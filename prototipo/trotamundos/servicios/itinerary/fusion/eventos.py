"""Eventos de dominio que produce un cambio en una reserva (contrato AsyncAPI).

Solo `itinerary` publica la reserva, y ya fusionada (ajuste 1 de la iteración 2):

* `ReservaActualizada` cada vez que la reserva cambia: con la reserva completa, los `cambios`
  campo por campo y, si la hubo, la unificación (`unificadaCon`).
* `ReservaCancelada` cuando la reserva **pasa** a `Cancelada` (no por la vista sola: una reserva
  por confirmar no se cancela con datos de banda media, ADR-0015).
* `ConflictoDeFuentesDetectado` por cada conflicto nuevo (ADR-0013).

Los eventos son también los «eventos internos» de la vista N2: `publicacion` y
`proyeccion_panel` reaccionan a ellos sin importar lógica de dominio.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from trotamundos.comun.eventos import Causa, Evento
from trotamundos.comun.modelo import Fuente, instante_a_texto
from trotamundos.servicios.itinerary.fusion.consolidacion import Cambio, Consolidacion
from trotamundos.servicios.itinerary.reservas import CAMPO_CANCELADA, Reserva

PRODUCTOR = "itinerary"


def eventos_del_cambio(reserva: Reserva, consolidacion: Consolidacion, fuente: Fuente,
                       causa: Causa, ahora: datetime, *, hubo_cambio: bool, creada: bool = False,
                       unificadas: Iterable[Reserva] = ()) -> list[Evento]:
    """Eventos de un cambio ya consolidado. `fuente` es quien lo provocó (para el cambio de
    estado y la cancelación, si la vista no dice otra cosa)."""
    def nuevo(tipo: str, carga: dict) -> Evento:
        return Evento.nuevo(tipo, carga, productor=PRODUCTOR, usuario_id=str(reserva.usuario_id),
                            region=causa.region, id_de_causa=causa.id_de_causa,
                            traceparent=causa.traceparent,
                            id_de_correlacion=causa.id_de_correlacion)

    eventos: list[Evento] = []
    if hubo_cambio:
        cambios = list(consolidacion.cambios)
        if consolidacion.estado_anterior not in (None, consolidacion.estado):
            cambios.append(Cambio("estado", consolidacion.estado_anterior.value,
                                  consolidacion.estado.value, fuente))
        carga = {"reserva": reserva.a_dict(), "creada": creada,
                 "cambios": [c.a_dict() for c in cambios]}
        absorbidas = [str(r.id) for r in unificadas]
        if absorbidas:
            carga["unificadaCon"] = absorbidas
        eventos.append(nuevo("ReservaActualizada", carga))

    if consolidacion.cancelada_ahora:
        eventos.append(nuevo("ReservaCancelada", {
            "reservaId": str(reserva.id),
            "version": reserva.version,
            "fuente": reserva.vista.origen.get(CAMPO_CANCELADA, fuente).value,
            "canceladaEn": instante_a_texto(ahora),
        }))

    for conflicto in consolidacion.conflictos_nuevos:
        eventos.append(nuevo("ConflictoDeFuentesDetectado",
                             {"reservaId": str(reserva.id), "conflicto": conflicto.a_dict()}))
    return eventos
