"""Escenario RF-10 (paso 12) contra los contenedores: preferencias y avisos de punta a punta.

El viajero guarda sus preferencias en `preferences` (sin push) → `PreferenciasActualizadas` →
copia local en `notification`. Reenvía una confirmación → reserva agregada → aviso informativo.
La aerolínea avisa un cambio de horario → `itinerary` → `ReservaActualizada` → aviso crítico, que
sale de inmediato por correo (el push está deshabilitado) sin importar las horas de silencio, y
`NotificacionEmitida` sale por el *broker*.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    PREFERENCES,
    Viajero,
    ahora,
    esperar,
    esperar_seguimiento,
    exigir_contenedores,
    fila,
    notificar_cambio,
)

TIPO = {"Content-Type": "application/vnd.trotamundos.v1+json"}


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def _aviso(usuario_id: str, severidad: str):
    return fila("notification", """SELECT * FROM aviso WHERE usuario_id = %s AND severidad = %s
                ORDER BY creado_en DESC LIMIT 1""", usuario_id, severidad)


def test_preferencias_y_avisos_de_punta_a_punta(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    respuesta = cliente.put(f"{PREFERENCES}/preferencias", headers={**viajero.sesion, **TIPO},
                            json={"idioma": "es-AR", "zonaHoraria": "America/Argentina/Buenos_Aires",
                                  "region": "AM", "canales": {"push": False, "correo": True}})
    assert respuesta.status_code == 200, respuesta.text
    esperar(lambda: fila("notification", "SELECT 1 FROM preferencias_local WHERE usuario_id = %s",
                         viajero.usuario_id), 60, "notification copia las preferencias")

    localizador = f"N{uuid4().hex[:5].upper()}"
    salida = (ahora() + timedelta(days=10)).replace(microsecond=0)
    assert viajero.reenviar_confirmacion(localizador, salida).status_code == 202
    informativo = esperar(lambda: _aviso(viajero.usuario_id, "informativa"), 90,
                          "notification avisa la reserva agregada")
    assert informativo["motivo"] == "reservaAgregada" and "interno" in informativo["canales"]

    esperar_seguimiento(localizador)
    assert notificar_cambio(cliente, localizador, salida + timedelta(hours=2)).status_code == 202
    critico = esperar(lambda: _aviso(viajero.usuario_id, "critica"), 90,
                      "notification avisa el cambio de horario")
    assert critico["canales"] == ["interno", "correo"] and critico["emitido_en"] is not None
    esperar(lambda: fila("notification", """SELECT 1 FROM bandeja_salida WHERE usuario_id = %s
                         AND tipo = 'NotificacionEmitida' AND publicado_en IS NOT NULL
                         AND carga->>'notificacionId' = %s""",
                         viajero.usuario_id, str(critico["aviso_id"])),
           30, "NotificacionEmitida sale por el broker")
