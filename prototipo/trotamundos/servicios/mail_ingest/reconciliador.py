"""Módulo `reconciliador`: el sondeo escalonado de ADR-0004 (vista N2, §3).

Cubre los buzones sin *push* (IMAP genérico) y la pérdida de avisos. Los sondeos se reparten en el
tiempo de forma determinista por `buzon_id`, para que la carga contra cada proveedor sea plana y no
una ráfaga sincronizada (ADR-0004, punto 3).

Intervalos: los «en reposo» de ADR-0024 (24 h con *push*, 6 h IMAP). El ajuste por viaje en curso
o próximo queda fuera del prototipo: `mail-ingest` no sabe de viajes (ver «Decisiones de
implementación» en el README).
"""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg

from trotamundos.servicios.mail_ingest import cola

INTERVALO_CON_PUSH = timedelta(hours=24)
INTERVALO_SIN_PUSH = timedelta(hours=6)
_EPOCA = datetime(2026, 1, 1, tzinfo=timezone.utc)


def proxima(buzon_id: UUID | str, intervalo: timedelta, ahora: datetime) -> datetime:
    """El próximo instante estrictamente posterior a `ahora` del turno fijo del buzón: un
    desplazamiento dentro del intervalo que sale de su id, siempre el mismo."""
    periodo = int(intervalo.total_seconds())
    desplazamiento = zlib.crc32(UUID(str(buzon_id)).bytes) % periodo
    transcurrido = int((ahora - _EPOCA).total_seconds())
    ultimo_turno = transcurrido - (transcurrido - desplazamiento) % periodo  # ≤ transcurrido
    return _EPOCA + timedelta(seconds=ultimo_turno + periodo)


def vencidos(conexion: psycopg.Connection, ahora: datetime, intervalos: dict[bool, timedelta],
             limite: int = 500) -> int:
    """Encola los buzones activos cuyo turno llegó y les fija el próximo; devuelve cuántos.
    `intervalos` va de «soporta *push*» al intervalo."""
    filas = conexion.execute(
        """SELECT buzon_id, usuario_id, soporta_push FROM buzon_ingesta
           WHERE activo AND proxima_reconciliacion <= %s
           ORDER BY proxima_reconciliacion LIMIT %s FOR UPDATE SKIP LOCKED""",
        (ahora, limite)).fetchall()
    for fila in filas:
        cola.encolar(conexion, fila["buzon_id"], fila["usuario_id"], "reconciliacion", ahora)
        conexion.execute(
            "UPDATE buzon_ingesta SET proxima_reconciliacion = %s WHERE buzon_id = %s",
            (proxima(fila["buzon_id"], intervalos[fila["soporta_push"]], ahora), fila["buzon_id"]))
    return len(filas)
