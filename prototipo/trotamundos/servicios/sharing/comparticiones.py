"""Módulo `comparticiones` de `sharing`: el agregado `Comparticion` y su tabla (ADR-0028).

Una compartición es del dueño del viaje (`usuario_id`, ADR-0012): una lista nominal de designados
por correo, con vencimiento (por omisión y como máximo, el fin del viaje + 30 días) y estado
`Activa` o `Revocada`; `Vencida` se calcula al leerla, así que vence sin trabajo periódico.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import UUID

import psycopg

GRACIA = timedelta(days=30)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS comparticion (
        comparticion_id uuid PRIMARY KEY,
        usuario_id      uuid        NOT NULL,
        viaje_id        uuid        NOT NULL,
        designados      text[]      NOT NULL,
        expira_en       timestamptz NOT NULL,
        revocada_en     timestamptz,
        creada_en       timestamptz NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS comparticion_por_viaje ON comparticion (usuario_id, viaje_id)",
    """
    CREATE TABLE IF NOT EXISTS publicacion (
        publicacion_id uuid PRIMARY KEY,
        usuario_id     uuid        NOT NULL,
        viaje_id       uuid        NOT NULL,
        red            text        NOT NULL,
        referencia     text        NOT NULL,
        publicada_en   timestamptz NOT NULL
    );
    """,
)


def vencimiento(pedido: datetime | None, fin_del_viaje: datetime) -> datetime:
    """El pedido, sin pasar del fin del viaje + 30 días (el máximo y el valor por omisión)."""
    maximo = fin_del_viaje + GRACIA
    return maximo if pedido is None else min(pedido, maximo)


def estado(fila: Mapping[str, Any], ahora: datetime) -> str:
    if fila["revocada_en"] is not None:
        return "Revocada"
    return "Vencida" if fila["expira_en"] <= ahora else "Activa"


def a_dict(fila: Mapping[str, Any], ahora: datetime) -> dict[str, Any]:
    return {"id": str(fila["comparticion_id"]), "viajeId": str(fila["viaje_id"]),
            "designados": list(fila["designados"]),
            "expiraEn": fila["expira_en"].isoformat().replace("+00:00", "Z"),
            "estado": estado(fila, ahora)}


def crear(conexion: psycopg.Connection, *, comparticion_id: UUID, usuario_id: UUID,
          viaje_id: UUID, designados: list[str], expira_en: datetime,
          ahora: datetime) -> dict[str, Any]:
    normalizados = sorted({d.strip().lower() for d in designados})
    return conexion.execute(
        """INSERT INTO comparticion (comparticion_id, usuario_id, viaje_id, designados, expira_en,
                                     creada_en)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (comparticion_id, usuario_id, viaje_id, normalizados, expira_en, ahora)).fetchone()


def del_viaje(conexion: psycopg.Connection, usuario_id: UUID, viaje_id: UUID) -> list[dict]:
    return conexion.execute(
        """SELECT * FROM comparticion WHERE usuario_id = %s AND viaje_id = %s
           ORDER BY creada_en""", (usuario_id, viaje_id)).fetchall()


def obtener(conexion: psycopg.Connection, comparticion_id: UUID) -> dict[str, Any] | None:
    return conexion.execute("SELECT * FROM comparticion WHERE comparticion_id = %s",
                            (comparticion_id,)).fetchone()


def revocar(conexion: psycopg.Connection, usuario_id: UUID, viaje_id: UUID,
            comparticion_id: UUID, ahora: datetime) -> bool:
    """`False` si no existe o no es de ese viaje y usuario (el mismo `404`)."""
    fila = conexion.execute(
        """UPDATE comparticion SET revocada_en = COALESCE(revocada_en, %s)
           WHERE comparticion_id = %s AND usuario_id = %s AND viaje_id = %s
           RETURNING comparticion_id""", (ahora, comparticion_id, usuario_id, viaje_id)).fetchone()
    return fila is not None


def registrar_publicacion(conexion: psycopg.Connection, *, publicacion_id: UUID, usuario_id: UUID,
                          viaje_id: UUID, red: str, referencia: str, ahora: datetime) -> None:
    conexion.execute(
        """INSERT INTO publicacion (publicacion_id, usuario_id, viaje_id, red, referencia,
                                    publicada_en) VALUES (%s, %s, %s, %s, %s, %s)""",
        (publicacion_id, usuario_id, viaje_id, red, referencia, ahora))
