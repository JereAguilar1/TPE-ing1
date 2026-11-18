"""El elemento `support-liaison`: arma los módulos y define las transacciones (UC-7).

Abrir un caso:

1. sin agencia preferida (la copia local que alimenta `PreferenciasActualizadas`), `422`;
2. toma la instantánea del viaje de `itinerary-lectura`, en nombre del viajero;
3. crea el caso `Abierto`, idempotente por `Idempotency-Key`;
4. lo deriva por el complemento de la agencia: con el acuse pasa a `Derivado` y publica
   `CasoDerivado`; si la agencia no responde, sigue `Abierto` y se reintenta (ADR-0024).

Con un *broker* configurado también consume `PreferenciasActualizadas` y publica la *outbox*.
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
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    crear_esquema,
    guardar_respuesta,
    huella_de_solicitud,
    purgar,
    registrar_en_bandeja_de_entrada,
    respuesta_guardada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.support_liaison import (
    api,
    casos,
    instantanea,
    preferencias,
    publicacion,
)
from trotamundos.servicios.support_liaison.complementos.agencia_simulada import AgenciaSimulada
from trotamundos.servicios.support_liaison.interfaz_de_agencia import (
    AdaptadorDeAgencia,
    AgenciaNoDisponible,
)

ESQUEMA = "support_liaison"
PRODUCTOR = "support-liaison"
CONSUME = frozenset({"PreferenciasActualizadas"})
OPERACION = "POST /casos"
PAUSA_S = 0.5
SIN_AGENCIA = ("No tenés una agencia preferida configurada. Elegila en tus preferencias "
               "(PUT /preferencias) y volvé a pedir ayuda.")

DDL = (*casos.DDL, *preferencias.DDL, *DDL_RECHAZADOS)

_registro_de_errores = logging.getLogger(__name__)


class SupportLiaison:
    """Las operaciones de `support-liaison`, cada una en sus transacciones."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None,
                 lector_de_viajes: instantanea.LectorDeViajes | None = None,
                 adaptador: AdaptadorDeAgencia | None = None,
                 secreto_jwt: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 nuevo_id: Callable[[], UUID] = uuid4):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._lector = lector_de_viajes or instantanea.LectorDeViajesHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_LECTURA", "http://localhost:18102"))
        self.adaptador = adaptador or AgenciaSimulada()
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._reloj = reloj
        self._nuevo_id = nuevo_id

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- PreferenciasActualizadas ----------------------------------------------------------

    def consumir(self, evento: Evento) -> None:
        """Lanza `ErrorDeContrato` si el evento no cumple el contrato, sin dejar nada escrito."""
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"support-liaison no consume {evento.tipo}"])
        evento.validar(self._contratos)
        usuario_id = evento.sobre["usuarioId"]
        with self._transaccion(usuario_id) as conexion:
            if registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                preferencias.aplicar(conexion, usuario_id, evento.carga["preferencias"],
                                     self._reloj())

    # --- casos ---------------------------------------------------------------------------

    def abrir_caso(self, usuario_id: UUID, clave: UUID,
                   cuerpo: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        """`POST /casos`. La misma `Idempotency-Key` con la misma solicitud devuelve el mismo caso
        (en su estado actual); con otra solicitud, `400`."""
        huella = huella_de_solicitud(cuerpo)
        with self._transaccion(usuario_id) as conexion:
            repetido = self._caso_ya_abierto(conexion, usuario_id, clave, huella)
            if repetido is not None:
                return 201, repetido
            agencia = preferencias.de_usuario(conexion, usuario_id)
        if agencia is None:
            raise Problema(422, "Sin agencia preferida", SIN_AGENCIA)

        viaje_id = UUID(str(cuerpo["viajeId"]))
        reserva_id = UUID(str(cuerpo["reservaId"])) if "reservaId" in cuerpo else None
        viaje = self._lector.viaje(usuario_id, viaje_id)
        if viaje is None or (reserva_id is not None and str(reserva_id) not in
                             {r["id"] for r in viaje.get("reservas", [])}):
            raise no_encontrado()

        with self._transaccion(usuario_id) as conexion:
            repetido = self._caso_ya_abierto(conexion, usuario_id, clave, huella)
            if repetido is not None:  # otro pedido con la misma clave ganó la carrera
                return 201, repetido
            fila = casos.abrir(
                conexion, usuario_id=usuario_id, caso_id=self._nuevo_id(), viaje_id=viaje_id,
                reserva_id=reserva_id, motivo=cuerpo["motivo"], descripcion=cuerpo.get("descripcion"),
                id_de_causa=cuerpo.get("idDeCausa"), agencia_id=agencia.id,
                agencia_nombre=agencia.nombre, instantanea=viaje, ahora=self._reloj())
            guardar_respuesta(conexion, usuario_id, clave, RespuestaGuardada(
                OPERACION, huella, 201, casos.a_dict(fila)))
        return 201, casos.a_dict(self._derivar(usuario_id, fila["caso_id"]))

    def leer_caso(self, usuario_id: UUID, caso_id: UUID) -> dict[str, Any]:
        with self._lectura() as conexion:
            fila = casos.obtener(conexion, usuario_id, caso_id)
        if fila is None:
            raise no_encontrado()
        return casos.a_dict(fila)

    def resolver_caso(self, usuario_id: UUID, caso_id: UUID) -> dict[str, Any]:
        with self._transaccion(usuario_id) as conexion:
            try:
                fila = casos.resolver(conexion, usuario_id, caso_id, self._reloj())
            except casos.CasoNoResoluble as error:
                raise Problema(409, "Conflicto", f"El caso ya está {error}") from error
        if fila is None:
            raise no_encontrado()
        return casos.a_dict(fila)

    def _caso_ya_abierto(self, conexion: psycopg.Connection, usuario_id: UUID, clave: UUID,
                         huella: str) -> dict[str, Any] | None:
        previa = respuesta_guardada(conexion, usuario_id, clave)
        if previa is None:
            return None
        if (previa.operacion, previa.huella) != (OPERACION, huella):
            raise Problema(400, "Solicitud inválida",
                           "La Idempotency-Key ya se usó con otra solicitud")
        fila = casos.obtener(conexion, usuario_id, previa.cuerpo["id"])
        return casos.a_dict(fila) if fila else previa.cuerpo

    def _derivar(self, usuario_id: UUID | str, caso_id: UUID | str) -> dict[str, Any]:
        """Un intento de derivación, en su transacción. Con el acuse de la agencia, `Derivado` y
        `CasoDerivado` en la *outbox*; si no responde, queda `Abierto` con su próximo intento."""
        with self._transaccion(usuario_id) as conexion:
            fila = casos.obtener(conexion, usuario_id, caso_id)
            if fila is None or fila["estado"] != "Abierto":
                return fila
            ahora = self._reloj()
            try:
                referencia = self.adaptador.derivar(fila["agencia_id"], casos.para_la_agencia(fila))
            except AgenciaNoDisponible:
                _registro_de_errores.warning("La agencia %s no acusó recibo del caso %s",
                                             fila["agencia_id"], caso_id)
                return casos.postergar(conexion, fila, ahora)
            fila = casos.marcar_derivado(conexion, fila, referencia, ahora)
            publicacion.registrar(conexion, [Evento.nuevo(
                "CasoDerivado",
                {"casoId": str(fila["caso_id"]), "viajeId": str(fila["viaje_id"]),
                 "agencia": fila["agencia_nombre"], "motivo": fila["motivo"]},
                productor=PRODUCTOR, usuario_id=str(usuario_id),
                region=self._configuracion.region, id_de_causa=fila["id_de_causa"])],
                self._contratos)
            return fila

    # --- trabajo periódico ---------------------------------------------------------------

    def tareas_periodicas(self) -> None:
        """Reintenta las derivaciones pendientes y purga lo vencido."""
        ahora = self._reloj()
        with self._lectura() as conexion:
            pendientes = casos.por_derivar(conexion, ahora)
        for pendiente in pendientes:
            self._derivar(pendiente["usuario_id"], pendiente["caso_id"])
        with self._lectura() as conexion:
            purgar(conexion, ahora)

    # --- API y broker --------------------------------------------------------------------

    def app(self) -> FastAPI:
        """La API de `support-liaison`. Al arrancar crea el esquema; corre el trabajo periódico
        cada `intervalo_tareas_s` (0 lo apaga) y, con broker, consume y publica."""
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
        # Referencias propias: el bucle de eventos solo guarda referencias débiles a las tareas.
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
                _registro_de_errores.exception("Falló la publicación de la outbox de support-liaison")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de support-liaison")

    # --- transacciones -------------------------------------------------------------------

    @contextlib.contextmanager
    def _transaccion(self, usuario_id: UUID | str):
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.support_liaison.servicio:crear_app`."""
    return SupportLiaison().app()
