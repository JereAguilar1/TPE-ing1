"""Publicador de la vista N2: resultados validados en la outbox (ADR-0012, ADR-0014)."""

from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"ReservaExtraida", "ExtraccionNoReconocida"})


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos) -> None:
    """Las dos salidas usan P2, según AsyncAPI; nunca se publica una reserva de banda baja."""
    lista = list(eventos)
    if any(evento.tipo not in PUBLICA for evento in lista):
        raise ValueError("booking-extraction solo publica sus resultados de extracción")
    escribir_en_outbox(conexion, lista, contratos)
