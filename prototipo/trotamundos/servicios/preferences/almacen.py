"""Las preferencias de cada viajero (`preferences.yaml`), una fila por `usuario_id` (ADR-0012).

Un viajero que nunca guardó las suyas tiene las de omisión del contrato: español rioplatense, hora
de Buenos Aires, la región del servicio, 3 días de gracia antes de archivar un viaje, push y correo
habilitados, silencio de 22:00 a 07:00 y sin agencia preferida.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

DDL = (
    """
    CREATE TABLE IF NOT EXISTS preferencias (
        usuario_id     uuid        PRIMARY KEY,
        datos          jsonb       NOT NULL,
        actualizado_en timestamptz NOT NULL
    );
    """,
)


def por_omision(region: str) -> dict[str, Any]:
    return {"agenciaPreferida": None, "idioma": "es-AR",
            "zonaHoraria": "America/Argentina/Buenos_Aires", "region": region,
            "diasDeGraciaArchivado": 3, "canales": {"push": True, "correo": True},
            "horasDeSilencio": {"desde": "22:00", "hasta": "07:00"}}


def completar(datos: Mapping[str, Any], region: str) -> dict[str, Any]:
    """Las preferencias con los valores de omisión en lo que no se indicó."""
    completas = por_omision(region)
    for clave, valor in datos.items():
        if isinstance(valor, Mapping) and isinstance(completas.get(clave), dict):
            completas[clave] = {**completas[clave], **valor}
        else:
            completas[clave] = copy.deepcopy(valor)
    return completas


def leer(conexion: psycopg.Connection, usuario_id: UUID | str, region: str) -> dict[str, Any]:
    fila = conexion.execute("SELECT datos FROM preferencias WHERE usuario_id = %s",
                            (str(usuario_id),)).fetchone()
    return fila["datos"] if fila else por_omision(region)


def guardar(conexion: psycopg.Connection, usuario_id: UUID | str, datos: Mapping[str, Any],
            ahora: datetime) -> bool:
    """Guarda las preferencias; `True` si cambiaron (solo entonces se publica el evento)."""
    previa = conexion.execute("SELECT datos FROM preferencias WHERE usuario_id = %s",
                              (str(usuario_id),)).fetchone()
    if previa is not None and previa["datos"] == dict(datos):
        return False
    conexion.execute(
        """INSERT INTO preferencias (usuario_id, datos, actualizado_en) VALUES (%s, %s, %s)
           ON CONFLICT (usuario_id) DO UPDATE
               SET datos = EXCLUDED.datos, actualizado_en = EXCLUDED.actualizado_en""",
        (str(usuario_id), Jsonb(dict(datos)), ahora))
    return True
