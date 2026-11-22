"""`notification` arranca como en `docker-compose.yml`: consume `ReservaActualizada` y publica
`NotificacionEmitida` por el broker real (Redpanda; sin él, la segunda prueba se saltea)."""

from __future__ import annotations

import asyncio
import dataclasses

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.notification.test_notification import HORARIO, USUARIO, VIAJE, actualizada
from tests.support_liaison.test_arranque_support_liaison import _enviar, _hasta_que, _leer_uno
from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.notification import servicio
from trotamundos.servicios.notification.servicio import Notification


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)


def test_con_broker_consume_el_cambio_y_publica_el_aviso(dsn, esquema, contratos, servidores,
                                                         prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    notification = Notification(configuracion, esquema=esquema, contratos=contratos)
    evento = actualizada([HORARIO])

    def publicadas() -> int:
        with conectar(dsn, esquema) as conexion:
            return len(conexion.execute(
                "SELECT 1 FROM bandeja_salida WHERE publicado_en IS NOT NULL").fetchall())

    with TestClient(notification.app()):
        asyncio.run(_enviar(servidores, topico(contratos, "ReservaActualizada", "P1", prefijo),
                            evento))
        _hasta_que(lambda: publicadas() == 1)

    carga = asyncio.run(_leer_uno(servidores, topico(contratos, "NotificacionEmitida", "P3",
                                                     prefijo)))
    assert (carga["severidad"], carga["viajeId"]) == ("critica", VIAJE)
    assert [c for c, u, _ in notification.canales_externos.entregados if u == USUARIO] == ["push"]
