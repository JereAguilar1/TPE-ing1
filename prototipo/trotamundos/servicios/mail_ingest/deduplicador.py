"""Módulo `deduplicador` (vista N2, §3; ADR-0014, CRN-12).

Bandeja de entrada por `(buzón, idDeMensaje)`: el mismo mensaje puede llegar por el aviso y por la
reconciliación (ADR-0004), y se publica una sola vez. También queda registrado lo que no se
publicó, con su motivo: nada se descarta en silencio.

La ventana es la de la bandeja de entrada (14 días, iteración 2 §5.11), que supera el intervalo
máximo de reconciliación.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import psycopg

RETENCION = timedelta(days=14)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS mensaje_recibido (
        buzon_id      uuid        NOT NULL,
        id_de_mensaje text        NOT NULL,
        usuario_id    uuid        NOT NULL,
        descartado    text,
        recibido_en   timestamptz NOT NULL,
        PRIMARY KEY (buzon_id, id_de_mensaje)
    );
    CREATE INDEX IF NOT EXISTS mensaje_recibido_por_antiguedad ON mensaje_recibido (recibido_en);
    """,
)


def ya_recibido(conexion: psycopg.Connection, buzon_id: UUID | str, id_de_mensaje: str) -> bool:
    """Para no volver a bajar lo que ya se procesó."""
    return conexion.execute(
        "SELECT 1 FROM mensaje_recibido WHERE buzon_id = %s AND id_de_mensaje = %s",
        (str(buzon_id), id_de_mensaje)).fetchone() is not None


def registrar(conexion: psycopg.Connection, buzon_id: UUID | str, usuario_id: UUID | str,
              id_de_mensaje: str, ahora: datetime, descartado: str | None = None) -> bool:
    """`True` si el mensaje es nuevo; `False` si ya estaba (y entonces no se publica)."""
    fila = conexion.execute(
        """INSERT INTO mensaje_recibido (buzon_id, id_de_mensaje, usuario_id, descartado,
                                         recibido_en)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING buzon_id""",
        (str(buzon_id), id_de_mensaje, str(usuario_id), descartado, ahora)).fetchone()
    return fila is not None


def purgar(conexion: psycopg.Connection, ahora: datetime) -> int:
    return conexion.execute("DELETE FROM mensaje_recibido WHERE recibido_en < %s",
                            (ahora - RETENCION,)).rowcount
