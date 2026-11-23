"""El asistente se degrada en `DisrupcionMasiva` (ADR-0040 §6, ADR-0020, `virtual-assistant.yaml`
1.2.0) y el modo llega desde `api-gateway` pasando por `bff-web`."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from tests.bff_web.test_bff_web import SECRETO_JWT as SECRETO_BFF
from tests.bff_web.test_bff_web import DobleDownstream
from tests.bff_web.test_bff_web import _sesion as sesion_bff
from tests.virtual_assistant.datos import OTRO, USUARIO, sesion_http
from tests.virtual_assistant.test_virtual_assistant import (  # noqa: F401 (fixture)
    RESPUESTA,
    _sesion,
    asistente,
)
from trotamundos.servicios.bff_web.clientes import ClienteDeAsistenteHttp
from trotamundos.servicios.bff_web.servicio import BffWeb

REDUCIDO = {"X-Modo-Operativo": "DisrupcionMasiva"}


def _en_modo(asistente, sid, modo: dict, usuario=USUARIO):
    cabeceras = {**sesion_http(usuario), "Idempotency-Key": str(uuid4()),
                 "Content-Type": "application/json", **modo}
    return asistente.cliente.post(f"/asistente/sesiones/{sid}/mensajes",
                                  content=json.dumps({"texto": "¿cómo viene mi viaje?"}),
                                  headers=cabeceras)


def test_en_disrupcion_masiva_responde_reducido_sin_leer_el_itinerario(asistente):
    sid = _sesion(asistente)
    turnos = len(asistente.cliente.get(f"/asistente/sesiones/{sid}",
                                       headers=sesion_http()).json()["turnos"])
    asistente.itinerario.disponible = False  # si lo consultara, la respuesta sería otra
    respuesta = _en_modo(asistente, sid, REDUCIDO)
    assert respuesta.status_code == 200, respuesta.text
    asistente.contratos.validar(RESPUESTA, respuesta.json())
    assert "modo reducido" in respuesta.json()["mensajes"][0]
    assert len(asistente.cliente.get(f"/asistente/sesiones/{sid}",
                                     headers=sesion_http()).json()["turnos"]) == turnos
    assert _en_modo(asistente, sid, REDUCIDO, usuario=OTRO).status_code == 404  # sesión ajena

    asistente.itinerario.disponible = True
    normal = _en_modo(asistente, sid, {"X-Modo-Operativo": "PicoElevado"})
    assert "modo reducido" not in normal.json()["mensajes"][0]


def test_bff_web_reenvia_el_modo_y_el_plazo_al_asistente(observacion, contratos):
    pedidos: list[httpx.Request] = []

    def asistente_http(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(200, json={"intencion": "ayuda", "mensajes": ["hola"]})

    doble = DobleDownstream(observacion)
    asistente_cliente = ClienteDeAsistenteHttp(
        "http://asistente", cliente=httpx.Client(transport=httpx.MockTransport(asistente_http)))
    bff = BffWeb(contratos=contratos, lector=doble, escritor=doble, asistente=asistente_cliente,
                 secreto_jwt=SECRETO_BFF)
    respuesta = TestClient(bff.app()).post(
        f"/asistente/sesiones/{uuid4()}/mensajes", json={"texto": "hola"},
        headers={**sesion_bff(), "Idempotency-Key": str(uuid4()), **REDUCIDO,
                 "X-Deadline-Ms": "1500"})
    assert respuesta.status_code == 200, respuesta.text
    (pedido,) = pedidos
    assert pedido.headers["x-modo-operativo"] == "DisrupcionMasiva"
    assert 0 < int(pedido.headers["x-deadline-ms"]) <= 1500
