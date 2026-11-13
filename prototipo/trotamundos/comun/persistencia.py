"""Persistencia compartida en PostgreSQL: transacciones, *outbox*, bandeja de entrada y
`Idempotency-Key` (ADR-0012, ADR-0014).

Cada servicio es dueño de sus datos (ADR-0001) y tiene su propio esquema de PostgreSQL. Las tres
tablas de este módulo son las mismas en todos los servicios, y se crean dentro del esquema de cada
uno:

* `bandeja_salida` (*outbox*): el evento se escribe en la misma transacción que el cambio, así que
  no hay eventos perdidos ni eventos de cambios que no ocurrieron (ADR-0012). La publica el
  paso 6.
* `bandeja_entrada`: clave única `(consumidor, evento_id)`. Un evento repetido no produce un
  segundo efecto (ADR-0014).
* `comando_idempotente`: clave `(usuario_id, clave)` de la cabecera `Idempotency-Key`. Dos
  comandos con la misma clave producen un solo efecto y la misma respuesta (`comun.yaml`).

Toda tabla lleva `usuario_id`, la clave de partición (ADR-0012). En la *outbox* y la bandeja de
entrada es nulo solo para los eventos que no pueden identificar al usuario (`CuentaSuprimida`,
ADR-0030).
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Iterator
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento

# Ventana de la bandeja de entrada (iteración 2 §5.11): debe superar el intervalo máximo de
# reconciliación de ADR-0004. Se usa la misma para las claves de idempotencia.
RETENCION = timedelta(days=14)

_ESQUEMA_VALIDO = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

DDL = (
    """
    CREATE TABLE IF NOT EXISTS bandeja_salida (
        evento_id          uuid PRIMARY KEY,
        usuario_id         uuid,
        tipo               text        NOT NULL,
        topico             text        NOT NULL,
        clave_de_particion text        NOT NULL,
        sobre              jsonb       NOT NULL,
        carga              jsonb       NOT NULL,
        creado_en          timestamptz NOT NULL DEFAULT now(),
        publicado_en       timestamptz
    );
    CREATE INDEX IF NOT EXISTS bandeja_salida_pendientes
        ON bandeja_salida (creado_en) WHERE publicado_en IS NULL;
    """,
    """
    CREATE TABLE IF NOT EXISTS bandeja_entrada (
        consumidor  text        NOT NULL,
        evento_id   uuid        NOT NULL,
        usuario_id  uuid,
        recibido_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (consumidor, evento_id)
    );
    CREATE INDEX IF NOT EXISTS bandeja_entrada_por_antiguedad ON bandeja_entrada (recibido_en);
    """,
    """
    CREATE TABLE IF NOT EXISTS comando_idempotente (
        usuario_id uuid        NOT NULL,
        clave      uuid        NOT NULL,
        operacion  text        NOT NULL,
        huella     text        NOT NULL,
        estado     integer     NOT NULL,
        respuesta  jsonb,
        creado_en  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (usuario_id, clave)
    );
    CREATE INDEX IF NOT EXISTS comando_idempotente_por_antiguedad ON comando_idempotente (creado_en);
    """,
)


# --- conexión y transacciones ----------------------------------------------------------------

def _exigir_esquema(esquema: str) -> str:
    if not _ESQUEMA_VALIDO.match(esquema):
        raise ValueError(f"Nombre de esquema inválido: {esquema!r}")
    return esquema


def conectar(dsn: str, esquema: str) -> psycopg.Connection:
    """Conexión cuyas consultas sin calificar van al esquema del servicio. Las filas son dicts."""
    return psycopg.connect(dsn, row_factory=dict_row,
                           options=f"-c search_path={_exigir_esquema(esquema)}")


@contextmanager
def transaccion(dsn: str, esquema: str) -> Iterator[psycopg.Connection]:
    """Una transacción: se confirma al salir y se deshace entera si hubo una excepción."""
    with conectar(dsn, esquema) as conexion:
        yield conexion


def crear_esquema(dsn: str, esquema: str, ddl: Iterable[str]) -> None:
    """Crea el esquema y sus tablas si no existen (incluidas las de este módulo)."""
    with conectar(dsn, esquema) as conexion:
        conexion.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
            sql.Identifier(_exigir_esquema(esquema))))
        for sentencia in (*DDL, *ddl):
            conexion.execute(sentencia)


def bloquear_usuario(conexion: psycopg.Connection, usuario_id: UUID | str) -> None:
    """Serializa hasta el fin de la transacción todo lo que se escribe para un usuario.

    Es lo que en producción da la partición por usuario en su región primaria (ADR-0018): la
    bandeja de entrada y la resolución de identidad suponen que nada más escribe a la vez para el
    mismo usuario (riesgo R-4).
    """
    conexion.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(usuario_id),))


# --- outbox ----------------------------------------------------------------------------------

def escribir_en_outbox(conexion: psycopg.Connection, eventos: Iterable[Evento],
                       contratos: Contratos) -> None:
    """Agrega los eventos a la *outbox* de la transacción en curso. Cada uno se valida antes
    contra el contrato AsyncAPI: nada sale del servicio sin cumplirlo (ADR-0009)."""
    for evento in eventos:
        evento.validar(contratos)
        conexion.execute(
            """INSERT INTO bandeja_salida
                   (evento_id, usuario_id, tipo, topico, clave_de_particion, sobre, carga)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (evento.id, evento.sobre.get("usuarioId"), evento.tipo,
             contratos.canal_de_evento(evento.tipo), evento.clave_de_particion,
             Jsonb(evento.sobre), Jsonb(evento.carga)),
        )


