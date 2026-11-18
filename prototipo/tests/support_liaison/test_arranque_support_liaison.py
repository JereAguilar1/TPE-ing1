"""`support-liaison` arranca como en `docker-compose.yml`, consume `PreferenciasActualizadas` y
publica `CasoDerivado` por el broker real (Redpanda; sin él, la segunda prueba se saltea)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support_liaison.test_support_liaison import (
    AGENCIA,
    SECRETO_JWT,
    TIPO,
    USUARIO,
    VIAJE,
    LectorDePrueba,
    _sesion,
)
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.support_liaison import servicio
from trotamundos.servicios.support_liaison.servicio import SupportLiaison


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


async def _leer_uno(servidores: str, nombre: str) -> dict:
    consumidor = AIOKafkaConsumer(nombre, bootstrap_servers=servidores,
                                  auto_offset_reset="earliest", group_id=f"prueba-{uuid4()}")
    await consumidor.start()
    try:
        mensaje = await asyncio.wait_for(consumidor.getone(), 20)
        return json.loads(mensaje.value)
    finally:
        await consumidor.stop()


def _hasta_que(condicion, limite_s: float = 20) -> None:
    limite = time.monotonic() + limite_s
    while not condicion() and time.monotonic() < limite:
        time.sleep(0.2)
    assert condicion()


def test_con_broker_consume_las_preferencias_y_publica_el_caso(dsn, esquema, contratos,
                                                               servidores, prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    soporte = SupportLiaison(configuracion, esquema=esquema, contratos=contratos,
                             lector_de_viajes=LectorDePrueba(), secreto_jwt=SECRETO_JWT)
    preferencias = Evento.nuevo("PreferenciasActualizadas", {"preferencias": {
        "agenciaPreferida": AGENCIA, "idioma": "es-AR",
        "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM"}},
        productor="preferences", usuario_id=str(USUARIO), region="AM")

    def filas(consulta: str) -> list[dict]:
        with conectar(dsn, esquema) as conexion:
            return conexion.execute(consulta).fetchall()

    with TestClient(soporte.app()) as cliente:  # ciclo de vida: esquema, consumidor y publicador
        asyncio.run(_enviar(servidores, topico(contratos, "PreferenciasActualizadas", "P2", prefijo),
                            preferencias))
        _hasta_que(lambda: len(filas("SELECT 1 FROM agencia_preferida")) == 1)
        respuesta = cliente.post("/casos", content=json.dumps(
            {"viajeId": str(VIAJE), "motivo": "cancelacion"}),
            headers={**_sesion(), **TIPO, "Idempotency-Key": str(uuid4())})
        assert respuesta.status_code == 201 and respuesta.json()["estado"] == "Derivado"
        _hasta_que(lambda: len(filas(
            "SELECT 1 FROM bandeja_salida WHERE publicado_en IS NOT NULL")) == 1)

    carga = asyncio.run(_leer_uno(servidores, topico(contratos, "CasoDerivado", "P1", prefijo)))
    assert carga["casoId"] == respuesta.json()["id"] and carga["agencia"] == "Agencia del Sur"
