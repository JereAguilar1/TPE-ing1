"""Consumo por carriles de prioridad (ADR-0014, ADR-0020). Usan Redpanda y PostgreSQL de
`docker-compose.yml`; sin ellos se saltean. Cada prueba usa tópicos propios."""

import asyncio
import uuid

import pytest
from aiokafka import AIOKafkaProducer

from trotamundos.comun.carriles import ORDEN_DE_LECTURA, Carril, asegurar_topicos
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar, crear_esquema

USUARIO_A = "00000000-0000-4000-8000-00000000000a"


@pytest.fixture
def bd(dsn, esquema):
    crear_esquema(dsn, esquema, DDL_RECHAZADOS)
    return dsn, esquema


def _conflicto(usuario: str, numero: int) -> Evento:
    return Evento.nuevo("ConflictoDeFuentesDetectado", {
        "reservaId": str(uuid.UUID(int=numero)), "conflicto": {
            "id": str(uuid.uuid4()), "campo": "segmentos[0].detalle.puerta", "estado": "Abierto",
            "valores": [{"fuente": "manual", "valor": "1"}, {"fuente": "proveedor", "valor": "2"}]}},
        productor="itinerary", usuario_id=usuario)


async def _producir(servidores: str, topico: str, *mensajes: Evento | bytes) -> None:
    productor = AIOKafkaProducer(bootstrap_servers=servidores)
    await productor.start()
    try:
        for mensaje in mensajes:
            if isinstance(mensaje, Evento):
                clave, valor, cabeceras = mensaje.a_kafka()
                await productor.send_and_wait(topico, valor, key=clave, headers=cabeceras)
            else:
                await productor.send_and_wait(topico, mensaje, key=b"x", headers=[("tipo", b"Raro")])
    finally:
        await productor.stop()


@pytest.fixture
def carriles(servidores, prefijo):
    topicos = {c: [f"{prefijo}carril.{c.lower()}"] for c in ORDEN_DE_LECTURA}
    asyncio.run(asegurar_topicos(servidores, [t for ts in topicos.values() for t in ts]))
    return topicos


async def _consumidor(bd, servidores, carriles, manejar, **opciones):
    consumidor = ConsumidorConCarriles(servidores, f"prueba-{uuid.uuid4().hex[:6]}",
                                              carriles, manejar, *bd, reintento_s=0, **opciones)
    await consumidor.iniciar()
    await consumidor.esperar_asignacion()
    return consumidor


async def _hasta_procesar(consumidor, cuantos: int) -> list:
    vueltas = []
    async with asyncio.timeout(20):
        while sum(n for _, n in vueltas) < cuantos:
            carril, n = await consumidor.vuelta()
            if n:
                vueltas.append((carril, n))
            else:
                await asyncio.sleep(0.1)
    return vueltas


async def test_p1_se_lee_antes_que_p2_aunque_llegue_despues(bd, servidores, carriles):
    await _producir(servidores, carriles[Carril.P2][0], _conflicto(USUARIO_A, 2))
    await _producir(servidores, carriles[Carril.P1][0], _conflicto(USUARIO_A, 1))
    vistos = []
    consumidor = await _consumidor(bd, servidores, carriles, lambda e: vistos.append(e.carga["reservaId"]))
    try:
        await asyncio.sleep(1)  # que los dos carriles tengan sus mensajes a mano
        vueltas = await _hasta_procesar(consumidor, 2)
    finally:
        await consumidor.detener()

    assert [c for c, _ in vueltas] == [Carril.P1, Carril.P2]
    assert vistos == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]


async def test_un_mensaje_invalido_se_guarda_y_se_sigue(bd, servidores, carriles):
    await _producir(servidores, carriles[Carril.P2][0], b"no es json", _conflicto(USUARIO_A, 1))
    vistos = []
    consumidor = await _consumidor(bd, servidores, carriles, lambda e: vistos.append(e))
    try:
        await _hasta_procesar(consumidor, 1)
        await asyncio.sleep(0.5)
        assert await consumidor.vuelta() == (None, 0)  # el inválido no vuelve
    finally:
        await consumidor.detener()

    assert len(vistos) == 1
    with conectar(*bd) as conexion:
        [rechazado] = conexion.execute("SELECT * FROM evento_rechazado").fetchall()
    assert rechazado["valor"] == b"no es json" and "JSON" in rechazado["motivo"]


async def test_un_error_transitorio_se_reintenta_sin_perder_el_mensaje(bd, servidores, carriles):
    await _producir(servidores, carriles[Carril.P1][0], _conflicto(USUARIO_A, 1))
    intentos = []

    def manejar(evento):
        intentos.append(evento.id)
        if len(intentos) == 1:
            raise RuntimeError("la base no responde")

    consumidor = await _consumidor(bd, servidores, carriles, manejar)
    try:
        async with asyncio.timeout(20):
            while len(intentos) < 2:
                await consumidor.vuelta()
                await asyncio.sleep(0.1)
    finally:
        await consumidor.detener()

    assert len(intentos) == 2 and intentos[0] == intentos[1]


async def test_p3_se_puede_pausar(bd, servidores, carriles):
    await _producir(servidores, carriles[Carril.P3][0], _conflicto(USUARIO_A, 3))
    pausado = {"si": True}
    vistos = []
    consumidor = await _consumidor(bd, servidores, carriles, lambda e: vistos.append(e),
                                   pausar_p3=lambda: pausado["si"])
    try:
        for _ in range(5):
            await consumidor.vuelta()
        assert vistos == []  # retenido en el broker, sin pérdida
        pausado["si"] = False
        await _hasta_procesar(consumidor, 1)
    finally:
        await consumidor.detener()

    assert len(vistos) == 1
