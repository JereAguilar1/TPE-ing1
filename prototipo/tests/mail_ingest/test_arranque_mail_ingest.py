"""`mail-ingest` arranca como en `docker-compose.yml`, consume `EstadoDeBuzonCambiado` y publica
`MensajeDeViajeRecibido` por el broker real (Redpanda; sin él, la segunda prueba se saltea)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.mail_ingest.test_mail_ingest import USUARIO, EmisorDePrueba, _correo
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.mail_ingest import servicio
from trotamundos.servicios.mail_ingest.servicio import MailIngest


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


def test_con_broker_consume_el_estado_y_publica_el_mensaje(dsn, esquema, contratos, servidores,
                                                         prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    mail = MailIngest(configuracion, esquema=esquema, contratos=contratos,
                      emisor_de_tokens=EmisorDePrueba())
    buzon_id = uuid4()
    activo = Evento.nuevo("EstadoDeBuzonCambiado", {
        "buzonId": str(buzon_id), "estadoAnterior": "Solicitado", "estadoNuevo": "Activo",
        "motivo": "otorgado", "via": "oauth", "proveedor": "gmail",
        "correoDelTitular": "viajero@test.app"},
        productor="identity-access", usuario_id=str(USUARIO), region="AM")

    def filas(consulta: str) -> list[dict]:
        with conectar(dsn, esquema) as conexion:
            return conexion.execute(consulta).fetchall()

    with TestClient(mail.app()):  # ciclo de vida: esquema, cola, consumidor y publicador
        asyncio.run(_enviar(servidores, topico(contratos, "EstadoDeBuzonCambiado", "P2", prefijo),
                            activo))
        _hasta_que(lambda: len(filas("SELECT 1 FROM buzon_ingesta WHERE activo")) == 1)
        mail.guardar_filtros(USUARIO, {"permitidos": ["*@aerolinea.com"], "bloqueados": []})
        mail.adaptadores["oauth"].entregar(str(buzon_id), _correo("reservas@aerolinea.com"))
        with conectar(dsn, esquema) as conexion:
            conexion.execute("INSERT INTO cola_buzones VALUES (%s, %s, 'aviso', now()) "
                             "ON CONFLICT DO NOTHING", (buzon_id, USUARIO))
        _hasta_que(lambda: len(filas("SELECT 1 FROM bandeja_salida WHERE publicado_en IS NOT NULL")) == 1)

    carga = asyncio.run(_leer_uno(servidores, topico(contratos, "MensajeDeViajeRecibido", "P2",
                                                     prefijo)))
    assert carga["buzonId"] == str(buzon_id)
    assert carga["mensaje"]["remitente"] == "reservas@aerolinea.com"
