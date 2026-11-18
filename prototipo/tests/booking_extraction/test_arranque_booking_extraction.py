"""Fábrica de Uvicorn y camino de mensajes con Redpanda real (paso 9)."""

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.booking_extraction.test_servicio import filas, mensaje
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.servicios.booking_extraction import servicio
from trotamundos.servicios.booking_extraction.servicio import BookingExtraction


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)


async def enviar(servidores, nombre, evento):
    productor = AIOKafkaProducer(bootstrap_servers=servidores)
    await productor.start()
    try:
        clave, valor, cabeceras = evento.a_kafka()
        await productor.send_and_wait(nombre, valor, key=clave, headers=cabeceras)
    finally:
        await productor.stop()


async def leer_uno(servidores, nombre):
    consumidor = AIOKafkaConsumer(nombre, bootstrap_servers=servidores,
                                  auto_offset_reset="earliest", group_id=f"prueba-{uuid4()}")
    await consumidor.start()
    try:
        registro = await asyncio.wait_for(consumidor.getone(), 20)
        return Evento.desde_kafka(registro.value, registro.headers)
    finally:
        await consumidor.stop()


def hasta_que(condicion):
    limite = time.monotonic() + 20
    while not condicion() and time.monotonic() < limite:
        time.sleep(0.2)
    assert condicion()


def test_con_broker_consume_mensaje_y_publica_rechazo_seguro(dsn, esquema, contratos, servidores,
                                                            prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    extraccion = BookingExtraction(configuracion, esquema=esquema, contratos=contratos)
    entrada = mensaje()
    with TestClient(extraccion.app()):
        asyncio.run(enviar(servidores, topico(contratos, entrada.tipo, "P2", prefijo), entrada))
        hasta_que(lambda: len(filas(extraccion,
            "SELECT 1 FROM bandeja_salida WHERE publicado_en IS NOT NULL")) == 1)
    salida = asyncio.run(leer_uno(servidores,
        topico(contratos, "ExtraccionNoReconocida", "P2", prefijo)))
    salida.validar(contratos)
    assert salida.carga["buzonId"] == entrada.carga["buzonId"]
    assert salida.carga["motivo"] == "formatoDesconocido"
    assert "contenido privado inédito" not in json.dumps(salida.carga)


def test_rechazado_del_broker_no_conserva_cuerpo_ni_error_con_pii(dsn, esquema, contratos,
                                                               servidores, prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    extraccion = BookingExtraction(configuracion, esquema=esquema, contratos=contratos)
    entrada = mensaje(cuerpo="PII: secreto del viajero")
    entrada.carga["mensaje"]["remitente"] = "PII: dato que falla validación"
    with TestClient(extraccion.app()):
        asyncio.run(enviar(servidores, topico(contratos, entrada.tipo, "P2", prefijo), entrada))
        hasta_que(lambda: len(filas(extraccion, "SELECT * FROM evento_rechazado")) == 1)
    rechazos = filas(extraccion, "SELECT * FROM evento_rechazado")
    assert rechazos[0]["valor"] is None
    assert "PII:" not in json.dumps(rechazos, default=str)
    assert filas(extraccion, "SELECT * FROM bandeja_salida") == []
