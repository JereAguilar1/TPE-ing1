"""Módulo `publicador` (vista N2, §3): la *outbox* de `MensajeDeViajeRecibido` (ADR-0012).

El contrato pide P1 si el remitente corresponde a un viaje `EnCurso`; `mail-ingest` no sabe de
viajes, así que en el prototipo todo va por P2 (ver «Decisiones de implementación» en el README).
"""

from __future__ import annotations

from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"MensajeDeViajeRecibido"})


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos) -> None:
    """Valida contra AsyncAPI y escribe los eventos en `bandeja_salida`."""
    lista = list(eventos)
    ajenos = sorted({e.tipo for e in lista} - PUBLICA)
    if ajenos:
        raise ValueError(f"mail-ingest no publica {', '.join(ajenos)}")
    escribir_en_outbox(conexion, lista, contratos, lambda _evento: "P2")
