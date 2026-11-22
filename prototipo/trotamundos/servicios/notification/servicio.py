"""El elemento `notification` (RF-10, iteración 2 §5.7): arma los módulos y define las transacciones.

Consume los eventos que pueden merecer un aviso y `PreferenciasActualizadas` (copia local). Cada
evento se procesa en una transacción con su bandeja de entrada (ADR-0014): se clasifica
(`reglas`), se guarda en la bandeja interna aplicando correlación y coalescencia (`avisos`) y, por
cada aviso que sale, se publica `NotificacionEmitida` en la *outbox* (ADR-0012). Después de
confirmar, se entrega por push o correo con el complemento de canales. No expone operaciones: no
hay contrato OpenAPI para `notification`, y la aplicación solo sirve para el *healthcheck*.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.errores import instalar_manejadores
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    bloquear_usuario,
    crear_esquema,
    purgar,
    registrar_en_bandeja_de_entrada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, registro_por_omision
from trotamundos.servicios.notification import avisos, preferencias, publicacion, reglas
from trotamundos.servicios.notification.canales import EXTERNOS, CanalesExternos
from trotamundos.servicios.notification.complementos.canales_simulados import CanalesSimulados

ESQUEMA = "notification"
PRODUCTOR = "notification"
CONSUME = frozenset({
    "ReservaActualizada", "ReservaCancelada", "ConflictoDeFuentesDetectado", "ViajeCompletado",
    "DisrupcionDetectada", "EstadoDeBuzonCambiado", "ExtraccionNoReconocida", "CasoDerivado",
    "PreferenciasActualizadas"})
PAUSA_S = 0.5

DDL = (*avisos.DDL, *preferencias.DDL, *DDL_RECHAZADOS)

_registro_de_errores = logging.getLogger(__name__)


class Notification:
    """Las operaciones de `notification`, cada una en su transacción."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, registro: RegistroDeTipos | None = None,
                 canales_externos: CanalesExternos | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._registro = registro or registro_por_omision()
        self.canales_externos = canales_externos or CanalesSimulados()
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- consumo -------------------------------------------------------------------------

    def consumir(self, evento: Evento) -> None:
        """Lanza `ErrorDeContrato` si el evento no cumple el contrato, sin dejar nada escrito."""
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"notification no consume {evento.tipo}"])
        evento.validar(self._contratos)
        ahora = self._reloj()
        if evento.tipo == "PreferenciasActualizadas":
            usuario_id = evento.sobre["usuarioId"]
            with self._transaccion([usuario_id]) as conexion:
                if registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                    preferencias.aplicar(conexion, usuario_id, evento.carga["preferencias"],
                                         datetime.fromisoformat(
                                             evento.sobre["ocurridoEn"].replace("Z", "+00:00")))
            return
        nuevos = reglas.avisos_de(evento, self._registro)
        usuarios = {evento.sobre["usuarioId"], *(a.usuario_id for a in nuevos)}
        emitidos = []
        with self._transaccion(usuarios) as conexion:
            if registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                for aviso in nuevos:
                    emitido = avisos.registrar(conexion, aviso,
                                               preferencias.de_usuario(conexion, aviso.usuario_id),
                                               ahora)
                    if emitido is not None:
                        emitidos.append(emitido)
                self._publicar(conexion, emitidos)
        self._entregar(emitidos)

    # --- trabajo periódico ---------------------------------------------------------------

    def emitir_agrupados(self) -> int:
        """Emite los avisos agrupados cuya ventana de coalescencia se cerró."""
        with self._lectura() as conexion:
            emitidos = avisos.emitir_vencidos(conexion, self._reloj(), preferencias.de_usuario)
            self._publicar(conexion, emitidos)
        self._entregar(emitidos)
        return len(emitidos)

    def tareas_periodicas(self) -> None:
        self.emitir_agrupados()
        with self._lectura() as conexion:
            purgar(conexion, self._reloj())

    def bandeja(self, usuario_id: str) -> list[dict[str, Any]]:
        """El canal interno del usuario (para las pruebas y la demostración)."""
        with self._lectura() as conexion:
            return avisos.de_usuario(conexion, usuario_id)

    def _publicar(self, conexion: Any, emitidos: list[avisos.Emitido]) -> None:
        eventos = []
        for emitido in emitidos:
            carga: dict[str, Any] = {"notificacionId": emitido.aviso_id,
                                     "severidad": emitido.severidad,
                                     "canales": list(emitido.canales),
                                     "eventosAgrupados": emitido.eventos_agrupados}
            if emitido.viaje_id:
                carga["viajeId"] = emitido.viaje_id
            eventos.append(Evento.nuevo("NotificacionEmitida", carga, productor=PRODUCTOR,
                                        usuario_id=emitido.usuario_id,
                                        region=self._configuracion.region,
                                        id_de_causa=emitido.id_de_causa))
        if eventos:
            publicacion.registrar(conexion, eventos, self._contratos)

    def _entregar(self, emitidos: list[avisos.Emitido]) -> None:
        """Push y correo, después de confirmar la transacción. Un canal que falla no frena a los
        demás: el aviso ya está en el canal interno."""
        for emitido in emitidos:
            contenido = {"avisoId": emitido.aviso_id, "severidad": emitido.severidad,
                         "motivo": emitido.motivo, "viajeId": emitido.viaje_id,
                         "eventosAgrupados": emitido.eventos_agrupados}
            for canal in emitido.canales:
                if canal not in EXTERNOS:
                    continue
                try:
                    self.canales_externos.enviar(canal, emitido.usuario_id, contenido)
                except Exception:  # el canal externo no responde: queda el interno
                    _registro_de_errores.exception("No se pudo entregar el aviso por %s", canal)

    # --- API y broker --------------------------------------------------------------------

    def app(self) -> FastAPI:
        """Sin operaciones: al arrancar crea el esquema, corre el trabajo periódico cada
        `intervalo_tareas_s` (0 lo apaga) y, con broker, consume y publica."""
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

        app = FastAPI(title="notification", openapi_url=None, docs_url=None, redoc_url=None,
                      lifespan=ciclo_de_vida)
        instalar_manejadores(app)
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
        consumidor = ConsumidorConCarriles(c.broker, PRODUCTOR, consume, self.consumir,
                                           c.dsn_postgres, self._esquema)
        await publicador.iniciar()
        await consumidor.iniciar()
        detener = asyncio.Event()
        tareas = [asyncio.create_task(self._publicar_siempre(publicador, detener)),
                  asyncio.create_task(consumidor.correr(detener))]
        try:
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
            except Exception:  # el broker o la base no responden: se reintenta
                _registro_de_errores.exception("Falló la publicación de la outbox de notification")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de notification")

    # --- transacciones -------------------------------------------------------------------

    @contextlib.contextmanager
    def _transaccion(self, usuarios: Any):
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            for usuario_id in sorted(str(u) for u in usuarios):  # siempre en el mismo orden
                bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.notification.servicio:crear_app`."""
    return Notification().app()
