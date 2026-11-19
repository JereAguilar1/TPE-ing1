"""Fábrica de Uvicorn y recorrido con Redpanda real para `provider-sync` (paso 10)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.provider_sync.test_conformidad_adaptadores import ADAPTADOR_ID, GRABACIONES
from tests.provider_sync.test_provider_sync import (
    AHORA,
    RESERVA_1,
    SECRETO_WEBHOOK,
    USUARIO_1,
    _evento_reserva_actualizada,
    filas,
)
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.servicios.provider_sync import servicio
from trotamundos.servicios.provider_sync.receptor_de_notificaciones import firma
from trotamundos.servicios.provider_sync.servicio import ProviderSync


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


async def _leer_uno(servidores: str, nombre: str) -> Evento:
    consumidor = AIOKafkaConsumer(
        nombre,
        bootstrap_servers=servidores,
        auto_offset_reset="earliest",
        group_id=f"prueba-{uuid4()}",
    )
    await consumidor.start()
    try:
        registro = await asyncio.wait_for(consumidor.getone(), 20)
        return Evento.desde_kafka(registro.value, registro.headers)
    finally:
        await consumidor.stop()


def _hasta_que(condicion, limite_s: float = 20) -> None:
    limite = time.monotonic() + limite_s
    while not condicion() and time.monotonic() < limite:
        time.sleep(0.2)
    assert condicion()


def test_con_broker_consume_reserva_y_publica_observacion_y_disrupcion(
    dsn, esquema, contratos, servidores, prefijo
):
    configuracion = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker=servidores,
        prefijo_topicos=prefijo,
        intervalo_tareas_s=0,
    )
    sync = ProviderSync(
        configuracion,
        esquema=esquema,
        contratos=contratos,
        secreto_webhook=SECRETO_WEBHOOK,
        reloj=lambda: AHORA,
    )
    actualizada = _evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123")
    cuerpo = json.dumps(GRABACIONES[2]["notificacion"]).encode("utf-8")

    with TestClient(sync.app()) as cliente:
        asyncio.run(
            _enviar(
                servidores,
                topico(contratos, "ReservaActualizada", "P2", prefijo),
                actualizada,
            )
        )
        _hasta_que(lambda: len(filas(sync, "SELECT 1 FROM reserva_seguida")) == 1)

        respuesta = cliente.post(
            "/webhooks/proveedor",
            content=cuerpo,
            headers={
                "X-Proveedor-Id": ADAPTADOR_ID,
                "X-Firma": firma(cuerpo, SECRETO_WEBHOOK),
                "Content-Type": "application/json",
            },
        )
        assert respuesta.status_code == 202

        _hasta_que(
            lambda: len(
                filas(sync, "SELECT 1 FROM bandeja_salida WHERE publicado_en IS NOT NULL")
            )
            == 2
        )

    disrupcion = asyncio.run(
        _leer_uno(servidores, topico(contratos, "DisrupcionDetectada", "P1", prefijo))
    )
    observada = asyncio.run(
        _leer_uno(servidores, topico(contratos, "ReservaObservada", "P1", prefijo))
    )
    disrupcion.validar(contratos)
    observada.validar(contratos)

    assert disrupcion.carga["disrupcionId"] == "DISR-AR1402-METEO"
    assert disrupcion.carga["afectados"] == [
        {"usuarioId": str(USUARIO_1), "reservaIds": [str(RESERVA_1)]}
    ]
    assert observada.sobre["idDeCausa"] == "DISR-AR1402-METEO"
    assert observada.carga["observacion"]["cancelada"] is True
