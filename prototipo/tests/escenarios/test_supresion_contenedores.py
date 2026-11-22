"""Supresión de fase 1 contra los contenedores (ADR-0030, ADR-0042): el viajero suprime su cuenta y
no queda nada suyo en `itinerary`, `support-liaison` ni el asistente."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    BFF_WEB,
    IDENTITY_ACCESS,
    Viajero,
    ahora,
    esperar,
    exigir_contenedores,
    fila,
    inicio_en_el_panel,
)


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=20) as cliente:
        yield cliente


def _cuantas(esquema: str, usuario_id: str) -> int:
    tablas = {"itinerary": ("reserva", "viaje", "panel_usuario"),
              "virtual_assistant": ("sesion", "turno"), "support_liaison": ("caso",)}[esquema]
    return sum(fila(esquema, f"SELECT count(*) AS n FROM {t} WHERE usuario_id = %s", usuario_id)["n"]
               for t in tablas)


def test_suprimir_la_cuenta_borra_los_datos_en_todo_el_plano_operacional(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    localizador = ("S" + uuid4().hex.upper())[:6]
    assert viajero.reenviar_confirmacion(localizador, ahora() + timedelta(days=9)).status_code == 202
    esperar(lambda: inicio_en_el_panel(viajero, localizador), 60, "la reserva en el panel")
    medio = {"Content-Type": "application/vnd.trotamundos.v1+json"}
    sesion = cliente.post(f"{BFF_WEB}/asistente/sesiones", content="{}",
                          headers={**viajero.sesion, **medio, "Idempotency-Key": str(uuid4())})
    assert sesion.status_code == 201
    usuario = viajero.usuario_id
    assert _cuantas("itinerary", usuario) > 0 and _cuantas("virtual_assistant", usuario) > 0

    respuesta = cliente.delete(f"{IDENTITY_ACCESS}/privacidad/cuenta",
                               headers={**viajero.sesion, "Idempotency-Key": str(uuid4())})
    assert respuesta.status_code == 202

    for esquema in ("itinerary", "virtual_assistant", "support_liaison"):
        esperar(lambda e=esquema: _cuantas(e, usuario) == 0, 30, f"sin datos en {esquema}")
    assert fila("identity_access", "SELECT count(*) AS n FROM orden_de_borrado "
                                   "WHERE usuario_id = %s", usuario)["n"] == 0
