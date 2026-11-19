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
from trotamundos.comun.modelo import limites_del_extremo
from trotamundos.comun.persistencia import escribir_en_outbox

PUBLICA = frozenset({"ReservaObservada", "DisrupcionDetectada"})
UMBRAL_P1 = timedelta(hours=48)


def _ventana_es_p1(inicio: datetime | None, fin: datetime | None, ahora: datetime) -> bool:
    if inicio is None:
        return False
    en_curso = inicio <= ahora and (fin is None or fin >= ahora)
    proxima = timedelta(0) <= (inicio - ahora) < UMBRAL_P1
    return en_curso or proxima


def _limites_observacion(observacion: Mapping[str, Any]
                         ) -> tuple[datetime | None, datetime | None]:
    inicios: list[datetime] = []
    fines: list[datetime] = []
    for seg in observacion.get("segmentos") or ():
        if not isinstance(seg, Mapping) or "inicio" not in seg or "fin" not in seg:
            continue
        inicio, _ = limites_del_extremo(seg["inicio"])
        _, fin = limites_del_extremo(seg["fin"])
        inicios.append(inicio)
        fines.append(fin)
    if not inicios:
        return None, None
    return min(inicios), max(fines)


def carril_reserva_observada(observacion: Mapping[str, Any], *,
                             inicio_proximo: datetime | None,
                             fin_ultimo: datetime | None,
                             ahora: datetime,
                             tiene_disrupcion: bool = False) -> Carril:
    """Regla `x-carril` de `ReservaObservada`: `P1` si está `EnCurso` o empieza en < 48 h, `P2` si no."""
    if tiene_disrupcion or observacion.get("cancelada") is True:
        return Carril.P1
    if _ventana_es_p1(inicio_proximo, fin_ultimo, ahora):
        return Carril.P1
    obs_inicio, obs_fin = _limites_observacion(observacion)
    if _ventana_es_p1(obs_inicio, obs_fin, ahora):
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
