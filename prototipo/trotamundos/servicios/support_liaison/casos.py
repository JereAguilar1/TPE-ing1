"""El caso de soporte (iteración 2 §5.7, RF-12, `contratos/openapi/support-liaison.yaml`).

Un caso guarda el **contexto del viaje en el momento de abrirlo** (una instantánea inmutable), el
motivo, la agencia destino y su estado: `Abierto` → `Derivado` → `EnGestion` → `Resuelto` o
`Cerrado`. Mientras la agencia no acusa recibo, sigue `Abierto` y se reintenta con espera creciente
(ADR-0024: `5 s × 2^n`, con tope de 15 min) durante 24 h.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.modelo import instante_a_texto

ESPERA_INICIAL = timedelta(seconds=5)
ESPERA_MAXIMA = timedelta(minutes=15)
VENTANA_DE_REINTENTO = timedelta(hours=24)
ABIERTOS_A_RESOLUCION = ("Abierto", "Derivado", "EnGestion")

DDL = (
    """
    CREATE TABLE IF NOT EXISTS caso (
        usuario_id         uuid        NOT NULL,
        caso_id            uuid        NOT NULL,
        viaje_id           uuid        NOT NULL,
        reserva_id         uuid,
        motivo             text        NOT NULL,
        descripcion        text,
        id_de_causa        text,
        agencia_id         text        NOT NULL,
        agencia_nombre     text        NOT NULL,
        estado             text        NOT NULL,
        instantanea        jsonb       NOT NULL,
        referencia_agencia text,
        abierto_en         timestamptz NOT NULL,
        derivado_en        timestamptz,
        resuelto_en        timestamptz,
        intentos           integer     NOT NULL DEFAULT 0,
        proxima_derivacion timestamptz,
        PRIMARY KEY (usuario_id, caso_id)
    );
    CREATE INDEX IF NOT EXISTS caso_por_derivar ON caso (proxima_derivacion)
        WHERE estado = 'Abierto' AND proxima_derivacion IS NOT NULL;
    """,
)


class CasoNoResoluble(Exception):
    """El caso ya está `Resuelto` o `Cerrado` (`409`)."""


def a_dict(fila: Mapping[str, Any]) -> dict[str, Any]:
    """`Caso` de `support-liaison.yaml`. La agencia se muestra por su nombre."""
    caso: dict[str, Any] = {
        "id": str(fila["caso_id"]), "viajeId": str(fila["viaje_id"]), "motivo": fila["motivo"],
        "agencia": fila["agencia_nombre"], "estado": fila["estado"],
        "abiertoEn": instante_a_texto(fila["abierto_en"]),
    }
    if fila["referencia_agencia"]:
        caso["referenciaAgencia"] = fila["referencia_agencia"]
    return caso


def abrir(conexion: psycopg.Connection, *, usuario_id: UUID, caso_id: UUID, viaje_id: UUID,
          reserva_id: UUID | None, motivo: str, descripcion: str | None, id_de_causa: str | None,
          agencia_id: str, agencia_nombre: str, instantanea: Mapping[str, Any],
          ahora: datetime) -> dict[str, Any]:
    return conexion.execute(
        """INSERT INTO caso (usuario_id, caso_id, viaje_id, reserva_id, motivo, descripcion,
                             id_de_causa, agencia_id, agencia_nombre, estado, instantanea,
                             abierto_en, proxima_derivacion)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Abierto', %s, %s, %s) RETURNING *""",
        (str(usuario_id), str(caso_id), str(viaje_id), str(reserva_id) if reserva_id else None,
         motivo, descripcion, id_de_causa, agencia_id, agencia_nombre, Jsonb(dict(instantanea)),
         ahora, ahora)).fetchone()


def obtener(conexion: psycopg.Connection, usuario_id: UUID | str,
            caso_id: UUID | str) -> dict[str, Any] | None:
    return conexion.execute("SELECT * FROM caso WHERE usuario_id = %s AND caso_id = %s",
                            (str(usuario_id), str(caso_id))).fetchone()


def marcar_derivado(conexion: psycopg.Connection, fila: Mapping[str, Any], referencia: str,
                    ahora: datetime) -> dict[str, Any]:
    return conexion.execute(
        """UPDATE caso SET estado = 'Derivado', referencia_agencia = %s, derivado_en = %s,
               proxima_derivacion = NULL
           WHERE usuario_id = %s AND caso_id = %s RETURNING *""",
        (referencia, ahora, fila["usuario_id"], fila["caso_id"])).fetchone()


def postergar(conexion: psycopg.Connection, fila: Mapping[str, Any], ahora: datetime) -> dict[str, Any]:
    """La agencia no respondió: otro intento más adelante, o ninguno si pasaron 24 h."""
    intentos = fila["intentos"] + 1
    espera = min(ESPERA_INICIAL * 2 ** (intentos - 1), ESPERA_MAXIMA)
    proxima = ahora + espera
    if proxima > fila["abierto_en"].astimezone(timezone.utc) + VENTANA_DE_REINTENTO:
        proxima = None  # queda Abierto; la agencia no acusó recibo en 24 h
    return conexion.execute(
        """UPDATE caso SET intentos = %s, proxima_derivacion = %s
           WHERE usuario_id = %s AND caso_id = %s RETURNING *""",
        (intentos, proxima, fila["usuario_id"], fila["caso_id"])).fetchone()


def por_derivar(conexion: psycopg.Connection, ahora: datetime, limite: int = 100) -> list[dict[str, Any]]:
    return conexion.execute(
        """SELECT usuario_id, caso_id FROM caso
           WHERE estado = 'Abierto' AND proxima_derivacion <= %s
           ORDER BY proxima_derivacion LIMIT %s""", (ahora, limite)).fetchall()


def resolver(conexion: psycopg.Connection, usuario_id: UUID, caso_id: UUID,
             ahora: datetime) -> dict[str, Any] | None:
    """El viajero lo marca resuelto cuando la agencia no ofrece interfaz de estado."""
    fila = obtener(conexion, usuario_id, caso_id)
    if fila is None:
        return None
    if fila["estado"] not in ABIERTOS_A_RESOLUCION:
        raise CasoNoResoluble(fila["estado"])
    return conexion.execute(
        """UPDATE caso SET estado = 'Resuelto', resuelto_en = %s, proxima_derivacion = NULL
           WHERE usuario_id = %s AND caso_id = %s RETURNING *""",
        (ahora, str(usuario_id), str(caso_id))).fetchone()


def para_la_agencia(fila: Mapping[str, Any]) -> dict[str, Any]:
    """Lo que se le entrega a la agencia: el caso canónico con su instantánea del viaje."""
    caso = {"casoId": str(fila["caso_id"]), "motivo": fila["motivo"],
            "viaje": fila["instantanea"], "abiertoEn": instante_a_texto(fila["abierto_en"])}
    if fila["reserva_id"]:
        caso["reservaId"] = str(fila["reserva_id"])
    if fila["descripcion"]:
        caso["descripcion"] = fila["descripcion"]
    if fila["id_de_causa"]:
        caso["idDeCausa"] = fila["id_de_causa"]
    return caso
