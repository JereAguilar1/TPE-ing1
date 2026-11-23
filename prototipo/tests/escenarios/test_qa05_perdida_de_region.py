"""QA-05 contra los contenedores: se cae la región AM (paso 16; ADR-0002, ADR-0018 «Confirmación»).

Un viajero de AM confirma comandos manuales por `api-gateway` y enseguida la región AM se cae de
golpe (`docker compose kill` de su `itinerary` y su `bff-web`: falla por omisión). Se mide:

- **redirección ≤ 60 s:** desde la caída hasta que el *gateway* lo atiende en EU, que incluye la
  detección (≤ 30 s, probada con reloj falso en `tests/api_gateway/test_regiones.py`);
- **pérdida de datos confirmados = 0:** en EU están, con los mismos ids, la reserva confirmada y la
  baja confirmada, sin duplicados, y `versionUsuario` no retrocede;
- **≤ 1,5 min de presupuesto:** el tiempo sin servicio del viajero es el de la redirección;
- EU asume la escritura del usuario (ADR-0018 §4).

Al terminar, vuelve a levantar AM y reinicia el *gateway* (la vuelta de una región no es
automática). Sin los contenedores se saltea; en la integración continua falla.
"""

from __future__ import annotations

import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import API_GATEWAY, Viajero, ahora, esperar, exigir_contenedores

PROTOTIPO = Path(__file__).resolve().parents[2]
REGION_AM = ["itinerary-escritura", "itinerary-lectura", "bff-web"]
REDIRECCION_S = 60
PRESUPUESTO_S = 90
APP_WEB = "http://localhost:18111"


def _compose(*argumentos: str) -> None:
    subprocess.run(["docker", "compose", *argumentos], cwd=PROTOTIPO, check=True,
                   capture_output=True, timeout=240)


@pytest.fixture
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente
    # La región AM vuelve y el gateway arranca de nuevo con las dos regiones sanas.
    _compose("up", "-d", "--wait", *REGION_AM)
    _compose("restart", "api-gateway")
    _compose("up", "-d", "--wait", "api-gateway")


def _hotel(referencia: str, dias: int) -> dict[str, Any]:
    entrada = ahora().replace(microsecond=0, second=0, minute=0) + timedelta(days=dias)
    lugar = {"nombre": "Hotel Bristol", "pais": "FR", "zonaHoraria": "Europe/Paris",
             "coordenadas": {"lat": 48.8718, "lon": 2.3148}}
    return {"segmentos": [{
        "tipo": "hotel", "operador": "Hotel Bristol", "referencia": referencia,
        "detalle": {"habitaciones": 1, "huespedes": 2},
        "inicio": {"instante": entrada.isoformat(), "precision": "instante",
                   "zonaHoraria": "Europe/Paris", "lugar": lugar},
        "fin": {"instante": (entrada + timedelta(days=3)).isoformat(), "precision": "instante",
                "zonaHoraria": "Europe/Paris", "lugar": lugar}}]}


def _reservas(panel: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for v in panel["viajesActivos"] for r in v["reservas"]] + panel["porConfirmar"]


def test_qa05_se_cae_la_region_am_y_no_se_pierde_nada_confirmado(cliente):
    viajero = Viajero(cliente).iniciar_sesion()

    def alta(referencia: str, dias: int) -> dict[str, Any]:
        respuesta = cliente.post(f"{API_GATEWAY}/reservas", json=_hotel(referencia, dias),
                                 headers={**viajero.sesion, "Idempotency-Key": str(uuid4())})
        assert respuesta.status_code == 201, respuesta.text
        return respuesta.json()

    queda = alta("PAR101", 20)
    baja = alta("PAR202", 40)
    respuesta = cliente.delete(f"{API_GATEWAY}/reservas/{baja['reserva']['id']}",
                               headers=viajero.sesion)
    assert respuesta.status_code == 204, respuesta.text
    version_confirmada = int(respuesta.headers["X-Version-Usuario"])

    # La región AM se cae de golpe, sin tiempo para nada más.
    _compose("kill", *REGION_AM)
    caida = time.monotonic()

    def panel_desde_eu():
        r = cliente.get(f"{API_GATEWAY}/panel", headers=viajero.sesion)
        if r.status_code == 200:
            return r.json()
        time.sleep(1)  # una consulta por segundo: el límite es de 60 por minuto (ADR-0020)
        return None

    panel = esperar(panel_desde_eu, REDIRECCION_S, "el gateway redirige al viajero a EU")
    redireccion_s = time.monotonic() - caida
    # La página también: nginx la manda por el gateway.
    pagina = cliente.get(f"{APP_WEB}/api/bff/panel", headers=viajero.sesion)
    assert pagina.status_code == 200 and pagina.json() == panel
    print(f"\nQA-05: tráfico redirigido a EU en {redireccion_s:.1f} s")
    assert redireccion_s <= REDIRECCION_S
    assert redireccion_s <= PRESUPUESTO_S

    # Pérdida de datos confirmados = 0: lo confirmado está, igual, una sola vez.
    reservas = _reservas(panel)
    assert [r["id"] for r in reservas] == [queda["reserva"]["id"]]
    assert reservas[0]["segmentos"] == queda["reserva"]["segmentos"]
    assert panel["versionUsuario"] >= version_confirmada

    # EU asumió la escritura del usuario.
    nueva = alta("PAR303", 30)
    panel = esperar(panel_desde_eu, 10, "el panel de EU")
    assert {r["id"] for r in _reservas(panel)} == {queda["reserva"]["id"], nueva["reserva"]["id"]}
