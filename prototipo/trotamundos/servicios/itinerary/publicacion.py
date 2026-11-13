"""Módulo `publicacion` (vista N2): la *outbox* de los eventos de dominio de `itinerary`.

Reacciona a los eventos internos sin importar lógica de dominio (regla I3): los escribe en la
`bandeja_salida` dentro de la misma transacción que el cambio (ADR-0012), validados contra el
contrato, con su carril de prioridad (ADR-0020). Llevarlos al *broker* lo hace
`comun.publicador`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import instante_desde_texto
from trotamundos.comun.persistencia import escribir_en_outbox

# Lo que publica itinerary (operaciones con `x-productor: itinerary` del contrato AsyncAPI).
PUBLICA = frozenset({"ReservaActualizada", "ReservaCancelada", "ConflictoDeFuentesDetectado",
                     "ViajeArmado", "ViajeCompletado", "ViajeArchivado"})
# Iteración 3 §5.3: van por P1 los cambios sobre viajes EnCurso o con salida en menos de 48 h.
HORIZONTE_CRITICO = timedelta(hours=48)


def registrar(conexion: psycopg.Connection, eventos: Iterable[Evento], contratos: Contratos,
              ahora: datetime | None = None) -> None:
    """Escribe los eventos en la outbox; `ahora` decide el carril de `ReservaActualizada`."""
    ahora = ahora or datetime.now(timezone.utc)
    eventos = list(eventos)
    ajenos = sorted({e.tipo for e in eventos} - PUBLICA)
    if ajenos:
        raise ValueError(f"itinerary no publica {', '.join(ajenos)}")
    escribir_en_outbox(conexion, eventos, contratos, lambda evento: carril_de(evento, ahora))


def carril_de(evento: Evento, ahora: datetime) -> str:
    """Carril de los eventos cuyo `x-carril` es «según la reserva» (`ReservaActualizada`): P1 si
    la reserva está en curso o empieza dentro de 48 h; P2 si no."""
    segmentos = evento.carga["reserva"]["segmentos"]
    inicio = min(instante_desde_texto(s["inicio"]["instante"]) for s in segmentos)
    fin = max(instante_desde_texto(s["fin"]["instante"]) for s in segmentos)
    return "P1" if inicio <= ahora + HORIZONTE_CRITICO and fin >= ahora else "P2"