# --- bandeja de entrada ----------------------------------------------------------------------

def registrar_en_bandeja_de_entrada(conexion: psycopg.Connection, consumidor: str,
                                    evento: Evento) -> bool:
    """`True` si el evento es nuevo para el consumidor; `False` si ya se procesó (ADR-0014)."""
    fila = conexion.execute(
        """INSERT INTO bandeja_entrada (consumidor, evento_id, usuario_id) VALUES (%s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING evento_id""",
        (consumidor, evento.id, evento.sobre.get("usuarioId")),
    ).fetchone()
    return fila is not None


# --- Idempotency-Key -------------------------------------------------------------------------

@dataclass(frozen=True)
class RespuestaGuardada:
    operacion: str
    huella: str
    estado: int
    cuerpo: Any


def huella_de_solicitud(cuerpo: Any) -> str:
    """Resumen del cuerpo, para detectar una clave reutilizada con otra solicitud."""
    canonico = json.dumps(cuerpo, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode()).hexdigest()


def respuesta_guardada(conexion: psycopg.Connection, usuario_id: UUID | str,
                       clave: UUID | str) -> RespuestaGuardada | None:
    fila = conexion.execute(
        """SELECT operacion, huella, estado, respuesta FROM comando_idempotente
           WHERE usuario_id = %s AND clave = %s""",
        (str(usuario_id), str(clave)),
    ).fetchone()
    if fila is None:
        return None
    return RespuestaGuardada(fila["operacion"], fila["huella"], fila["estado"], fila["respuesta"])


def guardar_respuesta(conexion: psycopg.Connection, usuario_id: UUID | str, clave: UUID | str,
                      respuesta: RespuestaGuardada) -> None:
    conexion.execute(
        """INSERT INTO comando_idempotente (usuario_id, clave, operacion, huella, estado, respuesta)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (str(usuario_id), str(clave), respuesta.operacion, respuesta.huella, respuesta.estado,
         Jsonb(respuesta.cuerpo)),
    )


def reemplazar_respuesta(conexion: psycopg.Connection, usuario_id: UUID | str, clave: UUID | str,
                         cuerpo: Any) -> None:
    """Completa la respuesta guardada de un comando que termina en una segunda transacción (por
    ejemplo, un alta que después se agrupa en un viaje)."""
    conexion.execute("UPDATE comando_idempotente SET respuesta = %s WHERE usuario_id = %s AND clave = %s",
                     (Jsonb(cuerpo), str(usuario_id), str(clave)))


# --- retención -------------------------------------------------------------------------------

def purgar(conexion: psycopg.Connection, ahora: datetime, retencion: timedelta = RETENCION) -> int:
    """Borra las entradas de la bandeja de entrada y las claves de idempotencia vencidas."""
    limite = ahora - retencion
    borradas = conexion.execute("DELETE FROM bandeja_entrada WHERE recibido_en < %s",
                                (limite,)).rowcount
    borradas += conexion.execute("DELETE FROM comando_idempotente WHERE creado_en < %s",
                                 (limite,)).rowcount
    return borradas
