"""El elemento `preferences` (RF-15, iteración 2 §5.6): arma los módulos y define las transacciones.

Cada cambio de preferencias se guarda y publica `PreferenciasActualizadas` en la misma transacción
(*outbox*, ADR-0012). Los consumidores (`notification`, `support-liaison`, `itinerary`) guardan una
copia local, así que nadie llama a este servicio durante un pico (QA-04). Con un *broker*
configurado, publica la *outbox*.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import UUID

from fastapi import FastAPI

from trotamundos.comun.carriles import asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    bloquear_usuario,
    borrar_usuario,
    crear_esquema,
    purgar,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.preferences import almacen, api, publicacion

ESQUEMA = "preferences"
PRODUCTOR = "preferences"
PAUSA_S = 0.5
DDL = (*almacen.DDL,)

_registro_de_errores = logging.getLogger(__name__)


class Preferences:
    """Las operaciones de `preferences`, cada una en su transacción."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, secreto_jwt: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- preferencias ----------------------------------------------------------------------

    def leer(self, usuario_id: UUID) -> dict[str, Any]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return almacen.leer(conexion, usuario_id, self._configuracion.region)

    def guardar(self, usuario_id: UUID, preferencias: Mapping[str, Any]) -> dict[str, Any]:
        """`PUT /preferencias`: guarda y, si cambiaron, publica `PreferenciasActualizadas` en la
        misma transacción."""
        completas = almacen.completar(preferencias, self._configuracion.region)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            if almacen.guardar(conexion, usuario_id, completas, self._reloj()):
                publicacion.registrar(conexion, [Evento.nuevo(
                    "PreferenciasActualizadas", {"preferencias": completas}, productor=PRODUCTOR,
                    usuario_id=str(usuario_id), region=completas["region"])], self._contratos)
        return completas

    def suprimir_usuario(self, usuario_id: UUID) -> int:
        """Orden de borrado de la fase 1 (ADR-0030, ADR-0042)."""
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            return borrar_usuario(conexion, usuario_id)

    def tareas_periodicas(self) -> None:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            purgar(conexion, self._reloj())

    # --- API y broker --------------------------------------------------------------------

    def app(self) -> FastAPI:
        intervalo = self._configuracion.intervalo_tareas_s

        @asynccontextmanager
        async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            tareas = [asyncio.create_task(self._bucle(intervalo))] if intervalo > 0 else []
            try:
                async with self.con_broker():
                    yield
            finally:
                for tarea in tareas:
                    tarea.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await tarea

        return api.crear_app(self, self._contratos, self._secreto_jwt, lifespan=ciclo_de_vida)

    def topicos(self) -> list[str]:
        prefijo = self._configuracion.prefijo_topicos
        return [topico(self._contratos, tipo, carril, prefijo) for tipo in sorted(publicacion.PUBLICA)
                for carril in carriles_posibles(self._contratos, tipo)]

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        c = self._configuracion
        if not c.broker:
            yield []
            return
        await asegurar_topicos(c.broker, self.topicos())
        publicador = PublicadorDeOutbox(c.dsn_postgres, self._esquema, c.broker, self._contratos,
                                        c.prefijo_topicos)
        await publicador.iniciar()
        detener = asyncio.Event()
        tarea = asyncio.create_task(self._publicar_siempre(publicador, detener))
        try:
            yield [tarea]
        finally:
            detener.set()
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea
            await publicador.detener()

    async def _publicar_siempre(self, publicador: PublicadorDeOutbox,
                                detener: asyncio.Event) -> None:
        while not detener.is_set():
            try:
                if await publicador.publicar_pendientes() == 0:
                    await asyncio.sleep(PAUSA_S)
            except Exception:  # el broker o la base no responden: se reintenta
                _registro_de_errores.exception("Falló la publicación de la outbox de preferences")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de preferences")


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.preferences.servicio:crear_app`."""
    return Preferences().app()
