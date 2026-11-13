"""Carril de los eventos de itinerary cuyo `x-carril` es una regla (ADR-0020, iteración 3 §5.3)."""

from datetime import datetime, timezone

from trotamundos.comun.eventos import Evento
from trotamundos.servicios.itinerary import publicacion


def test_el_carril_de_reserva_actualizada_depende_de_la_salida(observacion):
    reserva = {"segmentos": observacion["segmentos"]}  # del 1/12, 13 h, al 1/12, 15 h
    evento = Evento("ReservaActualizada", {}, {"reserva": reserva})
    assert publicacion.carril_de(evento, datetime(2026, 11, 20, tzinfo=timezone.utc)) == "P2"
    assert publicacion.carril_de(evento, datetime(2026, 11, 30, 14, tzinfo=timezone.utc)) == "P1"
    assert publicacion.carril_de(evento, datetime(2026, 12, 1, 14, tzinfo=timezone.utc)) == "P1"  # en curso
    assert publicacion.carril_de(evento, datetime(2026, 12, 2, tzinfo=timezone.utc)) == "P2"  # ya pasó
