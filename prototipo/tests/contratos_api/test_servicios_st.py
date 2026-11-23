"""Pruebas de contrato con Schemathesis (paso 17) de los servicios con base propia, contra
PostgreSQL; sin él, se saltean.

Cada servicio se arma como en sus propias pruebas y se le mandan los pedidos que Schemathesis
genera a partir de su contrato, con la sesión del viajero (o `X-Usuario-Id`, en las operaciones
internas de `itinerary`).
"""

from __future__ import annotations

import dataclasses
from uuid import UUID

import pytest
import schemathesis

from tests.contratos_api.comun import AJUSTES, cargar, verificar
from tests.identity_access.test_api_identity_access import _armar, _iniciar_sesion
from tests.mail_ingest.test_mail_ingest import _sesion as sesion_mail
from tests.preferences.test_preferences import SECRETO as SECRETO_PREFERENCES
from tests.preferences.test_preferences import sesion as sesion_preferences
from tests.sharing.test_sharing import DUENO, SECRETO_JWT as SECRETO_SHARING, Viajes, token
from tests.bff_web.test_bff_web import DobleDownstream
from tests.support_liaison.test_support_liaison import _sesion as sesion_soporte
from tests.virtual_assistant.datos import sesion_http as sesion_asistente
from trotamundos.comun.config import Configuracion
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.preferences.servicio import Preferences
from trotamundos.servicios.provider_sync.servicio import ProviderSync
from trotamundos.servicios.sharing.servicio import Sharing

USUARIO_ITINERARY = UUID("00000000-0000-4000-8000-0000000000e9")


def _configuracion(dsn):
    return dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                               intervalo_tareas_s=0)


@pytest.fixture
def app_preferences(dsn, esquema, contratos):
    servicio = Preferences(_configuracion(dsn), esquema=esquema, contratos=contratos,
                           secreto_jwt=SECRETO_PREFERENCES)
    servicio.crear_esquema()
    return cargar("openapi/preferences.yaml", servicio.app())


@pytest.fixture
def app_itinerary(dsn, esquema, contratos):
    servicio = Itinerary(_configuracion(dsn), esquema=esquema, contratos=contratos)
    servicio.crear_esquema()
    return cargar("openapi/itinerary.yaml", servicio.app())


@pytest.fixture
def app_soporte(soporte):
    return cargar("openapi/support-liaison.yaml", soporte.app())


@pytest.fixture
def app_asistente(asistente):
    return cargar("openapi/virtual-assistant.yaml", asistente.app())


@pytest.fixture
def app_filtros(mail):
    return cargar("openapi/mail-ingest-filtros.yaml", mail.app())


@pytest.fixture
def app_webhooks_correo(mail):
    return cargar("openapi/mail-ingest-webhooks.yaml", mail.app())


@pytest.fixture
def app_webhooks_proveedor(dsn, esquema, contratos):
    servicio = ProviderSync(_configuracion(dsn), esquema=esquema, contratos=contratos,
                            secreto_webhook="secreto-de-prueba")
    servicio.crear_esquema()
    return cargar("openapi/provider-sync-webhooks.yaml", servicio.app())


class _Deniega:
    def vale(self, sujeto, comparticion_id):
        return None


@pytest.fixture
def app_sharing(dsn, esquema, contratos, observacion):
    servicio = Sharing(_configuracion(dsn), esquema=esquema, contratos=contratos,
                       lector=Viajes(DobleDownstream(observacion).viaje), autorizador=_Deniega(),
                       secreto_jwt=SECRETO_SHARING)
    servicio.crear_esquema()
    return cargar("openapi/sharing.yaml", servicio.app())


@pytest.fixture
def identidad(dsn, esquema, contratos):
    cliente, servicio, _ = _armar(dsn, esquema, contratos)
    token, _ = _iniciar_sesion(cliente)
    return cargar("openapi/identity-access.yaml", cliente.app), {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_identidad(identidad):
    return identidad[0]


@schemathesis.from_pytest_fixture("app_preferences").parametrize()
@AJUSTES
def test_preferences_cumple_su_contrato(case, contratos):
    verificar(case, contratos, sesion_preferences())


@schemathesis.from_pytest_fixture("app_itinerary").parametrize()
@AJUSTES
def test_itinerary_cumple_su_contrato(case, contratos):
    verificar(case, contratos, {"X-Usuario-Id": str(USUARIO_ITINERARY)})


@schemathesis.from_pytest_fixture("app_soporte").parametrize()
@AJUSTES
def test_support_liaison_cumple_su_contrato(case, contratos):
    verificar(case, contratos, sesion_soporte())


@schemathesis.from_pytest_fixture("app_asistente").parametrize()
@AJUSTES
def test_virtual_assistant_cumple_su_contrato(case, contratos):
    verificar(case, contratos, sesion_asistente())


@schemathesis.from_pytest_fixture("app_filtros").parametrize()
@AJUSTES
def test_filtros_de_mail_ingest_cumplen_su_contrato(case, contratos):
    verificar(case, contratos, sesion_mail())


@schemathesis.from_pytest_fixture("app_webhooks_correo").parametrize()
@AJUSTES
def test_webhooks_de_mail_ingest_cumplen_su_contrato(case, contratos):
    verificar(case, contratos)


@schemathesis.from_pytest_fixture("app_webhooks_proveedor").parametrize()
@AJUSTES
def test_webhooks_de_provider_sync_cumplen_su_contrato(case, contratos):
    verificar(case, contratos)


@schemathesis.from_pytest_fixture("app_sharing").parametrize()
@AJUSTES
def test_sharing_cumple_su_contrato(case, contratos):
    verificar(case, contratos, token(str(DUENO)))


# El mTLS de las operaciones internas se simula con `X-Servicio-Cliente` (paso 7).
CLIENTE_INTERNO = {"/buzones/{id}/token-efimero": "mail-ingest", "/autorizaciones/evaluar": "bff-web"}


@schemathesis.from_pytest_fixture("app_identidad").parametrize()
@AJUSTES
def test_identity_access_cumple_su_contrato(case, contratos, identidad):
    cabeceras = dict(identidad[1])
    if case.path in CLIENTE_INTERNO:
        cabeceras["X-Servicio-Cliente"] = CLIENTE_INTERNO[case.path]
    verificar(case, contratos, cabeceras)
