"""Módulo `preferencias` de `notification`: la copia local de `PreferenciasActualizadas`.

Con la copia local, ningún aviso llama a `preferences` durante un pico (QA-04). Mientras no llegó
ninguna, valen los valores por omisión del contrato `preferences.yaml`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

DDL = (
    """
    CREATE TABLE IF NOT EXISTS preferencias_local (
        usuario_id    uuid PRIMARY KEY,
        datos         jsonb       NOT NULL,
        ocurrido_en   timestamptz NOT NULL
    );
    """,
)

CANALES_POR_OMISION = {"push": True, "correo": True}
SILENCIO_POR_OMISION = {"desde": "22:00", "hasta": "07:00"}
ZONA_POR_OMISION = "America/Argentina/Buenos_Aires"


def aplicar(conexion: psycopg.Connection, usuario_id: UUID | str, datos: Mapping[str, Any],
            ocurrido_en: datetime) -> None:
    """Guarda la copia; un evento más viejo que la copia guardada no la pisa."""
    conexion.execute(
        """INSERT INTO preferencias_local (usuario_id, datos, ocurrido_en) VALUES (%s, %s, %s)
           ON CONFLICT (usuario_id) DO UPDATE SET datos = EXCLUDED.datos,
               ocurrido_en = EXCLUDED.ocurrido_en
           WHERE preferencias_local.ocurrido_en <= EXCLUDED.ocurrido_en""",
        (str(usuario_id), Jsonb(dict(datos)), ocurrido_en))


def de_usuario(conexion: psycopg.Connection, usuario_id: UUID | str) -> dict[str, Any]:
    fila = conexion.execute("SELECT datos FROM preferencias_local WHERE usuario_id = %s",
                            (str(usuario_id),)).fetchone()
    datos = dict(fila["datos"]) if fila else {}
    return {"zonaHoraria": datos.get("zonaHoraria", ZONA_POR_OMISION),
            "region": datos.get("region"),
            "canales": {**CANALES_POR_OMISION, **datos.get("canales", {})},
            "horasDeSilencio": {**SILENCIO_POR_OMISION, **datos.get("horasDeSilencio", {})}}
