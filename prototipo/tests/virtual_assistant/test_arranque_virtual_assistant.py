"""`virtual-assistant` arranca como en `docker-compose.yml` y consume `DisrupcionDetectada` por el
broker real (Redpanda; sin él, la segunda prueba se saltea)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.virtual_assistant.datos import (
    SECRETO_JWT,
    USUARIO,
    VUELO,
    ItinerarioEnMemoria,
    SoporteEnMemoria,
    sesion_http,
)
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.virtual_assistant import servicio
from trotamundos.servicios.virtual_assistant.servicio import VirtualAssistant


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


def test_con_broker_consume_la_disrupcion_y_la_menciona(dsn, esquema, contratos, servidores,
                                                        prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    itinerario = ItinerarioEnMemoria()
    asistente = VirtualAssistant(configuracion, esquema=esquema, contratos=contratos,
                                 lector=itinerario, escritor=itinerario,
                                 abridor=SoporteEnMemoria(), secreto_jwt=SECRETO_JWT)
    disrupcion = Evento.nuevo("DisrupcionDetectada", {
        "disrupcionId": "disr-1", "proveedor": "Aerolíneas Argentinas", "severidad": "alta",
        "descripcion": "Vuelo AR1402 cancelado",
        "afectados": [{"usuarioId": str(USUARIO), "reservaIds": [VUELO]}]},
        productor="provider-sync", usuario_id=str(USUARIO), region="AM")

    def filas() -> list[dict]:
        with conectar(dsn, esquema) as conexion:
            return conexion.execute("SELECT 1 FROM disrupcion_conocida").fetchall()

    with TestClient(asistente.app()) as cliente:  # ciclo de vida: esquema y consumidor
        asyncio.run(_enviar(servidores, topico(contratos, "DisrupcionDetectada", "P1", prefijo),
                            disrupcion))
        _hasta_que(lambda: len(filas()) == 1)
        sesion = cliente.post("/asistente/sesiones",
                              headers={**sesion_http(), "Idempotency-Key": str(uuid4())})
        respuesta = cliente.post(f"/asistente/sesiones/{sesion.json()['id']}/mensajes",
                                 content=json.dumps({"texto": "¿Qué pasa con mi vuelo?"}),
                                 headers={**sesion_http(), "Idempotency-Key": str(uuid4()),
                                          "Content-Type": "application/json"})
    assert respuesta.status_code == 200, respuesta.text
    assert "Vuelo AR1402 cancelado" in respuesta.json()["mensajes"][1]
    assert respuesta.json()["accionPropuesta"]["tipo"] == "derivarALaAgencia"
