"""`bff-mobile` (`bff-mobile.yaml`, ADR-0005, ADR-0019) y el plazo propagado de `comun.bff`
(ADR-0020), con los servicios de atrás en memoria."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.bff_web.test_bff_web import SECRETO_JWT, TIPO, USUARIO, DobleDownstream, _sesion
from trotamundos.comun.bff import LectorDeItinerarioHttp
from trotamundos.servicios.bff_mobile import resumen
from trotamundos.servicios.bff_mobile.servicio import BffMobile

PANEL_RESUMEN = "openapi/comun.yaml#/components/schemas/PanelResumen"
ANTES = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def doble(observacion):
    return DobleDownstream(observacion)


@pytest.fixture
def cliente(doble, contratos):
    bff = BffMobile(contratos=contratos, lector=doble, escritor=doble, secreto_jwt=SECRETO_JWT,
                    reloj=lambda: ANTES)
    return TestClient(bff.app())


def test_panel_resumen_compacto_con_etag(cliente, doble, contratos):
    respuesta = cliente.get("/panel/resumen", headers={**_sesion(), "X-Min-Version": "1"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"].startswith(TIPO)
    assert respuesta.headers["cache-control"] == "private, no-cache"
    cuerpo = respuesta.json()
    contratos.validar(PANEL_RESUMEN, cuerpo)
    (viaje,) = cuerpo["viajesActivos"]
    assert viaje["cantidadReservas"] == 1
    assert viaje["proximoSegmento"]["id"] == doble.reserva["segmentos"][0]["id"]
    assert doble.llamadas[-1][2]["min_version"] == 1

    etag = respuesta.headers["etag"]
    assert cliente.get("/panel/resumen", headers={**_sesion(), "If-None-Match": etag}
                       ).status_code == 304
    assert cliente.get("/panel/resumen").status_code == 401


def test_expone_las_operaciones_compartidas_y_no_el_asistente(cliente):
    assert cliente.get("/panel", headers=_sesion()).status_code == 200
    assert cliente.get("/viajes", headers=_sesion()).status_code == 200
    assert cliente.get("/tipos-de-segmento").status_code == 200
    assert cliente.post("/asistente/sesiones", headers=_sesion()).status_code in (404, 405)


def test_el_resumen_no_pasa_de_15_kb_y_deja_afuera_los_viajes_mas_lejanos(doble):
    viajes = []
    for dia in range(60):
        viaje = copy.deepcopy(doble.viaje)
        viaje["id"] = str(uuid4())
        viaje["desde"] = (datetime(2027, 1, 1, tzinfo=timezone.utc)
                          + timedelta(days=dia)).isoformat().replace("+00:00", "Z")
        viajes.append(viaje)
    panel = {"viajesActivos": list(reversed(viajes)), "porConfirmar": [doble.reserva],
             "conflictosAbiertos": [], "versionUsuario": 7}
    compacto = resumen.del_panel(panel, ANTES)
    assert resumen.tamano(compacto) <= resumen.LIMITE_BYTES
    assert 0 < len(compacto["viajesActivos"]) < 60
    assert compacto["viajesActivos"][0]["desde"] == viajes[0]["desde"]  # el más cercano queda
    assert compacto["cantidadPorConfirmar"] == 1


def test_el_resumen_con_cinco_viajes_entra_en_15_kb(doble):
    """ADR-0019, Confirmación: 5 viajes activos pesan ≤ 15 KB (sin comprimir, más estricto)."""
    viajes = [dict(copy.deepcopy(doble.viaje), id=str(uuid4())) for _ in range(5)]
    panel = {"viajesActivos": viajes, "porConfirmar": [], "conflictosAbiertos": [],
             "versionUsuario": 1}
    compacto = resumen.del_panel(panel, ANTES)
    assert len(compacto["viajesActivos"]) == 5
    assert resumen.tamano(compacto) <= resumen.LIMITE_BYTES


# --- plazo propagado (ADR-0020) ------------------------------------------------------------------

class HttpDeItinerario:
    def __init__(self, panel):
        self.panel = panel
        self.pedidos: list[dict] = []

    def get(self, url, headers, params, timeout):
        self.pedidos.append({"url": url, "headers": headers, "timeout": timeout})
        return httpx.Response(200, json=self.panel)


@pytest.fixture
def con_http(doble, contratos):
    panel = {"viajesActivos": [doble.viaje], "porConfirmar": [], "conflictosAbiertos": [],
             "versionUsuario": 1}
    http = HttpDeItinerario(panel)
    bff = BffMobile(contratos=contratos, lector=LectorDeItinerarioHttp("http://lectura", cliente=http),
                    escritor=doble, secreto_jwt=SECRETO_JWT, reloj=lambda: ANTES)
    return TestClient(bff.app()), http


def test_el_plazo_acota_la_llamada_y_se_propaga(con_http):
    cliente, http = con_http
    assert cliente.get("/panel/resumen", headers={**_sesion(), "X-Deadline-Ms": "800"}
                       ).status_code == 200
    (pedido,) = http.pedidos
    assert pedido["timeout"] <= 0.8
    assert 0 < int(pedido["headers"]["X-Deadline-Ms"]) <= 800
    assert pedido["headers"]["X-Usuario-Id"] == str(USUARIO)


def test_sin_plazo_suficiente_no_llama_y_responde_503(con_http):
    cliente, http = con_http
    respuesta = cliente.get("/panel/resumen", headers={**_sesion(), "X-Deadline-Ms": "10"})
    assert respuesta.status_code == 503 and http.pedidos == []
    assert cliente.get("/panel/resumen", headers=_sesion()).status_code == 200
    assert http.pedidos[-1]["timeout"] == 5.0 and "X-Deadline-Ms" not in http.pedidos[-1]["headers"]
