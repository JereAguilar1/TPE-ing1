"""Escenario del paso 9 completo contra los contenedores: una reserva de hotel llega por correo.

El viajero reenvía la confirmación del vuelo a Mendoza y la reserva del hotel en Mendoza. El
extractor de hotel (un complemento más, sin cambios en `booking-extraction`) la lee, `itinerary`
la fusiona y la agrupa en el mismo viaje que el vuelo (RF-07), y el panel de `bff-web` la muestra
como un tramo `hotel`.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import Viajero, ahora, esperar, exigir_contenedores


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def _viaje_con(viajero: Viajero, *localizadores: str):
    datos, _ = viajero.panel()
    for viaje in datos["viajesActivos"]:
        codigos = {i["codigo"] for r in viaje["reservas"] for i in r["identificadores"]}
        if set(localizadores) <= codigos:
            return viaje
    return None


def test_el_hotel_llega_por_correo_y_se_agrupa_con_el_vuelo(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    vuelo, hotel = f"V{uuid4().hex[:5].upper()}", f"H{uuid4().hex[:5].upper()}"
    salida = (ahora() + timedelta(days=20)).replace(minute=0, second=0, microsecond=0)
    assert viajero.reenviar_confirmacion(vuelo, salida).status_code == 202
    assert viajero.reenviar_reserva_de_hotel(hotel, salida + timedelta(hours=4)).status_code == 202

    viaje = esperar(lambda: _viaje_con(viajero, vuelo, hotel), 120,
                    "el vuelo y el hotel quedan en el mismo viaje")
    tipos = sorted(s["tipo"] for r in viaje["reservas"] for s in r["segmentos"])
    assert tipos == ["hotel", "vuelo"]
    (estadia,) = [s for r in viaje["reservas"] for s in r["segmentos"] if s["tipo"] == "hotel"]
    assert estadia["detalle"] == {"habitaciones": 1, "huespedes": 2, "regimen": "desayuno"}
