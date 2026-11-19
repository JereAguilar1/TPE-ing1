"""Armado de `event-pipeline` y del almacén analítico `analytics_store` (paso 14, ADR-0003, ADR-0016, ADR-0030, QA-09).

Consume los eventos de dominio desde el *broker* y escribe únicamente en el esquema analítico
separado (`analytics_store`), sin importar ni invocar a ningún servicio del plano operacional
(regla R6 de la vista de módulos N1).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
import logging
from typing import Any, AsyncIterator

from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    bloquear_usuario,
    crear_esquema,
    purgar,
    registrar_en_bandeja_de_entrada,
    transaccion,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.event_pipeline import aterrizaje, modelo_dimensional

ESQUEMA = "analytics_store"
CONSUMIDOR = "event-pipeline"
CONSUME = frozenset({
    "ReservaActualizada",
    "ReservaCancelada",
    "ConflictoDeFuentesDetectado",
    "ViajeArmado",
    "ViajeCompletado",
    "ViajeArchivado",
    "CasoDerivado",
    "NotificacionEmitida",
    "CuentaSuprimida",
})
DDL = (*aterrizaje.DDL, *DDL_RECHAZADOS)

_registro = logging.getLogger(__name__)


class EventPipeline:
    """Consumidor de eventos hacia el plano analítico separado (`analytics_store`)."""

    def __init__(self, configuracion: Configuracion | None = None, *,
                 esquema: str = ESQUEMA,
                 contratos: Contratos | None = None,
                 tipos: RegistroDeTipos | None = None):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self.tipos = tipos or RegistroDeTipos.desde_contratos(self._contratos)

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            modelo_dimensional.instalar_modelo_dimensional(
                conexion, self._contratos, self.tipos
            )

    def sincronizar_tipos(self, tipos: RegistroDeTipos | None = None) -> int:
        if tipos is not None:
            self.tipos = tipos
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return modelo_dimensional.sincronizar_tipos_de_segmento(conexion, self.tipos)

    def consumir(self, evento: Evento) -> None:
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"event-pipeline no consume {evento.tipo}"])
        evento.validar(self._contratos)
        clave_bloqueo = evento.sobre.get("usuarioId") or evento.clave_de_particion
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, clave_bloqueo)
            if not registrar_en_bandeja_de_entrada(conexion, CONSUMIDOR, evento):
                return
            crudo = aterrizaje.registrar_crudo(conexion, evento)
            modelo_dimensional.proyectar_evento(conexion, crudo, self.tipos)

    def reconstruir(self) -> int:
        """Regenera los hechos y dimensiones desde `evento_crudo` (confirmación de ADR-0016)."""
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            crudos = aterrizaje.listar_crudos(conexion)
            modelo_dimensional.reconstruir_desde_crudos(conexion, crudos, self.tipos)
            return len(crudos)

    def consultar_tendencias(self) -> list[dict[str, Any]]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return modelo_dimensional.consultar_tendencias(conexion)

    def consultar_destinos(self) -> list[dict[str, Any]]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return modelo_dimensional.consultar_destinos(conexion)

    def consultar_cancelaciones(self) -> list[dict[str, Any]]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return modelo_dimensional.consultar_cancelaciones(conexion)

    def tareas_periodicas(self) -> None:
        ahora = datetime.now(timezone.utc)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            purgar(conexion, ahora)

    def app(self) -> FastAPI:
        intervalo = self._configuracion.intervalo_tareas_s

        @contextlib.asynccontextmanager
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

        app = FastAPI(
            title="event-pipeline",
            lifespan=ciclo_de_vida,
            openapi_url=None,
            docs_url=None,
            redoc_url=None,
        )
        app.state.servicio = self
        return app

    def topicos(self) -> dict[Carril, list[str]]:
        prefijo = self._configuracion.prefijo_topicos
        consume: dict[Carril, list[str]] = {}
        for tipo in sorted(CONSUME):
            for carril in carriles_posibles(self._contratos, tipo):
                consume.setdefault(carril, []).append(
                    topico(self._contratos, tipo, carril, prefijo)
                )
        return consume

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        c = self._configuracion
        if not c.broker:
            yield []
            return
        consume = self.topicos()
        await asegurar_topicos(c.broker, [t for ts in consume.values() for t in ts])
        consumidor = ConsumidorConCarriles(
            c.broker, CONSUMIDOR, consume, self.consumir, c.dsn_postgres, self._esquema
        )
        detener = asyncio.Event()
        tareas: list[asyncio.Task] = []
        try:
            await consumidor.iniciar()
            tareas = [asyncio.create_task(consumidor.correr(detener))]
            yield tareas
        finally:
            detener.set()
            for tarea in tareas:
                tarea.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarea
            await consumidor.detener()

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:
                _registro.warning("Falló el trabajo periódico de event-pipeline; se reintentará")


def crear_app() -> FastAPI:
    """Fábrica de Uvicorn: `uvicorn --factory trotamundos.servicios.event_pipeline.servicio:crear_app`."""
    return EventPipeline().app()
