"""Fábrica de Uvicorn y consumo con Redpanda real para `event-pipeline` (paso 14)."""

from __future__ import annotations

import asyncio
import dataclasses
import time

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.event_pipeline.test_event_pipeline import (
    RESERVA_1,
    USUARIO_1,
    VIAJE_1,
    _reserva_actualizada,
    _viaje_armado,
    filas,
)
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.servicios.event_pipeline import servicio
from trotamundos.servicios.event_pipeline.servicio import EventPipeline


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)


async def _enviar(servidores: str, nombre: str, evento: Evento) -> None:
    productor = AIOKafkaProducer(bootstrap_servers=servidores)
    await productor.start()
    try:
        clave, valor, cabeceras = evento.a_kafka()
        await productor.send_and_wait(nombre, valor, key=clave, headers=cabeceras)
    finally:
        await productor.stop()


def _hasta_que(condicion, limite_s: float = 20) -> None:
    limite = time.monotonic() + limite_s
    while not condicion() and time.monotonic() < limite:
        time.sleep(0.2)
    assert condicion()


def test_con_broker_consume_eventos_y_materializa_en_esquema_analitico(
    dsn, esquema, contratos, servidores, prefijo
):
    configuracion = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker=servidores,
        prefijo_topicos=prefijo,
        intervalo_tareas_s=0,
    )
    pipeline = EventPipeline(configuracion, esquema=esquema, contratos=contratos)
    ev_reserva = _reserva_actualizada(USUARIO_1, RESERVA_1)
    ev_viaje = _viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1)

    with TestClient(pipeline.app()):
        asyncio.run(
            _enviar(
                servidores,
                topico(contratos, "ReservaActualizada", "P2", prefijo),
                ev_reserva,
            )
        )
        asyncio.run(
            _enviar(
                servidores,
                topico(contratos, "ViajeArmado", "P2", prefijo),
                ev_viaje,
            )
        )
        _hasta_que(lambda: len(filas(pipeline, "SELECT 1 FROM evento_crudo")) == 2)

    assert pipeline.consultar_tendencias() == [
        {"anio": 2026, "mes": 11, "tipo": "vuelo", "total": 1}
    ]
    assert pipeline.consultar_destinos() == [
        {"pais": "AR", "ciudad": "Mendoza", "viajes": 1}
    ]
