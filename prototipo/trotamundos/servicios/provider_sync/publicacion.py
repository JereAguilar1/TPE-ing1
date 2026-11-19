"""Módulo `publicacion` de `provider-sync` (iteración 2 §5.5; ADR-0012, ADR-0014, ADR-0020).

Escribe en la *outbox* (`bandeja_salida`) los eventos `ReservaObservada` y `DisrupcionDetectada`.
El carril de `ReservaObservada` sale de la regla del contrato AsyncAPI: `P1` si el viaje está
`EnCurso` o empieza en menos de 48 h (o si es una cancelación / disrupción), y `P2` en otro caso.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

import psycopg

from trotamundos.comun.carriles import Carril
from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"ReservaObservada", "DisrupcionDetectada"})
UMBRAL_P1 = timedelta(hours=48)


def carril_reserva_observada(observacion: Mapping[str, Any], *,
                             inicio_proximo: datetime | None,
                             fin_ultimo: datetime | None,
                             ahora: datetime,
                             tiene_disrupcion: bool = False) -> Carril:
    """Regla `x-carril` de `ReservaObservada`: `P1` si está `EnCurso` o empieza en < 48 h, `P2` si no."""
    if tiene_disrupcion or observacion.get("cancelada") is True:
        return Carril.P1
    if inicio_proximo is not None:
        en_curso = inicio_proximo <= ahora and (fin_ultimo is None or fin_ultimo >= ahora)
        proxima = timedelta(0) <= (inicio_proximo - ahora) < UMBRAL_P1
        if en_curso or proxima:
            return Carril.P1
    return Carril.P2


def registrar(conexion: psycopg.Connection,
              eventos: Iterable[Evento | tuple[Evento, Carril | str]],
              contratos: Contratos) -> None:
    lista: list[Evento] = []
    carriles_por_id: dict[str, str] = {}
    for item in eventos:
        if isinstance(item, tuple):
            evento, carril = item
            carriles_por_id[evento.id] = Carril(carril).value
        else:
            evento = item
        if evento.tipo not in PUBLICA:
            raise ValueError(f"provider-sync no publica {evento.tipo}")
        lista.append(evento)
    escribir_en_outbox(
        conexion,
        lista,
        contratos,
        carril_de=lambda e: carriles_por_id.get(e.id, Carril.P2.value),
    )
