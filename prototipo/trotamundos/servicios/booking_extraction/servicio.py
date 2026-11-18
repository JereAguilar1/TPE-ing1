"""Armado de booking-extraction (vista N2 §2): inbox, extracción y outbox atómicas.

Solo los identificadores del correo se guardan para deduplicar. El cuerpo no se persiste ni en
los resultados ni en los rechazos del consumidor (ADR-0035). La infraestructura de correo que
entrega el evento conserva su propia política de retención.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import threading
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RETENCION, bloquear_usuario, crear_esquema, purgar, registrar_en_bandeja_de_entrada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.booking_extraction import publicacion
from trotamundos.servicios.booking_extraction.registro_de_extractores import MotorExtraccion

ESQUEMA = "booking_extraction"
PRODUCTOR = "booking-extraction"
CONSUME = frozenset({"MensajeDeViajeRecibido"})
PAUSA_S = 0.5
DDL = (*DDL_RECHAZADOS, """
    CREATE TABLE IF NOT EXISTS mensaje_procesado (
        buzon_id uuid NOT NULL,
        id_de_mensaje text NOT NULL,
        usuario_id uuid NOT NULL,
        recibido_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (buzon_id, id_de_mensaje)
    );
""")
_registro = logging.getLogger(__name__)


class BookingExtraction:
    """El servicio no conserva referencias a los cuerpos después de atender cada evento."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, motor: MotorExtraccion | None = None):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self.motor = motor or MotorExtraccion(self._contratos)
        # La calidad es local a la réplica. Un rollback no debe contar dos veces un reintento.
        self._cerrojo = threading.Lock()

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    def consumir(self, evento: Evento) -> None:
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, ["booking-extraction no consume ese evento"])
        evento.validar(self._contratos)
        with self._cerrojo:
            calidad_anterior = copy.deepcopy(self.motor.calidad)
            try:
                with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
                    bloquear_usuario(conexion, evento.sobre["usuarioId"])
                    if not registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                        return
                    nuevo = conexion.execute(
                        """INSERT INTO mensaje_procesado (buzon_id, id_de_mensaje, usuario_id)
                           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING buzon_id""",
                        (evento.carga["buzonId"], evento.carga["idDeMensaje"],
                         evento.sobre["usuarioId"])).fetchone()
                    if nuevo is None:
                        return
                    resultados = self.motor.procesar(evento.carga)
                    salidas = [Evento.nuevo(
                        tipo, carga, productor=PRODUCTOR, usuario_id=evento.sobre["usuarioId"],
                        region=evento.sobre.get("regionOrigen"), id_de_causa=evento.id,
                        traceparent=evento.sobre.get("traceparent"),
                        id_de_correlacion=evento.sobre.get("idDeCorrelacion"))
                        for tipo, carga in resultados]
                    publicacion.registrar(conexion, salidas, self._contratos)
            except Exception:
                self.motor.calidad = calidad_anterior
                raise

    def tareas_periodicas(self) -> None:
        ahora = datetime.now(timezone.utc)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            purgar(conexion, ahora)
            conexion.execute("DELETE FROM mensaje_procesado WHERE recibido_en < %s",
                             (ahora - RETENCION,))

    def app(self) -> FastAPI:
        @contextlib.asynccontextmanager
        async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            tareas = []
            if self._configuracion.intervalo_tareas_s > 0:
                tareas.append(asyncio.create_task(self._bucle()))
            try:
                async with self.con_broker():
                    yield
            finally:
                for tarea in tareas:
                    tarea.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await tarea

        app = FastAPI(title="booking-extraction", lifespan=ciclo_de_vida,
                      openapi_url=None, docs_url=None, redoc_url=None)
        app.state.servicio = self
        return app

    def topicos(self) -> tuple[list[str], dict[Carril, list[str]]]:
        prefijo = self._configuracion.prefijo_topicos
        publica = [topico(self._contratos, tipo, carril, prefijo)
                   for tipo in sorted(publicacion.PUBLICA)
                   for carril in carriles_posibles(self._contratos, tipo)]
        consume: dict[Carril, list[str]] = {}
        for tipo in sorted(CONSUME):
            for carril in carriles_posibles(self._contratos, tipo):
                consume.setdefault(carril, []).append(topico(self._contratos, tipo, carril, prefijo))
        return publica, consume

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        c = self._configuracion
        if not c.broker:
            yield []
            return
        publica, consume = self.topicos()
        await asegurar_topicos(c.broker, publica + [t for ts in consume.values() for t in ts])
        publicador = PublicadorDeOutbox(c.dsn_postgres, self._esquema, c.broker, self._contratos,
                                       c.prefijo_topicos)
        consumidor = ConsumidorConCarriles(
            c.broker, PRODUCTOR, consume, self.consumir, c.dsn_postgres, self._esquema,
            conservar_contenido_rechazado=False)
        detener = asyncio.Event()
        tareas = []
        try:
            await publicador.iniciar()
            await consumidor.iniciar()
            tareas = [asyncio.create_task(self._publicar_siempre(publicador, detener)),
                      asyncio.create_task(consumidor.correr(detener))]
            yield tareas
        finally:
            detener.set()
            for tarea in tareas:
                tarea.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarea
            await consumidor.detener()
            await publicador.detener()

    async def _publicar_siempre(self, publicador: PublicadorDeOutbox,
                               detener: asyncio.Event) -> None:
        while not detener.is_set():
            try:
                if await publicador.publicar_pendientes() == 0:
                    await asyncio.sleep(PAUSA_S)
            except Exception:
                # No adjuntar errores o datos del correo al log (ADR-0035).
                _registro.warning("No se pudo publicar la outbox; se reintentará")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self) -> None:
        while True:
            await asyncio.sleep(self._configuracion.intervalo_tareas_s)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:
                _registro.warning("No se pudo purgar la deduplicación; se reintentará")


def crear_app() -> FastAPI:
    """Fábrica de Uvicorn, con la misma configuración que el despliegue de Compose."""
    return BookingExtraction().app()
