"""Copia local de la agencia preferida de cada viajero (UC-7: «copia local de preferences»).

La alimenta `PreferenciasActualizadas`, que publica `preferences`. Así, abrir un caso no depende de
que `preferences` responda. Sin agencia preferida, el caso no se puede abrir (`422`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

import psycopg

DDL = (
    """
    CREATE TABLE IF NOT EXISTS agencia_preferida (
        usuario_id     uuid        PRIMARY KEY,
        agencia_id     text        NOT NULL,
        agencia_nombre text        NOT NULL,
        actualizada_en timestamptz NOT NULL
    );
    """,
)


@dataclass(frozen=True)
class Agencia:
    id: str
    nombre: str


def aplicar(conexion: psycopg.Connection, usuario_id: UUID | str, preferencias: Mapping[str, Any],
            ahora: datetime) -> None:
    """Refleja `PreferenciasActualizadas`: guarda la agencia o la borra si quedó en `null`."""
    agencia = preferencias.get("agenciaPreferida")
    if not agencia:
        conexion.execute("DELETE FROM agencia_preferida WHERE usuario_id = %s", (str(usuario_id),))
        return
    conexion.execute(
        """INSERT INTO agencia_preferida (usuario_id, agencia_id, agencia_nombre, actualizada_en)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (usuario_id) DO UPDATE SET agencia_id = EXCLUDED.agencia_id,
               agencia_nombre = EXCLUDED.agencia_nombre, actualizada_en = EXCLUDED.actualizada_en""",
        (str(usuario_id), agencia["id"], agencia["nombre"], ahora))


def de_usuario(conexion: psycopg.Connection, usuario_id: UUID | str) -> Agencia | None:
    fila = conexion.execute(
        "SELECT agencia_id, agencia_nombre FROM agencia_preferida WHERE usuario_id = %s",
        (str(usuario_id),)).fetchone()
    return Agencia(fila["agencia_id"], fila["agencia_nombre"]) if fila else None
