"""Repositorio PostgreSQL del agregado `Reserva` (ADR-0012, iteración 2 §5.8).

Tablas: `reserva`, `reserva_identificador`, `observacion`, `segmento` y `conflicto`. Todas llevan
`usuario_id` en la clave (partición por usuario) y borran en cascada con su reserva. Las dos
restricciones de unicidad de ADR-0012 que son de este agregado las impone la base:

* `reserva_identificador`: clave `(usuario_id, emisor, codigo)`. Un identificador es de una sola
  reserva del usuario (ADR-0013).
* `observacion`: única por `(reserva_id, fuente, id_de_fuente)` (ADR-0014).

El núcleo de cada segmento va en columnas y el `detalle` en JSONB (ADR-0011: lo que se filtra u
ordena es núcleo). Los conflictos resueltos no se borran: quedan con estado `Resuelto`.

Cumple el puerto `RepositorioDeReservas` de `fusion` por su forma, sin importarlo (regla I1).
Dentro de una transacción devuelve siempre el mismo objeto para la misma reserva.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.modelo import (
    Fuente,
    Identificador,
    ObservacionCanonica,
    instante_a_texto,
    instante_desde_texto,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.itinerary.reservas import (
    Banda,
    ConflictoDeFuentes,
    Fijado,
    ObservacionRegistrada,
    Reserva,
    ValorEnDisputa,
    VistaConsolidada,
)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS reserva (
        usuario_id             uuid        NOT NULL,
        reserva_id             uuid        NOT NULL,
        estado                 text        NOT NULL,
        version                bigint      NOT NULL,
        creada_en              timestamptz NOT NULL,
        actualizada_en         timestamptz NOT NULL DEFAULT now(),
        cancelada              boolean     NOT NULL,
        confirmada_por_usuario boolean     NOT NULL,
        descartada             boolean     NOT NULL,
        fijados                jsonb       NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reserva_identificador (
        usuario_id uuid NOT NULL,
        emisor     text NOT NULL,
        codigo     text NOT NULL,
        reserva_id uuid NOT NULL,
        PRIMARY KEY (usuario_id, emisor, codigo),
        FOREIGN KEY (usuario_id, reserva_id) REFERENCES reserva ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS observacion (
        usuario_id        uuid             NOT NULL,
        reserva_id        uuid             NOT NULL,
        fuente            text             NOT NULL,
        id_de_fuente      text             NOT NULL,
        version_de_fuente timestamptz      NOT NULL,
        banda             text,
        confianza         double precision,
        carga             jsonb            NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id, fuente, id_de_fuente),
        CONSTRAINT observacion_unica UNIQUE (reserva_id, fuente, id_de_fuente),
        FOREIGN KEY (usuario_id, reserva_id) REFERENCES reserva ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS observacion_por_clave ON observacion (usuario_id, fuente, id_de_fuente);
    """,
    """
    CREATE TABLE IF NOT EXISTS segmento (
        usuario_id          uuid        NOT NULL,
        reserva_id          uuid        NOT NULL,
        segmento_id         uuid        NOT NULL,
        orden               integer     NOT NULL,
        tipo                text        NOT NULL,
        version_tipo        integer     NOT NULL,
        inicio_instante     timestamptz NOT NULL,
        inicio_precision    text        NOT NULL,
        inicio_zona_horaria text        NOT NULL,
        inicio_lugar        jsonb       NOT NULL,
        fin_instante        timestamptz NOT NULL,
        fin_precision       text        NOT NULL,
        fin_zona_horaria    text        NOT NULL,
        fin_lugar           jsonb       NOT NULL,
        operador            text        NOT NULL,
        referencia          text,
        estado              text        NOT NULL,
        detalle             jsonb       NOT NULL,
        fijados             text[]      NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id, segmento_id),
        FOREIGN KEY (usuario_id, reserva_id) REFERENCES reserva ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS segmento_por_inicio ON segmento (usuario_id, inicio_instante);
    """,
    """
    CREATE TABLE IF NOT EXISTS conflicto (
        usuario_id   uuid        NOT NULL,
        reserva_id   uuid        NOT NULL,
        conflicto_id uuid        NOT NULL,
        campo        text        NOT NULL,
        valores      jsonb       NOT NULL,
        estado       text        NOT NULL,
        abierto_en   timestamptz NOT NULL DEFAULT now(),
        resuelto_en  timestamptz,
        PRIMARY KEY (usuario_id, reserva_id, conflicto_id),
        FOREIGN KEY (usuario_id, reserva_id) REFERENCES reserva ON DELETE CASCADE
    );
    """,
)


