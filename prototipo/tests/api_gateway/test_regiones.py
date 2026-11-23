"""Detección de la caída de una región y conmutación en `api-gateway` (paso 16; ADR-0002, ADR-0018,
QA-05), con los `bff-web` regionales simulados por `httpx.MockTransport`."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from trotamundos.servicios.api_gateway import regiones
from trotamundos.servicios.api_gateway.servicio import ApiGateway

SECRETO = "secreto-jwt-de-prueba-de-32-bytes!"
USUARIO = UUID("00000000-0000-4000-8000-0000000000d1")
URLS = {"bff-web": "http://bff-web-am", "bff-mobile": "http://bff-mobile",
        "identity-access": "http://identity"}


def sesion(region: str | None = "AM", usuario: UUID = USUARIO) -> dict[str, str]:
    datos = {"sub": str(usuario), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    if region:
        datos["region_primaria"] = region
    return {"Authorization": f"Bearer {jwt.encode(datos, SECRETO, algorithm='HS256')}"}


# --- salud y región de respaldo ---------------------------------------------------------------

def test_una_region_cae_recien_con_tres_fallos_seguidos():
    salud = regiones.SaludDeRegiones(["AM", "EU"])
    for ahora, sana in [(0, False), (2, False), (4, True), (6, False), (8, False)]:
        salud.registrar("AM", sana, ahora)
    assert salud.sana("AM")  # el acierto del segundo 4 reinició la cuenta

    salud.registrar("AM", False, 10)
    assert not salud.sana("AM") and salud.caidas == {"AM": 10}
    salud.registrar("AM", True, 12)  # sin vuelta automática (ADR-0018 §4)
    assert not salud.sana("AM") and salud.sana("EU")


def test_la_deteccion_entra_en_los_30_segundos_de_qa05():
    """Peor caso: la región cae justo después de una ronda sana y cada consulta agota su espera."""
    peor_caso_s = regiones.FALLOS_PARA_CAIDA * (regiones.INTERVALO_S + regiones.ESPERA_S)
    assert peor_caso_s <= 30


def test_la_region_de_respaldo_es_determinista_y_nunca_la_primaria():
    usuarios = [uuid4() for _ in range(200)]
    respaldos = [regiones.region_de_respaldo(u, "AM", ["AM", "EU", "AP"]) for u in usuarios]

    assert respaldos == [regiones.region_de_respaldo(u, "AM", ["AP", "EU", "AM"]) for u in usuarios]
    assert set(respaldos) == {"EU", "AP"}  # el hash reparte entre las otras dos
    assert regiones.region_de_respaldo(USUARIO, "AM", ["AM", "EU"]) == "EU"


def test_sin_ninguna_region_sana_no_hay_destino():
    salud = regiones.SaludDeRegiones(["AM", "EU"], fallos_para_caida=1)
    salud.registrar("AM", False, 0)
    assert regiones.region_para(USUARIO, "AM", salud, "AM") == "EU"
    salud.registrar("EU", False, 0)
    assert regiones.region_para(USUARIO, "AM", salud, "AM") is None


# --- conmutación en el gateway ----------------------------------------------------------------

class Regiones:
    """Los bff-web de cada región; los de `caidas` no responden."""

    def __init__(self):
        self.caidas: set[str] = set()
        self.atendidos: list[str] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        if pedido.url.host in self.caidas:
            raise httpx.ConnectError("sin respuesta", request=pedido)
        if pedido.url.path != "/tipos-de-segmento":
            self.atendidos.append(pedido.url.host)
        return httpx.Response(200, json={})


@pytest.fixture
def armado(contratos):
    atras = Regiones()
    gateway = ApiGateway(contratos=contratos, secreto_jwt=SECRETO, urls=URLS,
                         transporte=httpx.MockTransport(atras), region="AM",
                         regionales={"EU": "http://bff-web-eu"})
    with TestClient(gateway.app()) as cliente:
        yield cliente, atras, gateway


def _rondas(gateway: ApiGateway, atras: Regiones, cuantas: int) -> None:
    async def correr():
        async with httpx.AsyncClient(transport=httpx.MockTransport(atras)) as http:
            for _ in range(cuantas):
                await gateway.comprobar_regiones(http)
    asyncio.run(correr())


def test_cada_usuario_va_al_bff_web_de_su_region_primaria(armado):
    cliente, atras, _ = armado

    assert cliente.get("/panel", headers=sesion("AM")).status_code == 200
    assert cliente.get("/panel", headers=sesion("EU")).status_code == 200
    assert cliente.get("/panel", headers=sesion(None)).status_code == 200  # sin región: la local
    assert atras.atendidos == ["bff-web-am", "bff-web-eu", "bff-web-am"]


def test_si_cae_la_region_primaria_el_trafico_va_a_la_de_respaldo(armado):
    cliente, atras, gateway = armado
    atras.caidas.add("bff-web-am")

    # Antes de declararla caída, el pedido falla (es el tiempo de detección de QA-05).
    assert cliente.get("/panel", headers=sesion("AM")).status_code == 503
    _rondas(gateway, atras, regiones.FALLOS_PARA_CAIDA)

    assert "AM" in gateway.salud.caidas
    assert cliente.get("/panel", headers=sesion("AM")).status_code == 200
    assert cliente.post("/reservas", json={}, headers={**sesion("AM"),
                                                       "Idempotency-Key": str(uuid4())}
                        ).status_code == 200
    assert atras.atendidos[-2:] == ["bff-web-eu", "bff-web-eu"]


def test_sin_regiones_configuradas_no_se_mira_la_region_del_token(contratos):
    atras = Regiones()
    gateway = ApiGateway(contratos=contratos, secreto_jwt=SECRETO, urls=URLS, region="AM",
                         transporte=httpx.MockTransport(atras), regionales={})
    with TestClient(gateway.app()) as cliente:
        assert cliente.get("/panel", headers=sesion("EU")).status_code == 200
    assert atras.atendidos == ["bff-web-am"]
