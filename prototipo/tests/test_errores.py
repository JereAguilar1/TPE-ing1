"""Toda respuesta de error cumple el esquema `Problema` de `contratos/openapi/comun.yaml`.

Incluye los errores que genera el propio framework (ruta inexistente, método no permitido), que
de otro modo saldrían con un formato fuera del contrato.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trotamundos.comun.contratos import contratos_por_omision
from trotamundos.comun.errores import Problema, TIPO_MEDIO_PROBLEMA, instalar_manejadores, no_encontrado

PROBLEMA = "openapi/comun.yaml#/components/schemas/Problema"


@pytest.fixture(scope="module")
def cliente() -> TestClient:
    app = FastAPI()
    instalar_manejadores(app)

    @app.get("/limitado")
    def limitado():
        raise Problema(429, "Demasiadas peticiones", cabeceras={"Retry-After": "3"})

    @app.get("/ajeno")
    def ajeno():
        raise no_encontrado()

    @app.get("/numero/{n}")
    def numero(n: int):
        return {"n": n}

    return TestClient(app)


@pytest.mark.parametrize(
    ("metodo", "ruta", "estado"),
    [
        ("get", "/limitado", 429),
        ("get", "/ajeno", 404),
        ("get", "/numero/no-es-numero", 400),  # el contrato usa 400, no el 422 de FastAPI
        ("get", "/ruta-inexistente", 404),
        ("post", "/numero/1", 405),
    ],
)
def test_los_errores_cumplen_el_contrato(cliente, metodo, ruta, estado):
    respuesta = getattr(cliente, metodo)(ruta, headers={"traceparent": "00-abc-def-01"})

    assert respuesta.status_code == estado
    assert respuesta.headers["content-type"] == TIPO_MEDIO_PROBLEMA
    contratos_por_omision().validar(PROBLEMA, respuesta.json())
    assert respuesta.json()["correlationId"] == "00-abc-def-01"


def test_el_429_lleva_retry_after(cliente):
    # Contrato: DemasiadasPeticiones exige la cabecera Retry-After (ADR-0020).
    assert cliente.get("/limitado").headers["retry-after"] == "3"


def test_el_404_por_falta_de_acceso_es_identico_al_de_inexistente(cliente):
    # ADR-0028: no revelar si el recurso existe.
    ajeno = cliente.get("/ajeno").json()
    inexistente = cliente.get("/ruta-inexistente").json()
    assert ajeno == inexistente


def test_el_405_conserva_la_cabecera_allow(cliente):
    assert cliente.post("/numero/1").headers["allow"] == "GET"
