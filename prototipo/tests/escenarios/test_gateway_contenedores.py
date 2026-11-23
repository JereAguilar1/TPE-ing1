"""Escenario del paso 11 completo contra los contenedores: todo entra por `api-gateway`.

El viajero inicia sesión por el *gateway* (operación pública), reenvía una confirmación y ve el
viaje en el panel de `bff-web` y en el resumen compacto de `bff-mobile` (`X-Tipo-Cliente: movil`).
Guarda sus preferencias y conversa con el asistente por el mismo camino. Cada respuesta trae `traceparent` y el modo
operativo, y cada servicio recibe `X-Deadline-Ms`. Al pasar las 20 peticiones de la ráfaga, `429`
con `Retry-After` entre 2 y 8 s (ADR-0020).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    API_GATEWAY,
    Viajero,
    ahora,
    esperar,
    exigir_contenedores,
)

TIPO = "application/vnd.trotamundos.v1+json"
RESUMEN = "openapi/comun.yaml#/components/schemas/PanelResumen"


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def test_el_viajero_entra_por_el_gateway(cliente, contratos):
    viajero = Viajero(cliente)
    respuesta = cliente.post(f"{API_GATEWAY}/sesiones", json={
        "codigo": f"oidc:{viajero.correo}:AM", "verificadorPkce": "v" * 43,
        "uriRedireccion": "https://trotamundos.app/callback"})
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.headers["traceparent"].startswith("00-")
    viajero.token = respuesta.json()["tokenAcceso"]
    viajero.conectar_reenvio()

    localizador = f"G{uuid4().hex[:5].upper()}"
    salida = (ahora() + timedelta(days=12)).replace(microsecond=0)
    assert viajero.reenviar_confirmacion(localizador, salida).status_code == 202

    movil = {**viajero.sesion, "X-Tipo-Cliente": "movil", "Accept": TIPO}

    def resumen_con_viaje():
        r = cliente.get(f"{API_GATEWAY}/panel/resumen", headers=movil)
        return r if r.status_code == 200 and r.json()["viajesActivos"] else None

    resumen = esperar(resumen_con_viaje, 90, "el viaje aparece en el resumen móvil")
    contratos.validar(RESUMEN, resumen.json())
    assert len(resumen.content) <= 15 * 1024
    assert resumen.headers["x-modo-operativo"] == "Normal"
    assert cliente.get(f"{API_GATEWAY}/panel/resumen", headers={
        **movil, "If-None-Match": resumen.headers["etag"]}).status_code == 304

    web = cliente.get(f"{API_GATEWAY}/panel", headers=viajero.sesion)
    assert web.status_code == 200 and web.json()["viajesActivos"]
    assert cliente.get(f"{API_GATEWAY}/panel").status_code == 401
    assert cliente.get(f"{API_GATEWAY}/panel", headers={
        **viajero.sesion, "Accept": "application/vnd.trotamundos.v2+json"}).status_code == 406

    guardadas = cliente.put(f"{API_GATEWAY}/preferencias", headers={
        **viajero.sesion, "Content-Type": TIPO}, json={
        "idioma": "es-AR", "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM"})
    assert guardadas.status_code == 200, guardadas.text

    abierta = cliente.post(f"{API_GATEWAY}/asistente/sesiones", headers={
        **viajero.sesion, "Idempotency-Key": str(uuid4())})
    assert abierta.status_code == 201, abierta.text
    respuesta = cliente.post(f"{API_GATEWAY}/asistente/sesiones/{abierta.json()['id']}/mensajes",
                             headers={**viajero.sesion, "Idempotency-Key": str(uuid4())},
                             json={"texto": "¿cómo viene mi viaje?"})
    assert respuesta.status_code == 200, respuesta.text
    assert "modo reducido" not in respuesta.json()["mensajes"][0]  # en modo Normal

    estados = [cliente.get(f"{API_GATEWAY}/panel", headers=viajero.sesion).status_code
               for _ in range(25)]
    assert 429 in estados and set(estados) <= {200, 429}
    frenada = cliente.get(f"{API_GATEWAY}/panel", headers=viajero.sesion)
    assert frenada.status_code == 429 and 2 <= int(frenada.headers["retry-after"]) <= 8
