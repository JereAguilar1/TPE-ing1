"""Escenario del paso 13 contra los contenedores (QA-12, RF-11, RF-13): todo por `api-gateway`.

El viajero comparte su viaje con un designado. El designado, con su propia cuenta, lo ve: `sharing`
pide el vale a `identity-access`, que le pregunta los atributos a `sharing` (ADR-0028). Un tercero
recibe el mismo `404` que una compartición inexistente, y después de revocarla, el designado
también. El viajero previsualiza el resumen para redes y lo publica.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import jwt
import pytest

from trotamundos.comun.config import _variable

from tests.escenarios.contenedores import (
    API_GATEWAY,
    Viajero,
    ahora,
    esperar,
    exigir_contenedores,
)

TIPO = {"Content-Type": "application/vnd.trotamundos.v1+json"}


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def _viaje_de(viajero: Viajero, localizador: str) -> str | None:
    datos, _ = viajero.panel()
    for viaje in datos["viajesActivos"]:
        if any(i["codigo"] == localizador for r in viaje["reservas"] for i in r["identificadores"]):
            return viaje["id"]
    return None


def test_compartir_ver_revocar_y_publicar(cliente):
    dueno = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    designado, tercero = Viajero(cliente).iniciar_sesion(), Viajero(cliente).iniciar_sesion()
    localizador = f"S{uuid4().hex[:5].upper()}"
    salida = (ahora() + timedelta(days=15)).replace(microsecond=0)
    assert dueno.reenviar_confirmacion(localizador, salida).status_code == 202
    viaje_id = esperar(lambda: _viaje_de(dueno, localizador), 90, "el viaje aparece en el panel")

    creada = cliente.post(f"{API_GATEWAY}/viajes/{viaje_id}/comparticiones", headers={
        **dueno.sesion, **TIPO, "Idempotency-Key": str(uuid4())},
        json={"designados": [designado.correo]})
    assert creada.status_code == 201, creada.text
    cid = creada.json()["id"]

    visto = cliente.get(f"{API_GATEWAY}/comparticiones/{cid}", headers=designado.sesion)
    assert visto.status_code == 200, visto.text
    assert visto.json()["id"] == viaje_id and visto.headers["cache-control"] == "private, no-store"
    ajeno = cliente.get(f"{API_GATEWAY}/comparticiones/{cid}", headers=tercero.sesion)
    inexistente = cliente.get(f"{API_GATEWAY}/comparticiones/{uuid4()}", headers=designado.sesion)
    assert ajeno.status_code == inexistente.status_code == 404
    sin_traza = [{k: v for k, v in r.json().items() if k != "correlationId"}
                 for r in (ajeno, inexistente)]
    assert sin_traza[0] == sin_traza[1]  # idénticos salvo la traza de cada pedido

    # El envío OTP es simulado y su código queda en memoria de identity-access. Acá se firma
    # una sesión con los mismos reclamos; las pruebas de identity-access verifican el desafío.
    invitado = {"Authorization": "Bearer " + jwt.encode({
        "sub": f"invitado:{designado.correo}", "email": designado.correo,
        "email_verificado": True, "alcances": [f"lectura:comparticion:{cid}"],
        "exp": ahora() + timedelta(minutes=10)}, _variable("TROTAMUNDOS_JWT_SECRETO"),
        algorithm="HS256")}
    visto_invitado = cliente.get(f"{API_GATEWAY}/comparticiones/{cid}", headers=invitado)
    assert visto_invitado.status_code == 200, visto_invitado.text
    assert visto_invitado.json()["id"] == viaje_id
    assert cliente.get(f"{API_GATEWAY}/panel", headers=invitado).status_code == 401
    assert cliente.get(f"{API_GATEWAY}/comparticiones/{uuid4()}", headers=invitado).status_code == 404

    assert cliente.delete(f"{API_GATEWAY}/viajes/{viaje_id}/comparticiones/{cid}",
                          headers=dueno.sesion).status_code == 204
    assert cliente.get(f"{API_GATEWAY}/comparticiones/{cid}",
                       headers=designado.sesion).status_code == 404
    assert cliente.get(f"{API_GATEWAY}/comparticiones/{cid}", headers=invitado).status_code == 404

    resumen = cliente.get(f"{API_GATEWAY}/viajes/{viaje_id}/publicaciones/previsualizacion",
                          headers=dueno.sesion)
    assert resumen.status_code == 200 and localizador not in resumen.text
    publicada = cliente.post(f"{API_GATEWAY}/viajes/{viaje_id}/publicaciones", headers={
        **dueno.sesion, **TIPO, "Idempotency-Key": str(uuid4())},
        json={"red": "instagram", "resumen": resumen.json(), "confirmado": True})
    assert publicada.status_code == 202, publicada.text
