"""La *outbox* de `NotificacionEmitida` (ADR-0012), carril P3 según el contrato."""

from __future__ import annotations

from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"NotificacionEmitida"})


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos) -> None:
    lista = list(eventos)
    ajenos = sorted({e.tipo for e in lista} - PUBLICA)
    if ajenos:
        raise ValueError(f"notification no publica {', '.join(ajenos)}")
    escribir_en_outbox(conexion, lista, contratos)
