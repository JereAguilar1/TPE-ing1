"""`api-gateway` y `bff-mobile` arrancan como en `docker-compose.yml` (fábricas de Uvicorn). El
recorrido con los servicios reales está en `tests/escenarios/test_gateway_contenedores.py`."""

from fastapi import FastAPI

from trotamundos.servicios.api_gateway import servicio as gateway
from trotamundos.servicios.bff_mobile import servicio as bff_mobile


def test_las_fabricas_de_uvicorn_arman_las_apps():
    assert isinstance(gateway.crear_app(), FastAPI)
    assert isinstance(bff_mobile.crear_app(), FastAPI)
