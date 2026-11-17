"""`identity-access` arranca como en `docker-compose.yml` y publica su *outbox* (ADR-0012).

Las otras pruebas arman la API sin el ciclo de vida; estas pasan por la fábrica de Uvicorn y por
el arranque con el broker real (Redpanda de `docker-compose.yml`; sin él se saltean).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from uuid import uuid4

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.identity_access import servicio
from trotamundos.servicios.identity_access.servicio import IdentityAccess


def test_la_fabrica_de_uvicorn_arma_la_app():
    """Es lo que corre el contenedor: `uvicorn --factory ...servicio:crear_app`."""
    assert isinstance(servicio.crear_app(), FastAPI)


def test_el_trabajo_periodico_purga_lo_vencido(dsn, esquema, contratos):
    """Bandeja de entrada, claves de idempotencia (ADR-0014) y códigos de invitado vencidos."""
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0.05)
    identity = IdentityAccess(configuracion, esquema=esquema, contratos=contratos)
    identity.crear_esquema()
    vencidas = (
        """INSERT INTO comando_idempotente (usuario_id, clave, operacion, huella, estado, creado_en)
           VALUES (gen_random_uuid(), gen_random_uuid(), 'POST /buzones', 'h', 201,
                   now() - interval '30 days')""",
        """INSERT INTO bandeja_entrada (consumidor, evento_id, recibido_en)
           VALUES ('identity-access', gen_random_uuid(), now() - interval '30 days')""",
        """INSERT INTO codigo_invitado (comparticion_id, correo, codigo_hash, expira_en)
           VALUES (gen_random_uuid(), 'invitada@test.app', 'h', now() - interval '1 minute')""",
    )
    with conectar(dsn, esquema) as conexion:
        for sentencia in vencidas:
            conexion.execute(sentencia)

    def quedan() -> int:
        with conectar(dsn, esquema) as conexion:
            return conexion.execute(
                """SELECT (SELECT count(*) FROM comando_idempotente)
                        + (SELECT count(*) FROM bandeja_entrada)
                        + (SELECT count(*) FROM codigo_invitado) AS n""").fetchone()["n"]

    with TestClient(identity.app()):
        limite = time.monotonic() + 10
        while quedan() and time.monotonic() < limite:
            time.sleep(0.05)
    assert quedan() == 0


def _pendientes(dsn: str, esquema: str) -> int:
    with conectar(dsn, esquema) as conexion:
        return conexion.execute(
            "SELECT count(*) AS n FROM bandeja_salida WHERE publicado_en IS NULL").fetchone()["n"]


async def _leer_uno(servidores: str, nombre: str) -> dict:
    consumidor = AIOKafkaConsumer(nombre, bootstrap_servers=servidores,
                                  auto_offset_reset="earliest", group_id=f"prueba-{uuid4()}")
    await consumidor.start()
    try:
        mensaje = await asyncio.wait_for(consumidor.getone(), 20)
        return json.loads(mensaje.value)
    finally:
        await consumidor.stop()


def test_con_broker_arranca_y_publica_la_outbox(dsn, esquema, contratos, servidores, prefijo):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker=servidores, prefijo_topicos=prefijo)
    identity = IdentityAccess(configuracion, esquema=esquema, contratos=contratos)

    with TestClient(identity.app()) as cliente:  # corre el ciclo de vida: esquema y publicador
        sesion = cliente.post("/sesiones", json={
            "codigo": "oidc:viajero@test.app:AM", "verificadorPkce": "pkce-1234",
            "uriRedireccion": "https://app.trotamundos.app/cb"})
        assert sesion.status_code == 201
        buzon = cliente.post(
            "/buzones", json={"via": "reenvio"},
            headers={"Authorization": f"Bearer {sesion.json()['tokenAcceso']}",
                     "Idempotency-Key": str(uuid4())})
        assert buzon.status_code == 201

        limite = time.monotonic() + 20
        while _pendientes(dsn, esquema) and time.monotonic() < limite:
            time.sleep(0.2)
        assert _pendientes(dsn, esquema) == 0

    carga = asyncio.run(_leer_uno(
        servidores, topico(contratos, "EstadoDeBuzonCambiado", "P2", prefijo)))
    assert carga["buzonId"] == buzon.json()["id"]
    assert carga["estadoNuevo"] == "Activo"
