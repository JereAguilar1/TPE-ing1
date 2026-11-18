"""Módulo `sesiones` del asistente: la memoria mínima de una conversación (ADR-0040).

Por sesión se guarda el viaje en foco, la acción pendiente con su vencimiento y el contador de «no
entendidos»; por turno, el texto, la intención y la hora. Todo lleva `usuario_id` en la clave
(ADR-0012). No se guardan copias del itinerario. Una sesión sin turnos durante 30 días se borra con
sus turnos (retención, segunda línea de defensa de la supresión).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

RETENCION = timedelta(days=30)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS sesion (
        usuario_id      uuid        NOT NULL,
        sesion_id       uuid        NOT NULL,
        abierta_en      timestamptz NOT NULL,
        ultimo_turno_en timestamptz NOT NULL,
        idioma          text        NOT NULL,
        viaje_id        uuid,
        no_entendidos   integer     NOT NULL DEFAULT 0,
        accion          jsonb,
        PRIMARY KEY (usuario_id, sesion_id)
    );
    CREATE INDEX IF NOT EXISTS sesion_por_ultimo_turno ON sesion (ultimo_turno_en);
    """,
    """
    CREATE TABLE IF NOT EXISTS turno (
        usuario_id uuid        NOT NULL,
        sesion_id  uuid        NOT NULL,
        numero     integer     NOT NULL,
        autor      text        NOT NULL CHECK (autor IN ('viajero', 'asistente')),
        texto      text        NOT NULL,
        intencion  text,
        en         timestamptz NOT NULL,
        PRIMARY KEY (usuario_id, sesion_id, numero),
        FOREIGN KEY (usuario_id, sesion_id) REFERENCES sesion ON DELETE CASCADE
    );
    """,
)


def abrir(conexion: psycopg.Connection, usuario_id: UUID | str, sesion_id: UUID | str,
          idioma: str, viaje_id: str | None, ahora: datetime) -> dict[str, Any]:
    return conexion.execute(
        """INSERT INTO sesion (usuario_id, sesion_id, abierta_en, ultimo_turno_en, idioma, viaje_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (str(usuario_id), str(sesion_id), ahora, ahora, idioma, viaje_id)).fetchone()


def obtener(conexion: psycopg.Connection, usuario_id: UUID | str,
            sesion_id: UUID | str) -> dict[str, Any] | None:
    """La sesión, solo si es del usuario: una ajena no existe para él (ADR-0040)."""
    return conexion.execute("SELECT * FROM sesion WHERE usuario_id = %s AND sesion_id = %s",
                            (str(usuario_id), str(sesion_id))).fetchone()


def turnos(conexion: psycopg.Connection, usuario_id: UUID | str,
           sesion_id: UUID | str) -> list[dict[str, Any]]:
    return conexion.execute(
        """SELECT autor, texto, intencion, en FROM turno
           WHERE usuario_id = %s AND sesion_id = %s ORDER BY numero""",
        (str(usuario_id), str(sesion_id))).fetchall()


def agregar_turno(conexion: psycopg.Connection, usuario_id: UUID | str, sesion_id: UUID | str,
                  autor: str, texto: str, intencion: str | None, en: datetime) -> None:
    conexion.execute(
        """INSERT INTO turno (usuario_id, sesion_id, numero, autor, texto, intencion, en)
           SELECT %s, %s, COALESCE(MAX(numero), 0) + 1, %s, %s, %s, %s FROM turno
           WHERE usuario_id = %s AND sesion_id = %s""",
        (str(usuario_id), str(sesion_id), autor, texto, intencion, en,
         str(usuario_id), str(sesion_id)))


def actualizar(conexion: psycopg.Connection, usuario_id: UUID | str, sesion_id: UUID | str, *,
               viaje_id: str | None, no_entendidos: int, accion: Mapping[str, Any] | None,
               ahora: datetime) -> None:
    conexion.execute(
        """UPDATE sesion SET viaje_id = %s, no_entendidos = %s, accion = %s, ultimo_turno_en = %s
           WHERE usuario_id = %s AND sesion_id = %s""",
        (viaje_id, no_entendidos, Jsonb(accion) if accion is not None else None, ahora,
         str(usuario_id), str(sesion_id)))


def quitar_accion(conexion: psycopg.Connection, usuario_id: UUID | str,
                  sesion_id: UUID | str) -> None:
    conexion.execute("UPDATE sesion SET accion = NULL WHERE usuario_id = %s AND sesion_id = %s",
                     (str(usuario_id), str(sesion_id)))


def purgar_vencidas(conexion: psycopg.Connection, ahora: datetime) -> int:
    """Borra las sesiones (y sus turnos) con más de 30 días sin turnos."""
    return conexion.execute("DELETE FROM sesion WHERE ultimo_turno_en < %s",
                            (ahora - RETENCION,)).rowcount


# --- representación del contrato --------------------------------------------------------------

def accion_publica(accion: Mapping[str, Any] | None, ahora: datetime) -> dict[str, Any] | None:
    """La `AccionPropuesta` del contrato, sin los datos internos para ejecutarla; `None` si no hay
    o ya venció."""
    if accion is None or datetime.fromisoformat(accion["venceEn"]) <= ahora:
        return None
    return {k: v for k, v in accion.items() if k != "datos"}


def a_dict(sesion: Mapping[str, Any], filas_de_turnos: list[Mapping[str, Any]],
           ahora: datetime) -> dict[str, Any]:
    """`Sesion` de `virtual-assistant.yaml`."""
    datos: dict[str, Any] = {
        "id": str(sesion["sesion_id"]), "abiertaEn": sesion["abierta_en"].isoformat(),
        "turnos": [{"autor": t["autor"], "texto": t["texto"], "en": t["en"].isoformat(),
                    **({"intencion": t["intencion"]} if t["intencion"] else {})}
                   for t in filas_de_turnos]}
    if sesion["viaje_id"] is not None:
        datos["viajeId"] = str(sesion["viaje_id"])
    pendiente = accion_publica(sesion["accion"], ahora)
    if pendiente is not None:
        datos["accionPendiente"] = pendiente
    return datos
