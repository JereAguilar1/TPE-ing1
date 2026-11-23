"""Lo común de las pruebas de contrato con Schemathesis (paso 17, ADR-0017, ADR-0036).

Schemathesis genera pedidos a partir de cada operación del contrato OpenAPI y verifica la
respuesta del servicio, en el mismo proceso (ASGI):

* ningún pedido, ni siquiera uno inválido, termina en un error `5xx`;
* el código de estado, el tipo de contenido, las cabeceras y el cuerpo de la respuesta son los que
  declara el contrato para esa operación.

Los ejemplos son deterministas (`derandomize`), así que la integración continua prueba siempre los
mismos. Los descriptores de tipos de segmento traen un JSON Schema adentro (`esquemaDeDetalle`),
que referencia el metaesquema 2020-12: el validador de Schemathesis 3.x lo quiere bajar de internet,
así que ese cuerpo lo valida `comun.contratos`, que lo resuelve localmente (ADR-0009).
"""

from __future__ import annotations

from typing import Any, Mapping

import schemathesis
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from trotamundos.comun.contratos import Contratos, contratos_por_omision

schemathesis.experimental.OPEN_API_3_1.enable()
# Formatos que Schemathesis 3.x no sabe generar: sin esto manda texto cualquiera («0», «»), que el
# servicio rechaza con razón, y la prueba no llega a ejercitar la operación.
schemathesis.openapi.format("uuid", st.uuids().map(str))
schemathesis.openapi.format("email", st.from_regex(r"\A[a-z]{1,10}@[a-z]{1,10}\.example\Z"))


@schemathesis.serializer("message/rfc822")
class Rfc822:
    """El cuerpo de `POST /webhooks/correo/reenvio`: el correo crudo, en bytes."""

    def as_requests(self, context: Any, value: Any) -> dict[str, Any]:
        return {"data": value if isinstance(value, bytes) else str(value).encode("utf-8")}

    def as_werkzeug(self, context: Any, value: Any) -> dict[str, Any]:
        return self.as_requests(context, value)

CHEQUEOS = (not_a_server_error, status_code_conformance, content_type_conformance,
            response_headers_conformance, response_schema_conformance)
AJUSTES = settings(max_examples=10, deadline=None, derandomize=True, database=None,
                   suppress_health_check=list(HealthCheck))
# Operaciones cuyo cuerpo trae un JSON Schema adentro: lo valida comun.contratos.
CON_METAESQUEMA = {"/tipos-de-segmento": "openapi/bff-web.yaml#/paths/~1tipos-de-segmento/get/"
                                         "responses/200/content/application~1vnd.trotamundos.v1+json/schema"}


def cargar(contrato: str, app: Any) -> Any:
    """El esquema del contrato contra la app, sin el carácter nulo en los textos generados (en las
    claves lo reemplaza `verificar`): un nulo lo rechaza `comun.contratos` con `400` en todas las
    operaciones, aunque no todas lo declaren (lo prueba `tests/test_contratos.py`)."""
    return schemathesis.from_path(str(contratos_por_omision().ruta / contrato), app=app,
                                  generation_config=schemathesis.GenerationConfig(allow_x00=False))


def verificar(case: Any, contratos: Contratos, cabeceras: Mapping[str, str] | None = None) -> Any:
    """Manda el pedido generado (con las cabeceras de sesión) y verifica la respuesta."""
    case.body = _sin_nulos(case.body)  # ver `cargar`
    case.headers = {**(case.headers or {}), **(cabeceras or {})}
    respuesta = case.call()
    # JSON es UTF-8 (RFC 8259) aunque el tipo de medio no lo diga; el cliente de Schemathesis
    # supone ISO-8859-1 para `application/vnd.trotamundos.v1+json` sin `charset`.
    respuesta.encoding = "utf-8"
    referencia = CON_METAESQUEMA.get(case.path)
    if referencia is None:
        case.validate_response(respuesta, checks=CHEQUEOS)
        return respuesta
    case.validate_response(respuesta, checks=tuple(c for c in CHEQUEOS
                                                   if c is not response_schema_conformance))
    if respuesta.status_code == 200:
        contratos.validar(referencia, respuesta.json())
    return respuesta


def _sin_nulos(valor: Any) -> Any:
    if isinstance(valor, str):
        return valor.replace("\x00", "0")
    if isinstance(valor, dict):
        return {_sin_nulos(clave): _sin_nulos(contenido) for clave, contenido in valor.items()}
    if isinstance(valor, list):
        return [_sin_nulos(contenido) for contenido in valor]
    return valor
