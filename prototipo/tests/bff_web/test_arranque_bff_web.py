"""`bff-web` arranca por su fábrica de Uvicorn y compone `itinerary-lectura`, `itinerary-escritura`
y `virtual-assistant` (con PostgreSQL y el broker real para `DisrupcionDetectada`)."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import psycopg
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql

from trotamundos.comun.carriles import topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.bff_web import clientes, servicio
from trotamundos.servicios.bff_web.servicio import BffWeb
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.virtual_assistant import acciones, contexto
from trotamundos.servicios.virtual_assistant.servicio import VirtualAssistant

USUARIO = UUID("00000000-0000-4000-8000-0000000000f1")
SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
TIPO = "application/vnd.trotamundos.v1+json"


def test_la_fabrica_de_uvicorn_arma_la_app():
    assert isinstance(servicio.crear_app(), FastAPI)


def _sesion(usuario: UUID = USUARIO) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": str(usuario),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRETO_JWT,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def _enviar(servidores: str, nombre: str, evento: Evento) -> None:
    productor = AIOKafkaProducer(bootstrap_servers=servidores)
    await productor.start()
    try:
        clave, valor, cabeceras = evento.a_kafka()
        await productor.send_and_wait(
            nombre, valor, key=clave, headers=cabeceras
        )
    finally:
        await productor.stop()


def _hasta_que(condicion, limite_s: float = 20) -> None:
    limite = time.monotonic() + limite_s
    while not condicion() and time.monotonic() < limite:
        time.sleep(0.2)
    assert condicion()


def test_recorrido_por_bff_web_con_itinerary_asistente_y_broker(
    dsn, esquema, contratos, servidores, prefijo, observacion
):
    esquema_it = f"{esquema}_it"
    esquema_va = f"{esquema}_va"
    config_it = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker="",
        intervalo_tareas_s=0,
    )
    config_va = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker=servidores,
        prefijo_topicos=prefijo,
        intervalo_tareas_s=0,
    )
    itinerario = Itinerary(
        config_it, esquema=esquema_it, contratos=contratos
    )
    itinerario.crear_esquema()

    with TestClient(itinerario.app()) as http_itinerary:
        asistente = VirtualAssistant(
            config_va,
            esquema=esquema_va,
            contratos=contratos,
            lector=contexto.LectorDeItinerarioHttp(
                "http://itinerary-lectura", cliente=http_itinerary
            ),
            escritor=acciones.EscritorDeItinerarioHttp(
                "http://itinerary-escritura", cliente=http_itinerary
            ),
            secreto_jwt=SECRETO_JWT,
        )
        with TestClient(asistente.app()) as http_asistente:
            bff = BffWeb(
                contratos=contratos,
                lector=clientes.LectorDeItinerarioHttp(
                    "http://itinerary-lectura", cliente=http_itinerary
                ),
                escritor=clientes.EscritorDeItinerarioHttp(
                    "http://itinerary-escritura", cliente=http_itinerary
                ),
                asistente=clientes.ClienteDeAsistenteHttp(
                    "http://virtual-assistant", cliente=http_asistente
                ),
                secreto_jwt=SECRETO_JWT,
            )
            cliente = TestClient(bff.app())

            # 1. Alta manual por bff-web → itinerary-escritura.
            segmento = copy.deepcopy(observacion["segmentos"][0])
            del segmento["versionTipo"]
            alta = {
                "identificadores": observacion["identificadores"],
                "segmentos": [segmento],
            }
            creada = cliente.post(
                "/reservas",
                content=json.dumps(alta),
                headers={
                    **_sesion(),
                    "Idempotency-Key": str(uuid4()),
                    "Content-Type": TIPO,
                },
            )
            assert creada.status_code == 201, creada.text
            version_alta = int(creada.headers["x-version-usuario"])
            reserva_id = creada.json()["reserva"]["id"]
            viaje_id = creada.json()["viajeId"]

            # 2. Lectura del panel con ETag y revalidación 304 (ADR-0019).
            panel = cliente.get(
                "/panel",
                headers={**_sesion(), "X-Min-Version": str(version_alta)},
            )
            assert panel.status_code == 200
            etag = panel.headers["etag"]
            assert (
                cliente.get(
                    "/panel", headers={**_sesion(), "If-None-Match": etag}
                ).status_code
                == 304
            )

            # 3. Disrupción por el broker → consulta al asistente a través de bff-web.
            disrupcion = Evento.nuevo(
                "DisrupcionDetectada",
                {
                    "disrupcionId": "disr-bff-1",
                    "proveedor": "Aerolíneas Argentinas",
                    "severidad": "alta",
                    "descripcion": "Vuelo AR1402 reprogramado por meteorología",
                    "afectados": [
                        {
                            "usuarioId": str(USUARIO),
                            "reservaIds": [reserva_id],
                        }
                    ],
                },
                productor="provider-sync",
                usuario_id=str(USUARIO),
                region="AM",
            )
            asyncio.run(
                _enviar(
                    servidores,
                    topico(contratos, "DisrupcionDetectada", "P1", prefijo),
                    disrupcion,
                )
            )

            def disrupcion_recibida() -> bool:
                with conectar(dsn, esquema_va) as conexion:
                    return (
                        len(
                            conexion.execute(
                                "SELECT 1 FROM disrupcion_conocida"
                            ).fetchall()
                        )
                        == 1
                    )

            _hasta_que(disrupcion_recibida)

            sesion = cliente.post(
                "/asistente/sesiones",
                content=json.dumps({"viajeId": viaje_id}),
                headers={
                    **_sesion(),
                    "Idempotency-Key": str(uuid4()),
                    "Content-Type": TIPO,
                },
            )
            assert sesion.status_code == 201
            sesion_id = sesion.json()["id"]

            respuesta = cliente.post(
                f"/asistente/sesiones/{sesion_id}/mensajes",
                content=json.dumps({"texto": "¿Qué pasa con mi vuelo?"}),
                headers={
                    **_sesion(),
                    "Idempotency-Key": str(uuid4()),
                    "Content-Type": TIPO,
                },
            )
            assert respuesta.status_code == 200
            assert "Vuelo AR1402 reprogramado" in " ".join(
                respuesta.json()["mensajes"]
            )

            # 4. Archivo del viaje por bff-web → 204 con X-Version-Usuario y nuevo ETag del panel.
            archivado = cliente.post(
                f"/viajes/{viaje_id}/archivo", headers=_sesion()
            )
            assert archivado.status_code == 204
            assert int(archivado.headers["x-version-usuario"]) > version_alta
            panel_nuevo = cliente.get(
                "/panel", headers={**_sesion(), "If-None-Match": etag}
            )
            assert panel_nuevo.status_code == 200
            assert panel_nuevo.headers["etag"] != etag
            assert panel_nuevo.json()["viajesActivos"] == []
    with psycopg.connect(dsn, autocommit=True) as conexion:
        for s in (esquema_it, esquema_va):
            conexion.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(s)
                )
            )
