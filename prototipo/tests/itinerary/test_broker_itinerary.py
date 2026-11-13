"""itinerary con el broker real: consume por carriles y publica su outbox (ADR-0012, ADR-0014,
ADR-0020). Usan Redpanda y PostgreSQL de `docker-compose.yml`; sin ellos se saltean.
"""

import asyncio
import copy
import dataclasses
from datetime import datetime, timezone

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from ayudas import USUARIO
from test_servicio import _extraida, _observada
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.itinerary.servicio import Itinerary


@pytest.fixture
def itinerary(dsn, esquema, contratos, servidores, prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), intervalo_tareas_s=0,
                                        broker=servidores, prefijo_topicos=prefijo)
    reloj = {"ahora": datetime(2026, 11, 20, tzinfo=timezone.utc)}
    servicio = Itinerary(configuracion, esquema=esquema, contratos=contratos,
                         reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.bd, servicio.prefijo, servicio.reloj = (dsn, esquema), prefijo, reloj
    return servicio


def _filas(itinerary, consulta: str) -> list[dict]:
    with conectar(*itinerary.bd) as conexion:
        return conexion.execute(consulta).fetchall()


async def _enviar(itinerary, carril: str, *eventos) -> None:
    topico = f"{itinerary.prefijo}{itinerary._contratos.canal_de_evento(eventos[0].tipo)}.{carril}"
    productor = AIOKafkaProducer(bootstrap_servers=itinerary._configuracion.broker)
    await productor.start()
    try:
        for evento in eventos:
            clave, valor, cabeceras = evento.a_kafka()
            await productor.send_and_wait(topico, valor, key=clave, headers=cabeceras)
    finally:
        await productor.stop()


async def _hasta_que(condicion, limite_s: float = 30) -> None:
    async with asyncio.timeout(limite_s):
        while not await asyncio.to_thread(condicion):
            await asyncio.sleep(0.2)


async def _publicados(itinerary, tipo: str, carril: str, esperados: int) -> list:
    topico = f"{itinerary.prefijo}{itinerary._contratos.canal_de_evento(tipo)}.{carril}"
    consumidor = AIOKafkaConsumer(topico, bootstrap_servers=itinerary._configuracion.broker,
                                  group_id=None, auto_offset_reset="earliest")
    await consumidor.start()
    mensajes = []
    try:
        async with asyncio.timeout(20):
            while len(mensajes) < esperados:
                for lote in (await consumidor.getmany(timeout_ms=300)).values():
                    mensajes += lote
    finally:
        await consumidor.stop()
    return mensajes


def _pendientes(itinerary) -> int:
    return len(_filas(itinerary, "SELECT 1 FROM bandeja_salida WHERE publicado_en IS NULL"))


async def test_consume_publica_y_no_repite_el_efecto(itinerary, observacion):
    evento = _extraida(observacion)
    async with itinerary.con_broker():
        await _enviar(itinerary, "p2", evento, evento)  # la misma entrega dos veces
        await _hasta_que(lambda: len(_filas(itinerary, "SELECT 1 FROM bandeja_entrada")) == 1
                         and len(_filas(itinerary, "SELECT 1 FROM bandeja_salida")) == 2
                         and _pendientes(itinerary) == 0)
        await asyncio.sleep(1)  # el duplicado ya pasó por la bandeja de entrada

    assert len(_filas(itinerary, "SELECT 1 FROM reserva")) == 1
    # El vuelo sale el 1/12 y "ahora" es el 20/11: más de 48 h, carril P2.
    [actualizada] = await _publicados(itinerary, "ReservaActualizada", "p2", 1)
    assert actualizada.key == str(USUARIO).encode()
    await _publicados(itinerary, "ViajeArmado", "p2", 1)


async def test_lo_que_sale_dentro_de_48_horas_va_por_p1(itinerary, observacion):
    itinerary.reloj["ahora"] = datetime(2026, 11, 30, 20, tzinfo=timezone.utc)  # sale en 17 h
    cancelacion = _observada({**observacion, "cancelada": True})
    async with itinerary.con_broker():
        await _enviar(itinerary, "p1", cancelacion)
        await _hasta_que(lambda: len(_filas(itinerary, "SELECT 1 FROM bandeja_salida")) >= 3
                         and _pendientes(itinerary) == 0)

    await _publicados(itinerary, "ReservaActualizada", "p1", 1)
    await _publicados(itinerary, "ReservaCancelada", "p1", 1)


async def test_un_evento_invalido_queda_registrado_y_no_frena_al_resto(itinerary, observacion):
    invalida = copy.deepcopy(observacion)
    invalida["segmentos"][0]["detalle"].pop("numeroDeVuelo")  # no valida contra el tipo
    async with itinerary.con_broker():
        await _enviar(itinerary, "p2", _extraida(invalida), _extraida(observacion))
        await _hasta_que(lambda: len(_filas(itinerary, "SELECT 1 FROM reserva")) == 1)

    [rechazado] = _filas(itinerary, "SELECT consumidor, usuario_id, motivo FROM evento_rechazado")
    assert rechazado["consumidor"] == "itinerary" and rechazado["usuario_id"] == USUARIO
    assert "numeroDeVuelo" in rechazado["motivo"]
