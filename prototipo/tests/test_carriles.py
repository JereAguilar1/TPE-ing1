"""Carriles de prioridad y tópicos (ADR-0020). Las que crean tópicos usan el broker de
`docker-compose.yml` y se saltean sin él."""

import asyncio

import pytest
from aiokafka.admin import AIOKafkaAdminClient

from trotamundos.comun import carriles
from trotamundos.comun.carriles import Carril
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import escribir_en_outbox

USUARIO_A = "00000000-0000-4000-8000-00000000000a"


def test_los_carriles_salen_del_contrato(contratos):
    assert carriles.carril_fijo(contratos, "ReservaCancelada") == Carril.P1
    assert carriles.carril_fijo(contratos, "ViajeCompletado") == Carril.P3
    assert carriles.carril_fijo(contratos, "ReservaObservada") is None  # regla del productor
    assert carriles.carriles_posibles(contratos, "ReservaObservada") == (Carril.P1, Carril.P2)
    assert carriles.carriles_posibles(contratos, "ReservaActualizada") == carriles.ORDEN_DE_LECTURA


def test_el_topico_es_el_canal_del_contrato_mas_el_carril(contratos):
    assert carriles.topico(contratos, "ReservaObservada", "P1") == "dominio.reserva-observada.p1"
    assert carriles.topico(contratos, "ViajeArmado", Carril.P2, "prueba.") == "prueba.dominio.viaje-armado.p2"


def test_la_outbox_exige_el_carril_cuando_el_contrato_da_una_regla(contratos, observacion):
    observada = Evento.nuevo("ReservaObservada", {
        "adaptador": {"id": "ar", "version": "1"}, "observacion": {**observacion, "fuente": "proveedor"}},
        productor="provider-sync", usuario_id=USUARIO_A)
    with pytest.raises(ValueError):  # x-carril es una regla y el productor no dio carril
        escribir_en_outbox(None, [observada], contratos)


async def _existentes(servidores: str, prefijo: str) -> list[str]:
    administrador = AIOKafkaAdminClient(bootstrap_servers=servidores)
    await administrador.start()
    try:
        return sorted(t for t in await administrador.list_topics() if t.startswith(prefijo))
    finally:
        await administrador.close()


def test_asegurar_topicos_los_crea_una_vez_y_no_oculta_errores(servidores, prefijo):
    nombres = [f"{prefijo}a.p1", f"{prefijo}a.p2"]
    asyncio.run(carriles.asegurar_topicos(servidores, nombres))
    asyncio.run(carriles.asegurar_topicos(servidores, nombres))  # ya existen: no pasa nada
    assert asyncio.run(_existentes(servidores, prefijo)) == nombres

    with pytest.raises(carriles.TopicoNoCreado):  # el broker rechaza cero particiones
        asyncio.run(carriles.asegurar_topicos(servidores, [f"{prefijo}b.p1"], particiones=0))


def test_borrar_topicos_exige_un_prefijo(servidores):
    with pytest.raises(ValueError):
        asyncio.run(carriles.borrar_topicos(servidores, ""))
