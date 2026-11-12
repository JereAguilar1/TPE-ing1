"""Módulo `proyeccion-panel` (vista N2): modelos de lectura mantenidos por eventos internos.

No importa lógica de dominio (regla I3): lee las cargas de los eventos, que ya tienen la forma
del contrato. Por eso la lectura se puede desplegar sola, en `itinerary-lectura` (ADR-0021).

En este paso mantiene `reserva_lectura`, la reserva consolidada que sirve `GET /reservas/{id}`.
Las reservas descartadas, dadas de baja o absorbidas por una unificación salen de la lectura. El
panel del usuario (`panel_usuario`) llega con el paso 5.
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.eventos import Evento

DDL = (
    """
    CREATE TABLE IF NOT EXISTS reserva_lectura (
        usuario_id uuid   NOT NULL,
        reserva_id uuid   NOT NULL,
        version    bigint NOT NULL,
        datos      jsonb  NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id)
    );
    """,
)


def aplicar(conexion: psycopg.Connection, eventos: Iterable[Evento]) -> None:
    for evento in eventos:
        if evento.tipo != "ReservaActualizada":
            continue
        usuario, reserva = evento.sobre["usuarioId"], evento.carga["reserva"]
        for absorbida in evento.carga.get("unificadaCon", []):
            _borrar(conexion, usuario, absorbida)
        if reserva["estado"] == "Descartada":
            _borrar(conexion, usuario, reserva["id"])
            continue
        # Una versión vieja que llegue tarde no pisa a una nueva.
        conexion.execute(
            """INSERT INTO reserva_lectura (usuario_id, reserva_id, version, datos)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (usuario_id, reserva_id) DO UPDATE
                   SET version = EXCLUDED.version, datos = EXCLUDED.datos
                   WHERE reserva_lectura.version < EXCLUDED.version""",
            (usuario, reserva["id"], reserva["version"], Jsonb(reserva)))


def leer_reserva(conexion: psycopg.Connection, usuario_id: UUID | str,
                 reserva_id: UUID | str) -> dict[str, Any] | None:
    fila = conexion.execute(
        "SELECT datos FROM reserva_lectura WHERE usuario_id = %s AND reserva_id = %s",
        (str(usuario_id), str(reserva_id))).fetchone()
    return fila["datos"] if fila else None


def _borrar(conexion: psycopg.Connection, usuario_id: str, reserva_id: str) -> None:
    conexion.execute("DELETE FROM reserva_lectura WHERE usuario_id = %s AND reserva_id = %s",
                     (usuario_id, reserva_id))
