"""Módulo `filtros` (RF-04; iteración 2 §5.4; `contratos/openapi/mail-ingest-filtros.yaml`).

Tres listas: el **catálogo** de remitentes reconocidos (derivado de los manifiestos de los
extractores), los **permitidos** y los **bloqueados** por el usuario. Precedencia: bloqueados >
permitidos > catálogo. Un remitente que no figura en ninguna no es correo de viaje y no se baja.
Se evalúa sobre los metadatos, **antes** de descargar el cuerpo: así el sistema procesa menos
datos personales.

El catálogo se deriva del manifiesto declarativo compartido con el registro de extractores.

Un patrón es una dirección exacta (`reservas@miagencia.com`) o un dominio (`*@miagencia.com`). El
dominio no incluye subdominios: `*@aerolinea.com` no cubre `avisos.aerolinea.com`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID

import psycopg

DDL = (
    """
    CREATE TABLE IF NOT EXISTS filtros_de_correo (
        usuario_id     uuid        PRIMARY KEY,
        permitidos     text[]      NOT NULL,
        bloqueados     text[]      NOT NULL,
        actualizado_en timestamptz NOT NULL
    );
    """,
)


@dataclass(frozen=True)
class Filtros:
    permitidos: tuple[str, ...] = ()
    bloqueados: tuple[str, ...] = ()

    def a_dict(self) -> dict[str, list[str]]:
        """`FiltrosDeCorreo` del contrato."""
        return {"permitidos": list(self.permitidos), "bloqueados": list(self.bloqueados)}


def coincide(patron: str, remitente: str) -> bool:
    patron, remitente = patron.strip().lower(), remitente.strip().lower()
    if patron.startswith("*@"):
        return remitente.rpartition("@")[2] == patron[2:]
    if "@" not in patron:  # el contrato admite también el dominio solo
        return remitente.rpartition("@")[2] == patron
    if patron.startswith("@"):
        return remitente.rpartition("@")[2] == patron[1:]
    return remitente == patron


def admite(filtros: Filtros, remitente: str, catalogo: Iterable[str] = ()) -> bool:
    """¿Se baja el mensaje de `remitente`? Bloqueados > permitidos > catálogo."""
    if any(coincide(p, remitente) for p in filtros.bloqueados):
        return False
    if any(coincide(p, remitente) for p in filtros.permitidos):
        return True
    return any(coincide(p, remitente) for p in catalogo)


def admite_reenvio(filtros: Filtros, remitente: str) -> bool:
    """Lo que el usuario reenvía a su alias ya lo eligió él (ADR-0035: consentimiento activo):
    no hace falta que esté permitido ni en el catálogo, pero un bloqueado se descarta igual."""
    return not any(coincide(p, remitente) for p in filtros.bloqueados)


def de_usuario(conexion: psycopg.Connection, usuario_id: UUID | str) -> Filtros:
    fila = conexion.execute(
        "SELECT permitidos, bloqueados FROM filtros_de_correo WHERE usuario_id = %s",
        (str(usuario_id),)).fetchone()
    return Filtros(tuple(fila["permitidos"]), tuple(fila["bloqueados"])) if fila else Filtros()


def guardar(conexion: psycopg.Connection, usuario_id: UUID | str, filtros: Filtros,
            ahora: datetime) -> None:
    """Reemplaza las listas del usuario (`PUT /filtros-de-correo`). Sin repetidos, en el orden
    en que llegaron."""
    permitidos = list(dict.fromkeys(p.strip().lower() for p in filtros.permitidos))
    bloqueados = list(dict.fromkeys(p.strip().lower() for p in filtros.bloqueados))
    conexion.execute(
        """INSERT INTO filtros_de_correo (usuario_id, permitidos, bloqueados, actualizado_en)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (usuario_id) DO UPDATE SET permitidos = EXCLUDED.permitidos,
               bloqueados = EXCLUDED.bloqueados, actualizado_en = EXCLUDED.actualizado_en""",
        (str(usuario_id), permitidos, bloqueados, ahora))
