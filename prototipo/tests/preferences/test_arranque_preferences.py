"""`preferences` arranca como en `docker-compose.yml` y su `PreferenciasActualizadas` llega por el
broker real a `support-liaison`, que guarda la agencia preferida (sin broker, se saltea)."""

from __future__ import annotations

import dataclasses
import json
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.preferences.test_preferences import SECRETO, TIPO, USUARIO, sesion
from tests.support_liaison.test_support_liaison import LectorDePrueba
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.preferences import servicio
from trotamundos.servicios.preferences.servicio import Preferences
from trotamundos.servicios.support_liaison.servicio import SupportLiaison


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)


def test_con_broker_la_agencia_preferida_llega_a_support_liaison(dsn, esquema, contratos,
                                                                  servidores, prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo,
                                        intervalo_tareas_s=0)
    preferencias = Preferences(configuracion, esquema=esquema, contratos=contratos,
                               secreto_jwt=SECRETO)
    esquema_soporte = f"{esquema}_soporte"
    soporte = SupportLiaison(configuracion, esquema=esquema_soporte, contratos=contratos,
                             lector_de_viajes=LectorDePrueba(), secreto_jwt=SECRETO)
    try:
        with TestClient(soporte.app()), TestClient(preferencias.app()) as cliente:
            respuesta = cliente.put("/preferencias", content=json.dumps({
                "idioma": "es-AR", "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM",
                "agenciaPreferida": {"id": "agencia-sur", "nombre": "Agencia del Sur"}}),
                headers={**sesion(), **TIPO})
            assert respuesta.status_code == 200

            def guardada():
                with conectar(dsn, esquema_soporte) as conexion:
                    return conexion.execute("SELECT 1 FROM agencia_preferida WHERE usuario_id = %s",
                                            (str(USUARIO),)).fetchone()
            limite = time.monotonic() + 30
            while not guardada() and time.monotonic() < limite:
                time.sleep(0.2)
            assert guardada()
    finally:
        with conectar(dsn, "public") as conexion:
            conexion.execute(f'DROP SCHEMA IF EXISTS "{esquema_soporte}" CASCADE')
            conexion.commit()
