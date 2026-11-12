"""Módulo `publicacion` (vista N2): la *outbox* de los eventos de dominio de `itinerary`.

Reacciona a los eventos internos sin importar lógica de dominio (regla I3): los escribe en la
`bandeja_salida` dentro de la misma transacción que el cambio (ADR-0012), validados contra el
contrato. Llevarlos al *broker* es del paso 6.
"""

from __future__ import annotations

from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

# Lo que publica itinerary (operaciones con `x-productor: itinerary` del contrato AsyncAPI). Los
# eventos de viajes llegan con el paso 5.
PUBLICA = frozenset({"ReservaActualizada", "ReservaCancelada", "ConflictoDeFuentesDetectado"})


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos) -> None:
    eventos = list(eventos)
    ajenos = sorted({e.tipo for e in eventos} - PUBLICA)
    if ajenos:
        raise ValueError(f"itinerary no publica {', '.join(ajenos)}")
    escribir_en_outbox(conexion, eventos, contratos)
