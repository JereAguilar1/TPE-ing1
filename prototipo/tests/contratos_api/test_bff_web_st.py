"""Pruebas de contrato de `bff-web` y `bff-mobile` con Schemathesis (paso 17), con los servicios de
atrás en memoria."""

import pytest
import schemathesis

from tests.bff_web.test_bff_web import SECRETO_JWT, DobleDownstream, _sesion
from tests.contratos_api.comun import AJUSTES, cargar, verificar
from trotamundos.servicios.bff_mobile.servicio import BffMobile
from trotamundos.servicios.bff_web.servicio import BffWeb


@pytest.fixture
def esquema_bff_web(observacion, contratos):
    doble = DobleDownstream(observacion)
    return cargar("openapi/bff-web.yaml", BffWeb(
        contratos=contratos, lector=doble, escritor=doble, asistente=doble,
        secreto_jwt=SECRETO_JWT).app())


@pytest.fixture
def esquema_bff_mobile(observacion, contratos):
    doble = DobleDownstream(observacion)
    return cargar("openapi/bff-mobile.yaml", BffMobile(
        contratos=contratos, lector=doble, escritor=doble, secreto_jwt=SECRETO_JWT).app())


@schemathesis.from_pytest_fixture("esquema_bff_web").parametrize()
@AJUSTES
def test_bff_web_cumple_su_contrato(case, contratos):
    verificar(case, contratos, _sesion())


@schemathesis.from_pytest_fixture("esquema_bff_mobile").parametrize()
@AJUSTES
def test_bff_mobile_cumple_su_contrato(case, contratos):
    verificar(case, contratos, _sesion())
