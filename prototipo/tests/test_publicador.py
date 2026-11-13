"""Publicación de la outbox en el broker (ADR-0012). Usan Redpanda y PostgreSQL de
`docker-compose.yml`; sin ellos se saltean. Cada prueba usa tópicos propios."""

import asyncio
import json
import uuid

import pytest
from aiokafka import AIOKafkaConsumer

from trotamundos.comun.carriles import asegurar_topicos, topico
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import crear_esquema, escribir_en_outbox, transaccion
from trotamundos.comun.publicador import PublicadorDeOutbox

USUARIO_A = "00000000-0000-4000-8000-00000000000a"
USUARIO_B = "00000000-0000-4000-8000-00000000000b"


@pytest.fixture
def bd(dsn, esquema):
    crear_esquema(dsn, esquema, ())
    return dsn, esquema


def _conflicto(usuario: str, numero: int) -> Evento:
    return Evento.nuevo("ConflictoDeFuentesDetectado", {
        "reservaId": str(uuid.UUID(int=numero)), "conflicto": {
            "id": str(uuid.uuid4()), "campo": "segmentos[0].detalle.puerta", "estado": "Abierto",
            "valores": [{"fuente": "manual", "valor": "1"}, {"fuente": "proveedor", "valor": "2"}]}},
        productor="itinerary", usuario_id=usuario)


async def _leer_todo(servidores: str, nombre: str, esperados: int) -> list:
    consumidor = AIOKafkaConsumer(nombre, bootstrap_servers=servidores, group_id=None,
                                  auto_offset_reset="earliest")
    await consumidor.start()
    mensajes = []
    try:
        async with asyncio.timeout(20):
            while len(mensajes) < esperados:
                for lote in (await consumidor.getmany(timeout_ms=500)).values():
                    mensajes += lote
        await asyncio.sleep(0.5)  # por si hay de más
        for lote in (await consumidor.getmany(timeout_ms=500)).values():
            mensajes += lote
    finally:
        await consumidor.stop()
    return mensajes


async def test_el_publicador_lleva_la_outbox_al_broker_en_orden(bd, servidores, prefijo, contratos):
    eventos = [_conflicto(USUARIO_A, 1), _conflicto(USUARIO_B, 2), _conflicto(USUARIO_A, 3)]
    with transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, eventos, contratos)
    destino = topico(contratos, "ConflictoDeFuentesDetectado", "P2", prefijo)
    await asegurar_topicos(servidores, [destino])
    publicador = PublicadorDeOutbox(*bd, servidores, contratos, prefijo)
    await publicador.iniciar()
    try:
        assert await publicador.publicar_pendientes() == 3
        assert await publicador.publicar_pendientes() == 0  # ya están marcados
    finally:
        await publicador.detener()

    mensajes = await _leer_todo(servidores, destino, 3)
    del_usuario_a = sorted((m for m in mensajes if m.key == USUARIO_A.encode()),
                           key=lambda m: (m.partition, m.offset))
    assert [json.loads(m.value)["reservaId"] for m in del_usuario_a] == [
        str(uuid.UUID(int=1)), str(uuid.UUID(int=3))]  # en orden, en la misma partición
    assert len({m.partition for m in del_usuario_a}) == 1
    assert Evento.desde_kafka(mensajes[0].value, mensajes[0].headers).sobre["productor"] == "itinerary"


async def test_si_falla_entre_enviar_y_marcar_se_reenvia(bd, servidores, prefijo, contratos, monkeypatch):
    with transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, [_conflicto(USUARIO_A, 1)], contratos)
    destino = topico(contratos, "ConflictoDeFuentesDetectado", "P2", prefijo)
    await asegurar_topicos(servidores, [destino])
    publicador = PublicadorDeOutbox(*bd, servidores, contratos, prefijo)
    await publicador.iniciar()
    original = publicador._marcar

    def falla(eventos_id):
        raise RuntimeError("se cayó la base entre enviar y marcar")

    try:
        monkeypatch.setattr(publicador, "_marcar", falla)
        with pytest.raises(RuntimeError):
            await publicador.publicar_pendientes()
        monkeypatch.setattr(publicador, "_marcar", original)
        assert await publicador.publicar_pendientes() == 1  # no se perdió: se reenvía
    finally:
        await publicador.detener()

    mensajes = await _leer_todo(servidores, destino, 2)
    assert len(mensajes) == 2  # al menos una vez: el duplicado lo frena la bandeja de entrada


async def test_un_solo_publicador_por_esquema(bd, servidores, prefijo, contratos):
    with transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, [_conflicto(USUARIO_A, 1)], contratos)
    uno = PublicadorDeOutbox(*bd, servidores, contratos, prefijo)
    otro = PublicadorDeOutbox(*bd, servidores, contratos, prefijo)
    try:
        assert await asyncio.to_thread(uno._tengo_el_turno) is True
        assert await otro.publicar_pendientes() == 0  # el turno lo tiene el primero
    finally:
        await uno.detener()
        await otro.detener()
