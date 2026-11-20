"""QA-15 contra los contenedores: un boleto de tren llega por correo y aparece en el panel.

Completa el escenario de `test_qa15_nuevo_transporte.py` con el paso 4 de la guía de extensión:
el tren entra por el mismo camino que un vuelo (`mail-ingest` → `booking-extraction` →
`itinerary` → `bff-web`), con su propio extractor como complemento y sin cambios en el servicio.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    Viajero,
    ahora,
    esperar,
    exigir_contenedores,
    inicio_en_el_panel,
    texto_utc,
)


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def test_qa15_un_boleto_de_tren_reenviado_llega_al_panel(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    localizador = ("T" + uuid4().hex.upper())[:6]
    salida = ahora().replace(microsecond=0) + timedelta(days=9)
    assert viajero.reenviar_boleto_de_tren(localizador, salida).status_code == 202
    esperar(lambda: inicio_en_el_panel(viajero, localizador) == texto_utc(salida), 60,
            "el tren en el panel")

    reserva = viajero.reservas()[localizador]
    tramo = reserva["segmentos"][0]
    assert reserva["estado"] == "Confirmada" and reserva["fuentes"] == ["correo"]
    assert (tramo["tipo"], tramo["referencia"]) == ("tren", "RF03071")
    assert tramo["detalle"] == {"numeroDeTren": "03071", "coche": "5", "asiento": "12A", "anden": "7"}
    assert tramo["inicio"]["lugar"]["nombre"] == "Madrid Atocha"