class RepositorioDeReservasPostgres:
    """Lee y escribe reservas dentro de la transacción de `conexion`."""

    def __init__(self, conexion: psycopg.Connection, registro: RegistroDeTipos | None = None):
        self._conexion = conexion
        self._registro = registro
        self._cargadas: dict[UUID, Reserva] = {}

    # --- lectura -------------------------------------------------------------------------

    def obtener(self, usuario_id: UUID, reserva_id: UUID) -> Reserva | None:
        reserva_id = UUID(str(reserva_id))
        if reserva_id in self._cargadas:
            cargada = self._cargadas[reserva_id]
            return cargada if str(cargada.usuario_id) == str(usuario_id) else None
        fila = self._uno("SELECT * FROM reserva WHERE usuario_id = %s AND reserva_id = %s",
                         usuario_id, reserva_id)
        if fila is None:
            return None
        reserva = self._reconstruir(fila)
        self._cargadas[reserva_id] = reserva
        return reserva

    def por_identificador(self, usuario_id: UUID, identificador: Identificador) -> Reserva | None:
        fila = self._uno("""SELECT reserva_id FROM reserva_identificador
                            WHERE usuario_id = %s AND emisor = %s AND codigo = %s""",
                         usuario_id, identificador.emisor, identificador.codigo)
        return self.obtener(usuario_id, fila["reserva_id"]) if fila else None

    def por_observacion(self, usuario_id: UUID, clave: tuple[Fuente, str]) -> Reserva | None:
        fuente, id_de_fuente = clave
        fila = self._uno("""SELECT reserva_id FROM observacion
                            WHERE usuario_id = %s AND fuente = %s AND id_de_fuente = %s LIMIT 1""",
                         usuario_id, fuente.value, id_de_fuente)
        return self.obtener(usuario_id, fila["reserva_id"]) if fila else None

    def candidatas(self, usuario_id: UUID, desde: date, hasta: date) -> list[Reserva]:
        """Reservas con algún segmento que empieza cerca de `[desde, hasta]`. La ventana se
        ensancha un día para cubrir cualquier zona horaria: puede devolver de más, y quien
        sugiere compara después la fecha local exacta."""
        inicio = datetime.combine(desde - timedelta(days=1), time(), timezone.utc)
        fin = datetime.combine(hasta + timedelta(days=2), time(), timezone.utc)
        filas = self._conexion.execute(
            """SELECT DISTINCT reserva_id FROM segmento
               WHERE usuario_id = %s AND inicio_instante >= %s AND inicio_instante < %s""",
            (str(usuario_id), inicio, fin)).fetchall()
        return [r for f in filas if (r := self.obtener(usuario_id, f["reserva_id"])) is not None]

    # --- escritura -----------------------------------------------------------------------

    def guardar(self, reserva: Reserva) -> None:
        """Escribe el estado completo de la reserva (y su vista consolidada)."""
        c, u, r = self._conexion, str(reserva.usuario_id), str(reserva.id)
        vista = reserva.vista
        c.execute(
            """INSERT INTO reserva (usuario_id, reserva_id, estado, version, creada_en, cancelada,
                                    confirmada_por_usuario, descartada, fijados)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (usuario_id, reserva_id) DO UPDATE SET
                   estado = EXCLUDED.estado, version = EXCLUDED.version,
                   cancelada = EXCLUDED.cancelada, actualizada_en = now(),
                   confirmada_por_usuario = EXCLUDED.confirmada_por_usuario,
                   descartada = EXCLUDED.descartada, fijados = EXCLUDED.fijados""",
            (u, r, reserva.estado.value, reserva.version, reserva.creada_en, vista.cancelada,
             reserva.confirmada_por_usuario, reserva.descartada,
             Jsonb({f.campo: {"valor": f.valor, "fijadoEn": instante_a_texto(f.fijado_en)}
                    for f in reserva.fijados.values()})))

        c.execute("DELETE FROM reserva_identificador WHERE usuario_id = %s AND reserva_id = %s", (u, r))
        for identificador in sorted(reserva.identificadores, key=lambda i: (i.emisor, i.codigo)):
            c.execute("""INSERT INTO reserva_identificador (usuario_id, emisor, codigo, reserva_id)
                         VALUES (%s, %s, %s, %s)""", (u, identificador.emisor, identificador.codigo, r))

        for o in reserva.observaciones:
            c.execute(
                """INSERT INTO observacion (usuario_id, reserva_id, fuente, id_de_fuente,
                                            version_de_fuente, banda, confianza, carga)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (reserva_id, fuente, id_de_fuente) DO UPDATE SET
                       version_de_fuente = EXCLUDED.version_de_fuente, banda = EXCLUDED.banda,
                       confianza = EXCLUDED.confianza, carga = EXCLUDED.carga""",
                (u, r, o.fuente.value, o.observacion.id_de_fuente, o.version_de_fuente,
                 o.banda.value if o.banda else None, o.confianza, Jsonb(o.observacion.a_dict())))

        c.execute("DELETE FROM segmento WHERE usuario_id = %s AND reserva_id = %s", (u, r))
        for s in vista.segmentos:
            c.execute(
                """INSERT INTO segmento (usuario_id, reserva_id, segmento_id, orden, tipo, version_tipo,
                       inicio_instante, inicio_precision, inicio_zona_horaria, inicio_lugar,
                       fin_instante, fin_precision, fin_zona_horaria, fin_lugar,
                       operador, referencia, estado, detalle, fijados)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (u, r, s["id"], s["orden"], s["tipo"], s["versionTipo"],
                 *_extremo_a_columnas(s["inicio"]), *_extremo_a_columnas(s["fin"]),
                 s["operador"], s.get("referencia"), s["estado"], Jsonb(s["detalle"]),
                 list(s.get("fijados", []))))

        abiertos = [str(conflicto.id) for conflicto in vista.conflictos]
        c.execute("""UPDATE conflicto SET estado = 'Resuelto', resuelto_en = now()
                     WHERE usuario_id = %s AND reserva_id = %s AND estado = 'Abierto'
                       AND NOT (conflicto_id = ANY(%s::uuid[]))""", (u, r, abiertos))
        for conflicto in vista.conflictos:
            # El mismo conflicto puede volver a abrirse (la fuente vuelve a discrepar con el mismo
            # fijado) o cambiar de valores en disputa: la fila refleja siempre la vista.
            c.execute("""INSERT INTO conflicto (usuario_id, reserva_id, conflicto_id, campo, valores, estado)
                         VALUES (%s, %s, %s, %s, %s, 'Abierto')
                         ON CONFLICT (usuario_id, reserva_id, conflicto_id) DO UPDATE SET
                             valores = EXCLUDED.valores, estado = 'Abierto', resuelto_en = NULL""",
                      (u, r, str(conflicto.id), conflicto.campo,
                       Jsonb([v.a_dict() for v in conflicto.valores])))
        self._cargadas[reserva.id] = reserva

    def eliminar(self, reserva: Reserva) -> None:
        """Borra una reserva absorbida por una unificación (con todo lo suyo, en cascada)."""
        self._conexion.execute("DELETE FROM reserva WHERE usuario_id = %s AND reserva_id = %s",
                               (str(reserva.usuario_id), str(reserva.id)))
        self._cargadas.pop(reserva.id, None)

    # --- reconstrucción ------------------------------------------------------------------

    def _uno(self, consulta: str, *parametros: Any) -> dict | None:
        return self._conexion.execute(consulta, tuple(str(p) if isinstance(p, UUID) else p
                                                       for p in parametros)).fetchone()

    def _todas(self, tabla: str, fila: Mapping[str, Any], orden: str) -> list[dict]:
        return self._conexion.execute(
            f"SELECT * FROM {tabla} WHERE usuario_id = %s AND reserva_id = %s ORDER BY {orden}",
            (fila["usuario_id"], fila["reserva_id"])).fetchall()

    def _reconstruir(self, fila: Mapping[str, Any]) -> Reserva:
        observaciones = [
            ObservacionRegistrada(ObservacionCanonica.desde_dict(o["carga"]),
                                  banda=Banda(o["banda"]) if o["banda"] else None,
                                  confianza=o["confianza"])
            for o in self._todas("observacion", fila, "fuente, id_de_fuente")]
        # En el orden en que los arma la consolidación (por campo, como Python ordena el texto):
        # no depende de la intercalación de la base.
        conflictos = tuple(sorted((
            ConflictoDeFuentes(c["conflicto_id"], c["campo"], tuple(
                ValorEnDisputa(Fuente(v["fuente"]), v["valor"], instante_desde_texto(v["observadoEn"]))
                for v in c["valores"]))
            for c in self._todas("conflicto", fila, "conflicto_id") if c["estado"] == "Abierto"),
            key=lambda conflicto: conflicto.campo))
        vista = VistaConsolidada(
            segmentos=tuple(_segmento(s) for s in self._todas("segmento", fila, "orden")),
            cancelada=fila["cancelada"], conflictos=conflictos)
        return Reserva.restaurar(
            id=fila["reserva_id"], usuario_id=fila["usuario_id"], creada_en=fila["creada_en"],
            version=fila["version"], observaciones=observaciones,
            fijados=[Fijado(campo, f["valor"], instante_desde_texto(f["fijadoEn"]))
                     for campo, f in fila["fijados"].items()],
            identificadores=[Identificador(i["emisor"], i["codigo"])
                             for i in self._todas("reserva_identificador", fila, "emisor, codigo")],
            confirmada_por_usuario=fila["confirmada_por_usuario"],
            descartada=fila["descartada"], vista=vista, registro=self._registro)


def _extremo_a_columnas(extremo: Mapping[str, Any]) -> tuple:
    return (instante_desde_texto(extremo["instante"]), extremo["precision"],
            extremo["zonaHoraria"], Jsonb(extremo["lugar"]))


def _extremo(fila: Mapping[str, Any], prefijo: str) -> dict[str, Any]:
    return {"instante": instante_a_texto(fila[f"{prefijo}_instante"]),
            "precision": fila[f"{prefijo}_precision"],
            "zonaHoraria": fila[f"{prefijo}_zona_horaria"],
            "lugar": fila[f"{prefijo}_lugar"]}


def _segmento(fila: Mapping[str, Any]) -> dict[str, Any]:
    """El segmento con la misma forma con que lo armó la consolidación."""
    segmento: dict[str, Any] = {
        "id": str(fila["segmento_id"]), "orden": fila["orden"], "tipo": fila["tipo"],
        "versionTipo": fila["version_tipo"], "inicio": _extremo(fila, "inicio"),
        "fin": _extremo(fila, "fin"), "operador": fila["operador"], "estado": fila["estado"],
        "detalle": fila["detalle"],
    }
    if fila["referencia"] is not None:
        segmento["referencia"] = fila["referencia"]
    if fila["fijados"]:
        segmento["fijados"] = list(fila["fijados"])
    return segmento
