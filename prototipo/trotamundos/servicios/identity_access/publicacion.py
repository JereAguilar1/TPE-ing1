"""Módulo `publicacion`: *outbox* de los eventos de dominio de `identity-access` (ADR-0012).

Publica `EstadoDeBuzonCambiado` (carril `P2`) y `CuentaSuprimida` (carril `P3`, `SobreSinUsuario`).
"""

from __future__ import annotations

from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"EstadoDeBuzonCambiado", "CuentaSuprimida"})


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos) -> None:
    """Valida contra AsyncAPI y escribe los eventos en `bandeja_salida`."""
    lista = list(eventos)
    ajenos = sorted({e.tipo for e in lista} - PUBLICA)
    if ajenos:
        raise ValueError(f"identity-access no publica {', '.join(ajenos)}")
    escribir_en_outbox(
        conexion,
        lista,
        contratos,
        lambda e: "P3" if e.tipo == "CuentaSuprimida" else "P2",
    )
