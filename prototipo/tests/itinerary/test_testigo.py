"""Testigo transregional de los comandos manuales (paso 16, ADR-0018 §3 y §4, QA-05).

Dos regiones en la misma base, cada una con su esquema: `AM` registra sus comandos manuales en el
testigo y `EU`, la región de respaldo, los reproduce al atender al usuario. Sin PostgreSQL se
saltean.
"""

import copy
import dataclasses
import uuid
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from ayudas import USUARIO, instante
from trotamundos.comun.config import Configuracion
from trotamundos.comun.errores import Problema
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.itinerary import gestion_manual
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.itinerary.testigo import Cinta, RegistroTestigo


@pytest.fixture
def esquemas(dsn):
    nombres = {clave: f"prueba_{clave}_{uuid.uuid4().hex[:10]}" for clave in ("am", "eu", "testigo")}
    yield nombres
    with psycopg.connect(dsn, autocommit=True) as conexion:
        for nombre in nombres.values():
            conexion.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(nombre)))


def _region(dsn, contratos, esquema, region, reloj, **testigos) -> Itinerary:
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        intervalo_tareas_s=0, broker="", region=region)
    servicio = Itinerary(configuracion, esquema=esquema, contratos=contratos,
                         reloj=lambda: reloj["ahora"], **testigos)
    servicio.crear_esquema()
    return servicio


@pytest.fixture
def reloj():
    return {"ahora": instante(20)}


@pytest.fixture
def am(dsn, contratos, esquemas, reloj):
    return _region(dsn, contratos, esquemas["am"], "AM", reloj,
                   testigo_remoto=RegistroTestigo(dsn, esquemas["testigo"]))


@pytest.fixture
def eu(dsn, contratos, esquemas, reloj):
    return _region(dsn, contratos, esquemas["eu"], "EU", reloj,
                   testigo_local=RegistroTestigo(dsn, esquemas["testigo"]))


@pytest.fixture
def alta(observacion):
    segmento = copy.deepcopy(observacion["segmentos"][0])
    del segmento["versionTipo"]
    return {"identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
            "segmentos": [segmento]}


def _testigo(dsn, esquemas) -> list[dict]:
    with conectar(dsn, esquemas["testigo"]) as conexion:
        return conexion.execute("SELECT operacion, aplicado_en, error FROM registro_testigo "
                                "ORDER BY secuencia").fetchall()


def test_cada_comando_confirmado_deja_su_entrada_en_la_region_de_respaldo(am, alta, dsn, esquemas):
    _, creada = am.crear_reserva(USUARIO, uuid4(), alta)
    am.eliminar_reserva(USUARIO, UUID(creada["reserva"]["id"]))

    assert [(e["operacion"], e["aplicado_en"]) for e in _testigo(dsn, esquemas)] == [
        ("crearReserva", None), ("eliminarReserva", None)]


def test_la_region_de_respaldo_reproduce_los_comandos_con_los_mismos_ids(am, eu, alta, reloj):
    """RPO = 0: lo confirmado en AM está en EU igual, aunque AM ya no responda."""
    _, creada = am.crear_reserva(USUARIO, uuid4(), alta)
    reserva = creada["reserva"]
    segmento = {k: v for k, v in reserva["segmentos"][0].items()
                if k not in ("id", "orden", "estado", "versionTipo", "fijados")}
    segmento["detalle"]["puerta"] = "12"
    reloj["ahora"] = instante(21)
    editada = am.editar_reserva(USUARIO, UUID(reserva["id"]),
                                {"version": reserva["version"], "segmentos": [segmento]})
    reloj["ahora"] = instante(25)  # la reproducción usa los instantes grabados, no los de ahora

    assert eu.leer_reserva(USUARIO, reserva["id"]) == editada["reserva"]
    assert eu.leer_panel(USUARIO) == am.leer_panel(USUARIO)  # incluida versionUsuario


def test_lo_reproducido_no_se_repite_y_la_region_de_respaldo_sigue_escribiendo(am, eu, alta, dsn,
                                                                               esquemas):
    _, creada = am.crear_reserva(USUARIO, uuid4(), alta)
    eu.leer_panel(USUARIO)
    eu.leer_panel(USUARIO)

    # Ya conmutada, EU escribe para el usuario sobre lo reproducido (ADR-0018 §4).
    eu.eliminar_reserva(USUARIO, UUID(creada["reserva"]["id"]))
    assert eu.leer_reserva(USUARIO, creada["reserva"]["id"]) is None
    assert [e["error"] for e in _testigo(dsn, esquemas)] == [None]
    with conectar(dsn, esquemas["eu"]) as conexion:
        assert len(conexion.execute("SELECT * FROM reserva").fetchall()) == 1


def test_una_entrada_que_no_se_puede_reproducir_no_frena_a_las_siguientes(am, eu, alta, dsn,
                                                                          esquemas):
    # Una baja sobre una reserva que EU no tiene (por ejemplo, una ingerida por correo).
    with pytest.raises(gestion_manual.NoEncontrada):
        am.eliminar_reserva(USUARIO, UUID(int=7))
    RegistroTestigo(dsn, esquemas["testigo"]).registrar(
        USUARIO, "AM", "eliminarReserva", [UUID(int=7)], Cinta())
    _, creada = am.crear_reserva(USUARIO, uuid4(), alta)

    assert eu.leer_reserva(USUARIO, creada["reserva"]["id"]) == am.leer_reserva(
        USUARIO, creada["reserva"]["id"])
    errores = [e["error"] for e in _testigo(dsn, esquemas)]
    assert errores[0].startswith("NoEncontrada") and errores[1] is None


def test_sin_testigo_el_comando_no_se_confirma(dsn, contratos, esquemas, reloj, alta):
    caido = RegistroTestigo("postgresql://nadie@127.0.0.1:9/nada", "testigo")
    am = _region(dsn, contratos, esquemas["am"], "AM", reloj, testigo_remoto=caido)

    with pytest.raises(Problema) as error:
        am.crear_reserva(USUARIO, uuid4(), alta)
    assert error.value.status == 503


def test_la_supresion_borra_tambien_el_testigo(am, alta, dsn, esquemas):
    am.crear_reserva(USUARIO, uuid4(), alta)

    am.suprimir_usuario(USUARIO)

    assert _testigo(dsn, esquemas) == []
