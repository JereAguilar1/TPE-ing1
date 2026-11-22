"""Módulo `avisos` de `notification`: la bandeja interna y las reglas transversales (iteración 2 §5.7).

* **Canal interno:** cada aviso queda en la tabla `aviso` en cuanto llega el evento, así que la
  coalescencia no consume el presupuesto de QA-01.
* **Correlación:** los eventos con el mismo `idDeCausa` (una disrupción y los cambios de reserva
  que provoca) producen **un solo** aviso por usuario; los siguientes solo suman a
  `eventos_agrupados` y, si el aviso todavía no salió, pueden subirle la severidad.
* **Coalescencia (30 s, decidida en la iteración 2):** el primer aviso de un viaje sale de inmediato; los
  siguientes de la misma severidad que llegan dentro de los 30 s se agrupan en uno solo, que el
  trabajo periódico emite al cerrarse la ventana.
* **Horas de silencio:** en la zona horaria del usuario, los avisos que no son críticos salen solo
  por el canal interno.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Mapping
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from trotamundos.servicios.notification.reglas import (
    ADMINISTRATIVA,
    CRITICA,
    INFORMATIVA,
    Aviso,
)

VENTANA = timedelta(seconds=30)
_RANGO = {INFORMATIVA: 0, ADMINISTRATIVA: 1, CRITICA: 2}

DDL = (
    """
    CREATE TABLE IF NOT EXISTS aviso (
        aviso_id          uuid PRIMARY KEY,
        usuario_id        uuid        NOT NULL,
        severidad         text        NOT NULL,
        motivo            text        NOT NULL,
        viaje_id          uuid,
        id_de_causa       text,
        eventos_agrupados integer     NOT NULL DEFAULT 1,
        creado_en         timestamptz NOT NULL,
        emitir_en         timestamptz NOT NULL,
        emitido_en        timestamptz,
        canales           text[]      NOT NULL DEFAULT '{interno}'
    );
    """,
    "CREATE INDEX IF NOT EXISTS aviso_por_viaje ON aviso (usuario_id, viaje_id, creado_en)",
    "CREATE INDEX IF NOT EXISTS aviso_por_causa ON aviso (usuario_id, id_de_causa)",
    "CREATE INDEX IF NOT EXISTS aviso_pendiente ON aviso (emitir_en) WHERE emitido_en IS NULL",
)


@dataclass(frozen=True)
class Emitido:
    """Un aviso que sale ahora: lo que se publica y lo que se entrega por los canales externos."""

    aviso_id: str
    usuario_id: str
    severidad: str
    motivo: str
    viaje_id: str | None
    id_de_causa: str | None
    eventos_agrupados: int
    canales: tuple[str, ...]


def en_silencio(preferencias: Mapping[str, Any], ahora: datetime) -> bool:
    try:
        zona = ZoneInfo(preferencias["zonaHoraria"])
    except (ZoneInfoNotFoundError, ValueError):
        zona = ZoneInfo("UTC")
    local = ahora.astimezone(zona).time()
    desde = time.fromisoformat(preferencias["horasDeSilencio"]["desde"])
    hasta = time.fromisoformat(preferencias["horasDeSilencio"]["hasta"])
    if desde == hasta:
        return False
    if desde < hasta:
        return desde <= local < hasta
    return local >= desde or local < hasta  # cruza la medianoche


def canales(severidad: str, preferencias: Mapping[str, Any], ahora: datetime) -> tuple[str, ...]:
    """Los canales por omisión de cada severidad, según lo que el usuario habilitó."""
    habilitados = preferencias["canales"]
    if severidad == CRITICA:  # no respeta las horas de silencio
        return ("interno", "push") if habilitados["push"] else ("interno", "correo")
    if en_silencio(preferencias, ahora):
        return ("interno",)
    if severidad == INFORMATIVA:
        return ("interno", "push") if habilitados["push"] else ("interno",)
    return ("interno", "correo") if habilitados["correo"] else ("interno",)


def registrar(conexion: psycopg.Connection, aviso: Aviso, preferencias: Mapping[str, Any],
              ahora: datetime) -> Emitido | None:
    """Guarda el aviso en la bandeja interna. Devuelve el `Emitido` si sale ahora; `None` si se
    correlacionó con otro o quedó agrupado para el cierre de la ventana."""
    if aviso.id_de_causa is not None:
        previo = conexion.execute(
            """SELECT * FROM aviso WHERE usuario_id = %s AND id_de_causa = %s
               ORDER BY creado_en LIMIT 1 FOR UPDATE""",
            (aviso.usuario_id, aviso.id_de_causa)).fetchone()
        if previo is not None:
            severidad = previo["severidad"]
            if previo["emitido_en"] is None and _RANGO[aviso.severidad] > _RANGO[severidad]:
                severidad = aviso.severidad
            conexion.execute("""UPDATE aviso SET eventos_agrupados = eventos_agrupados + 1,
                                severidad = %s WHERE aviso_id = %s""",
                             (severidad, previo["aviso_id"]))
            return None

    if aviso.viaje_id is not None:
        reciente = conexion.execute(
            """SELECT * FROM aviso WHERE usuario_id = %s AND viaje_id = %s AND severidad = %s
                 AND creado_en > %s
               ORDER BY creado_en DESC LIMIT 1 FOR UPDATE""",
            (aviso.usuario_id, aviso.viaje_id, aviso.severidad, ahora - VENTANA)).fetchone()
        if reciente is not None and reciente["emitido_en"] is None:
            conexion.execute("UPDATE aviso SET eventos_agrupados = eventos_agrupados + 1 "
                             "WHERE aviso_id = %s", (reciente["aviso_id"],))
            return None
        if reciente is not None:  # el primero ya salió: este espera el cierre de su ventana
            _insertar(conexion, aviso, ahora, emitir_en=reciente["emitido_en"] + VENTANA)
            return None

    elegidos = canales(aviso.severidad, preferencias, ahora)
    fila = _insertar(conexion, aviso, ahora, emitir_en=ahora, emitido_en=ahora, canales=elegidos)
    return _emitido(fila)


def emitir_vencidos(conexion: psycopg.Connection, ahora: datetime,
                    preferencias_de: Any) -> list[Emitido]:
    """Emite los avisos agrupados cuya ventana se cerró. `preferencias_de(conexion, usuario)` da la
    copia local de las preferencias de cada usuario."""
    filas = conexion.execute(
        """SELECT * FROM aviso WHERE emitido_en IS NULL AND emitir_en <= %s
           ORDER BY emitir_en FOR UPDATE SKIP LOCKED""", (ahora,)).fetchall()
    emitidos = []
    for fila in filas:
        elegidos = canales(fila["severidad"], preferencias_de(conexion, fila["usuario_id"]), ahora)
        fila = conexion.execute(
            "UPDATE aviso SET emitido_en = %s, canales = %s WHERE aviso_id = %s RETURNING *",
            (ahora, list(elegidos), fila["aviso_id"])).fetchone()
        emitidos.append(_emitido(fila))
    return emitidos


def de_usuario(conexion: psycopg.Connection, usuario_id: UUID | str) -> list[dict[str, Any]]:
    """La bandeja interna del usuario, del más nuevo al más viejo."""
    return conexion.execute("SELECT * FROM aviso WHERE usuario_id = %s ORDER BY creado_en DESC",
                            (str(usuario_id),)).fetchall()


def _insertar(conexion: psycopg.Connection, aviso: Aviso, ahora: datetime, *, emitir_en: datetime,
              emitido_en: datetime | None = None,
              canales: tuple[str, ...] = ("interno",)) -> dict[str, Any]:
    return conexion.execute(
        """INSERT INTO aviso (aviso_id, usuario_id, severidad, motivo, viaje_id, id_de_causa,
                              creado_en, emitir_en, emitido_en, canales)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (uuid4(), aviso.usuario_id, aviso.severidad, aviso.motivo, aviso.viaje_id,
         aviso.id_de_causa, ahora, emitir_en, emitido_en, list(canales))).fetchone()


def _emitido(fila: Mapping[str, Any]) -> Emitido:
    return Emitido(str(fila["aviso_id"]), str(fila["usuario_id"]), fila["severidad"],
                   fila["motivo"], str(fila["viaje_id"]) if fila["viaje_id"] else None,
                   fila["id_de_causa"], fila["eventos_agrupados"], tuple(fila["canales"]))
