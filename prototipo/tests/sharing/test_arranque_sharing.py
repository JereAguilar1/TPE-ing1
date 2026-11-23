"""`sharing` arranca como en `docker-compose.yml` (fábrica de Uvicorn). No usa el *broker*: el
recorrido con los servicios reales está en `tests/escenarios/test_comparticion_contenedores.py`."""

from fastapi import FastAPI

from trotamundos.servicios.sharing import servicio


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)
