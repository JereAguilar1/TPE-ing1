"""`api-gateway` (`api-gateway.yaml`, ADR-0005, ADR-0020, ADR-0025, ADR-0027), con los servicios de
atrás simulados por `httpx.MockTransport`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from trotamundos.servicios.api_gateway import cubeta, modos
from trotamundos.servicios.api_gateway.servicio import ApiGateway

SECRETO = "secreto-jwt-de-prueba-de-32-bytes!"
USUARIO = UUID("00000000-0000-4000-8000-0000000000d1")
URLS = {"bff-web": "http://bff-web", "bff-mobile": "http://bff-mobile",
        "identity-access": "http://identity", "support-liaison": "http://soporte",
        "preferences": "http://preferences", "mail-ingest": "http://mail"}


def sesion(usuario: UUID = USUARIO) -> dict[str, str]:
    token = jwt.encode({"sub": str(usuario), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       SECRETO, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


class Atras:
    """Los servicios de atrás: registran cada pedido y responden lo que se les indique."""

    def __init__(self):
        self.pedidos: list[httpx.Request] = []
        self.falla: Exception | None = None

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        if self.falla is not None:
            raise self.falla
        return httpx.Response(200, json={"servicio": pedido.url.host, "ruta": pedido.url.path},
                              headers={"ETag": '"abc"', "Cache-Control": "private, no-cache"})


@pytest.fixture
def armado(contratos):
    atras, reloj = Atras(), Reloj()
    gateway = ApiGateway(contratos=contratos, secreto_jwt=SECRETO, urls=URLS,
                         transporte=httpx.MockTransport(atras), reloj=reloj)
    with TestClient(gateway.app()) as cliente:
        yield cliente, atras, gateway, reloj


def test_enruta_segun_el_contrato_y_el_tipo_de_cliente(armado):
    cliente, atras, _, _ = armado
    casos = [("GET", "/panel", {}, "bff-web"), ("GET", "/panel", {"X-Tipo-Cliente": "movil"},
                                                     "bff-mobile"),
             ("GET", "/panel/resumen", {}, "bff-mobile"), ("PUT", "/preferencias", {}, "preferences"),
             ("GET", "/casos/00000000-0000-4000-8000-000000000001", {}, "soporte"),
             ("GET", "/filtros-de-correo/catalogo", {}, "mail")]
    for metodo, ruta, extra, servicio in casos:
        respuesta = cliente.request(metodo, ruta, headers={**sesion(), **extra})
        assert respuesta.status_code == 200, (ruta, respuesta.text)
        assert respuesta.json() == {"servicio": servicio, "ruta": ruta}
    assert respuesta.headers["etag"] == '"abc"'
    assert respuesta.headers["x-modo-operativo"] == "Normal"


def test_lo_que_el_contrato_no_publica_no_pasa(armado):
    cliente, atras, _, _ = armado
    assert cliente.delete(f"/interno/usuarios/{USUARIO}").status_code == 404
    assert cliente.post("/panel", headers=sesion()).status_code == 404
    assert cliente.get("/webhooks/proveedor").status_code == 404
    assert atras.pedidos == []


def test_exige_sesion_salvo_en_las_operaciones_publicas(armado):
    cliente, atras, _, _ = armado
    assert cliente.get("/panel").status_code == 401
    assert cliente.get("/panel", headers={"Authorization": "Bearer basura"}).status_code == 401
    assert cliente.post("/sesiones", json={}).status_code == 200      # iniciar sesión
    assert cliente.get("/tipos-de-segmento").status_code == 200       # catálogo público
    assert [p.url.path for p in atras.pedidos] == ["/sesiones", "/tipos-de-segmento"]


def test_propaga_plazo_traza_cuerpo_y_consulta(armado):
    cliente, atras, _, _ = armado
    traza = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    respuesta = cliente.post("/reservas?x=1", content=json.dumps({"a": 1}),
                             headers={**sesion(), "traceparent": traza, "Idempotency-Key": "k",
                                      "Content-Type": "application/vnd.trotamundos.v1+json"})
    assert respuesta.status_code == 200 and respuesta.headers["traceparent"] == traza
    (pedido,) = atras.pedidos
    assert pedido.headers["x-deadline-ms"] == "800" and pedido.headers["traceparent"] == traza
    assert pedido.headers["x-modo-operativo"] == "Normal"
    assert pedido.headers["idempotency-key"] == "k" and pedido.url.params["x"] == "1"
    assert json.loads(pedido.content) == {"a": 1}

    cliente.get("/panel", headers={**sesion(), "traceparent": "inventada"})
    creada = atras.pedidos[-1].headers["traceparent"]
    assert creada != "inventada" and creada.startswith("00-") and len(creada) == 55


def test_negocia_la_version_de_representacion(armado):
    cliente, atras, _, _ = armado
    v1 = "application/vnd.trotamundos.v1+json"
    assert cliente.get("/panel", headers={**sesion(), "Accept": v1}).status_code == 200
    assert cliente.get("/panel", headers={**sesion(), "Accept": "*/*"}).status_code == 200
    respuesta = cliente.get("/panel", headers={**sesion(),
                                               "Accept": "application/vnd.trotamundos.v2+json"})
    assert respuesta.status_code == 406
    assert respuesta.headers["content-type"].startswith("application/problem+json")


def test_cubeta_de_fichas_por_usuario_60_por_minuto_rafaga_20(armado):
    cliente, _, _, reloj = armado
    for _ in range(20):
        assert cliente.get("/panel", headers=sesion()).status_code == 200
    frenada = cliente.get("/panel", headers=sesion())
    assert frenada.status_code == 429
    assert 2 <= int(frenada.headers["retry-after"]) <= 8
    otro = UUID("00000000-0000-4000-8000-0000000000d2")
    assert cliente.get("/panel", headers=sesion(otro)).status_code == 200  # cubeta propia
    reloj.ahora += 1  # una ficha por segundo
    assert cliente.get("/panel", headers=sesion()).status_code == 200
    assert cliente.get("/panel", headers=sesion()).status_code == 429


def test_cubeta_se_recarga_hasta_su_capacidad():
    c = cubeta.CubetaDeFichas()
    assert all(c.tomar("u", 0.0) is None for _ in range(20)) and c.tomar("u", 0.0) is not None
    assert all(c.tomar("u", 3600.0) is None for _ in range(20)) and c.tomar("u", 3600.0)


def test_servicio_caido_o_lento_es_503_y_sharing_no_esta(armado):
    cliente, atras, _, _ = armado
    atras.falla = httpx.ReadTimeout("lento")
    respuesta = cliente.get("/panel", headers=sesion())
    assert respuesta.status_code == 503 and "plazo" in respuesta.json()["detail"]
    atras.falla = httpx.ConnectError("caído")
    assert cliente.get("/panel", headers=sesion()).status_code == 503
    atras.falla = None
    respuesta = cliente.get(f"/viajes/{USUARIO}/comparticiones", headers=sesion())
    assert respuesta.status_code == 503 and "sharing" in respuesta.json()["detail"]


def test_cola_acotada_responde_503(armado):
    cliente, _, gateway, _ = armado
    gateway._en_curso = 50
    respuesta = cliente.get("/panel", headers=sesion())
    assert respuesta.status_code == 503 and respuesta.headers["retry-after"] == "2"


# --- modos operativos (ADR-0020, iteración 3 §5.3) ----------------------------------------------

UMBRALES = modos.Umbrales(pico_rps=5, pico_entrada_s=6, pico_salida_rps=2, pico_salida_p95_s=0.5,
                          pico_salida_s=60, disrupcion_rps=20, disrupcion_p95_s=0.9,
                          disrupcion_entrada_s=3, disrupcion_salida_rps=10, disrupcion_salida_s=90)


def _carga(maquina, desde: float, hasta: float, rps: float, latencia: float = 0.1) -> str:
    t, paso = desde, 1 / rps
    while t < hasta:
        modo = maquina.registrar(t, latencia)
        t += paso
    return modo


def test_entra_en_pico_con_carga_sostenida_y_sale_con_histeresis():
    m = modos.MaquinaDeModos(UMBRALES)
    assert _carga(m, 0, 5, 6) == modos.NORMAL            # todavía no se sostuvo 6 s
    assert _carga(m, 5, 30, 6) == modos.PICO_ELEVADO
    assert _carga(m, 30, 80, 1) == modos.PICO_ELEVADO    # baja, pero no 60 s seguidos
    assert _carga(m, 80, 120, 1) == modos.NORMAL


def test_disrupcion_por_latencia_y_vuelta_a_pico():
    m = modos.MaquinaDeModos(UMBRALES)
    assert _carga(m, 0, 10, 1, latencia=1.2) == modos.DISRUPCION_MASIVA
    assert _carga(m, 10, 60, 1) == modos.DISRUPCION_MASIVA
    assert _carga(m, 60, 120, 1) == modos.PICO_ELEVADO


def test_en_disrupcion_el_plazo_es_1500_y_se_apagan_las_publicaciones(contratos):
    atras, reloj = Atras(), Reloj()
    gateway = ApiGateway(contratos=contratos, secreto_jwt=SECRETO, urls={**URLS, "sharing": "http://s"},
                         transporte=httpx.MockTransport(atras), reloj=reloj, umbrales=UMBRALES)
    gateway.modos.modo = modos.DISRUPCION_MASIVA
    with TestClient(gateway.app()) as cliente:
        assert cliente.get("/panel", headers=sesion()).headers["x-modo-operativo"] == (
            "DisrupcionMasiva")
        assert atras.pedidos[-1].headers["x-deadline-ms"] == "1500"
        assert atras.pedidos[-1].headers["x-modo-operativo"] == "DisrupcionMasiva"
        cliente.post(f"/asistente/sesiones/{USUARIO}/mensajes", headers=sesion(), json={})
        assert atras.pedidos[-1].url.host == "bff-web"  # el asistente se publica por bff-web
        apagada = cliente.post(f"/viajes/{USUARIO}/publicaciones", headers=sesion())
        assert apagada.status_code == 503 and apagada.headers["retry-after"] == "60"
