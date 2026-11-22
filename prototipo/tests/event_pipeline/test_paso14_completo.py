"""Paso 14 completo: historial SCD tipo 2 de `dim_proveedor` (ADR-0016) y compactación de fase 2
de la supresión (ADR-0030). Sin PostgreSQL se saltean."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.event_pipeline.test_event_pipeline import (  # noqa: F401 (fixture `pipeline`)
    RESERVA_1,
    RESERVA_2,
    USUARIO_1,
    USUARIO_2,
    VIAJE_1,
    _reserva_actualizada,
    _viaje_armado,
    filas,
    pipeline,
)
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.event_pipeline import compactacion
from trotamundos.servicios.event_pipeline.aterrizaje import seudonimo_de_usuario
from trotamundos.servicios.event_pipeline.servicio import EventPipeline


def _a_las(evento, instante: str):
    evento.sobre["ocurridoEn"] = instante
    return evento


def _con_operador(evento, operador: str):
    evento.carga["reserva"]["segmentos"][0]["operador"] = operador
    return evento


# --- A. SCD tipo 2 de dim_proveedor -------------------------------------------------------------

def test_scd2_un_cambio_del_proveedor_cierra_su_version_y_abre_otra(pipeline):
    pipeline.consumir(_a_las(_reserva_actualizada(USUARIO_1, RESERVA_1), "2026-11-10T10:00:00Z"))
    pipeline.consumir(_a_las(_con_operador(_reserva_actualizada(USUARIO_1, uuid4()), "Aerolíneas AR"),
                             "2026-11-15T10:00:00Z"))

    versiones = filas(pipeline, "SELECT proveedor_sk, nombre, vigente_desde, vigente_hasta, "
                                "es_vigente FROM dim_proveedor ORDER BY vigente_desde")
    assert [(v["nombre"], v["es_vigente"]) for v in versiones] == [
        ("Aerolíneas Argentinas", False), ("Aerolíneas AR", True)]
    assert versiones[0]["vigente_hasta"] == versiones[1]["vigente_desde"]
    # cada hecho apunta a la versión vigente cuando ocurrió
    hechos = filas(pipeline, "SELECT proveedor_sk FROM hecho_cambio_reserva ORDER BY fecha_id")
    assert {h["proveedor_sk"] for h in hechos} == {v["proveedor_sk"] for v in versiones}


def test_scd2_sin_cambios_no_abre_versiones(pipeline):
    for dia in (10, 11, 12):
        pipeline.consumir(_a_las(_reserva_actualizada(USUARIO_1, uuid4()), f"2026-11-{dia}T10:00:00Z"))
    assert len(filas(pipeline, "SELECT 1 FROM dim_proveedor")) == 1


def test_scd2_un_evento_atrasado_usa_la_version_de_su_momento(pipeline):
    pipeline.consumir(_a_las(_reserva_actualizada(USUARIO_1, uuid4()), "2026-11-10T10:00:00Z"))
    pipeline.consumir(_a_las(_con_operador(_reserva_actualizada(USUARIO_1, uuid4()), "Aerolíneas AR"),
                             "2026-11-15T10:00:00Z"))
    pipeline.consumir(_a_las(_reserva_actualizada(USUARIO_1, uuid4()), "2026-11-12T10:00:00Z"))
    versiones = filas(pipeline, "SELECT proveedor_sk FROM dim_proveedor ORDER BY vigente_desde")
    assert len(versiones) == 2  # el atrasado no reescribió la historia
    (atrasado,) = filas(pipeline, "SELECT h.proveedor_sk FROM hecho_cambio_reserva h "
                                  "JOIN dim_fecha f ON f.fecha_id = h.fecha_id WHERE f.dia = 12")
    assert atrasado["proveedor_sk"] == versiones[0]["proveedor_sk"]


# --- B. compactación de fase 2 (ADR-0030) -------------------------------------------------------

def _baja(usuario) -> Evento:
    return Evento.nuevo("CuentaSuprimida", {"seudonimoAnalitico": seudonimo_de_usuario(str(usuario)),
                                            "suprimidaEn": "2026-11-18T18:00:00Z"},
                        productor="identity-access", usuario_id=None)


@pytest.fixture
def con_reloj(dsn, esquema, contratos):
    reloj = {"ahora": datetime(2026, 11, 20, 3, tzinfo=timezone.utc)}
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    servicio = EventPipeline(configuracion, esquema=esquema, contratos=contratos,
                             clave_de_actas="clave-de-actas-de-prueba", reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.reloj = reloj
    return servicio


def test_la_compactacion_borra_las_filas_y_deja_solo_el_aporte_anonimo(con_reloj):
    pipeline = con_reloj
    pipeline.consumir(_reserva_actualizada(USUARIO_1, RESERVA_1))
    pipeline.consumir(_viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1))
    pipeline.consumir(_reserva_actualizada(USUARIO_2, RESERVA_2))
    pipeline.consumir(_baja(USUARIO_1))
    seudonimo = seudonimo_de_usuario(str(USUARIO_1))

    acta = pipeline.compactar_supresiones()

    # sin filas físicas del usuario suprimido en ningún lado
    assert filas(pipeline, f"SELECT 1 FROM dim_usuario WHERE seudonimo_analitico = '{seudonimo}'") == []
    assert filas(pipeline, f"SELECT 1 FROM evento_crudo WHERE seudonimo_analitico = '{seudonimo}'") == []
    assert filas(pipeline, "SELECT 1 FROM hecho_viaje") == []
    assert len(filas(pipeline, "SELECT 1 FROM hecho_cambio_reserva")) == 1  # el del usuario 2
    # su aporte, solo en el cubo anónimo, invisible para los analistas con menos de 50 usuarios
    (celda,) = filas(pipeline, "SELECT cantidad, usuarios FROM cubo_cambios_anonimo")
    assert (celda["cantidad"], celda["usuarios"]) == (1, 1)
    assert filas(pipeline, "SELECT 1 FROM v_cubo_cambios_anonimo") == []
    (marca,) = filas(pipeline, "SELECT compactada_en FROM lista_supresion_analitica")
    assert marca["compactada_en"] is not None
    # el acta: cantidades y un resumen, nunca el seudónimo, con una firma verificable
    (guardada,) = filas(pipeline, "SELECT * FROM acta_compactacion")
    assert seudonimo not in json.dumps(guardada, default=str)
    assert guardada["seudonimos"] == 1 and guardada["filas_borradas"] == acta["filas_borradas"] > 0
    assert guardada["firma"] == compactacion.firmar(
        {**guardada, "ejecutada_en": guardada["ejecutada_en"]}, "clave-de-actas-de-prueba")
    # una reconstrucción desde los eventos crudos no lo devuelve
    pipeline.reconstruir()
    assert filas(pipeline, f"SELECT 1 FROM dim_usuario WHERE seudonimo_analitico = '{seudonimo}'") == []


def test_se_compacta_cada_15_dias_y_solo_si_hay_bajas(con_reloj):
    pipeline = con_reloj
    pipeline.tareas_periodicas()
    assert filas(pipeline, "SELECT 1 FROM acta_compactacion") == []  # nada que compactar

    pipeline.consumir(_reserva_actualizada(USUARIO_1, RESERVA_1))
    pipeline.consumir(_baja(USUARIO_1))
    pipeline.tareas_periodicas()
    assert len(filas(pipeline, "SELECT 1 FROM acta_compactacion")) == 1

    pipeline.consumir(_reserva_actualizada(USUARIO_2, RESERVA_2))
    pipeline.consumir(_baja(USUARIO_2))
    pipeline.reloj["ahora"] += timedelta(days=14)
    pipeline.tareas_periodicas()
    assert len(filas(pipeline, "SELECT 1 FROM acta_compactacion")) == 1  # todavía no
    pipeline.reloj["ahora"] += timedelta(days=1)
    pipeline.tareas_periodicas()
    assert len(filas(pipeline, "SELECT 1 FROM acta_compactacion")) == 2  # a los 15 días


def test_un_esquema_de_la_version_anterior_recibe_las_tablas_nuevas(con_reloj):
    with conectar(con_reloj._configuracion.dsn_postgres, con_reloj._esquema) as conexion:
        conexion.execute("DROP VIEW v_cubo_cambios_anonimo; DROP TABLE cubo_cambios_anonimo; "
                         "DROP TABLE acta_compactacion")
        conexion.commit()
    con_reloj.crear_esquema()  # como al arrancar sobre una base del contrato 1.1
    assert filas(con_reloj, "SELECT 1 FROM acta_compactacion") == []
    assert filas(con_reloj, "SELECT 1 FROM v_cubo_cambios_anonimo") == []
