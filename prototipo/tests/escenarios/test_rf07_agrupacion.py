"""RF-07 contra los contenedores: las reservas de un mismo viaje, llegadas por fuentes distintas,
quedan en un solo viaje (iteración 2 §5.1).

La ida y la vuelta llegan por correo (el aeropuerto trae su código IATA) y el hotel se carga a mano
(trae coordenadas y no código). El criterio de «misma ciudad» compara coordenadas cuando las dos
tienen, así que el extractor y el adaptador completan las de los aeropuertos que conocen.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    BFF_WEB,
    Viajero,
    ahora,
    esperar,
    exigir_contenedores,
    inicio_en_el_panel,
)


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def _localizador(prefijo: str) -> str:
    return (prefijo + uuid4().hex.upper())[:6]


def test_rf07_ida_hotel_y_vuelta_de_fuentes_distintas_forman_un_solo_viaje(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    ida = ahora().replace(microsecond=0, second=0, minute=0) + timedelta(days=8)
    vuelta = ida + timedelta(days=4)
    mendoza = {"nombre": "Hotel Aconcagua", "pais": "AR", "zonaHoraria": "America/Argentina/Mendoza",
               "coordenadas": {"lat": -32.8908, "lon": -68.8272}}

    ida_loc = _localizador("I")
    assert viajero.reenviar_confirmacion(ida_loc, ida).status_code == 202
    esperar(lambda: inicio_en_el_panel(viajero, ida_loc), 60, "la ida en el panel")
    hotel = cliente.post(f"{BFF_WEB}/reservas", headers={**viajero.sesion,
                                                         "Idempotency-Key": str(uuid4())}, json={
        "segmentos": [{"tipo": "hotel", "operador": "Hotel Aconcagua", "referencia": "HAC552",
                       "detalle": {"habitaciones": 1, "huespedes": 2},
                       "inicio": {"instante": (ida + timedelta(hours=5)).isoformat(),
                                  "precision": "instante", "zonaHoraria": mendoza["zonaHoraria"],
                                  "lugar": mendoza},
                       "fin": {"instante": (vuelta - timedelta(hours=3)).isoformat(),
                               "precision": "instante", "zonaHoraria": mendoza["zonaHoraria"],
                               "lugar": mendoza}}]})
    assert hotel.status_code == 201, hotel.text
    vuelta_loc = _localizador("V")
    assert viajero.reenviar_confirmacion(vuelta_loc, vuelta, "MDZ", "AEP").status_code == 202
    esperar(lambda: inicio_en_el_panel(viajero, vuelta_loc), 60, "la vuelta en el panel")

    viajes = viajero.panel()[0]["viajesActivos"]
    assert len(viajes) == 1, [v["titulo"] for v in viajes]
    assert len(viajes[0]["reservas"]) == 3
