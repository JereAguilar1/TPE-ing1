"""El elemento `virtual-assistant` (nº 14, Opción B): arma los módulos y define las transacciones.

Un turno se atiende en tres tiempos, para no tener una transacción abierta mientras se llama a otros
servicios:

1. en una transacción, devuelve la respuesta guardada si la `Idempotency-Key` ya se usó, lee la
   sesión (una ajena es `404`) y, si el mensaje confirma la acción pendiente, la **reclama**: otra
   confirmación simultánea de la misma acción ya no la encuentra (`409`);
2. `dialogo` atiende el turno, con las llamadas a `itinerary` y `support-liaison`;
3. en otra transacción guarda los turnos, el estado de la sesión y la respuesta.

Con un *broker* configurado consume `DisrupcionDetectada` (carril P1, bandeja de entrada). No publica
eventos.
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

from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RETENCION,
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
from trotamundos.servicios.virtual_assistant import (
    acciones,
    api,
    contexto,
    derivacion,
    dialogo,
    sesiones,
)
from trotamundos.servicios.virtual_assistant.catalogo import IDIOMA_POR_OMISION, Mensajes
from trotamundos.servicios.virtual_assistant.interprete import (
    InterpreteDeIntenciones,
    InterpretePorReglas,
)

ESQUEMA = "virtual_assistant"
CONSUMIDOR = "virtual-assistant"
CONSUME = frozenset({"DisrupcionDetectada"})
ABRIR = "POST /asistente/sesiones"
MENSAJE = "POST /asistente/sesiones/{sid}/mensajes"

DDL = (*sesiones.DDL, *contexto.DDL, *DDL_RECHAZADOS)

_registro_de_errores = logging.getLogger(__name__)


class VirtualAssistant:
    """Las operaciones del asistente, cada una en sus transacciones."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None,
                 lector: contexto.LectorDeItinerario | None = None,
                 escritor: acciones.EscritorDeItinerario | None = None,
                 abridor: derivacion.AbridorDeCasos | None = None,
                 interprete: InterpreteDeIntenciones | None = None,
                 secreto_jwt: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 nuevo_id: Callable[[], UUID] = uuid4):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._lector = lector or contexto.LectorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_LECTURA", "http://localhost:18102"))
        escritor = escritor or acciones.EscritorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_ESCRITURA", "http://localhost:18101"))
        abridor = abridor or derivacion.AbridorDeCasosHttp(
            os.environ.get("TROTAMUNDOS_URL_SUPPORT_LIAISON", "http://localhost:18105"))
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._reloj = reloj
        self._nuevo_id = nuevo_id
        # El prototipo trae solo los catálogos en español (ADR-0037).
        self._mensajes = Mensajes(IDIOMA_POR_OMISION)
        self._dialogo = dialogo.Dialogo(interprete or InterpretePorReglas(IDIOMA_POR_OMISION),
                                        self._lector, escritor, abridor, self._disrupcion,
                                        self._mensajes, nuevo_id)

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- DisrupcionDetectada ---------------------------------------------------------------

    def consumir(self, evento: Evento) -> None:
        """Lanza `ErrorDeContrato` si el evento no cumple el contrato, sin dejar nada escrito."""
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"virtual-assistant no consume {evento.tipo}"])
        evento.validar(self._contratos)
        with self._transaccion(evento.sobre["usuarioId"]) as conexion:
            if registrar_en_bandeja_de_entrada(conexion, CONSUMIDOR, evento):
                contexto.registrar_disrupcion(conexion, evento.carga, self._reloj())

    def _disrupcion(self, usuario_id: str, reserva_id: str) -> Mapping[str, Any] | None:
        with self._lectura() as conexion:
            return contexto.disrupcion_de(conexion, usuario_id, reserva_id)

    # --- sesiones --------------------------------------------------------------------------

    def abrir_sesion(self, usuario_id: UUID, clave: UUID,
                     cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        """`POST /asistente/sesiones`: la sesión, con el saludo del asistente."""
        huella = huella_de_solicitud(cuerpo)
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, ABRIR, huella)
            if previa is not None:
                return previa
        viaje_id = cuerpo.get("viajeId")
        if viaje_id is not None:
            try:
                if self._lector.viaje(usuario_id, viaje_id) is None:
                    raise no_encontrado()
            except contexto.ItinerarioNoDisponible:
                pass  # cada lectura va en nombre del viajero: un viaje ajeno no se ve igual
        ahora = self._reloj()
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, ABRIR, huella)
            if previa is not None:  # otro pedido con la misma clave ganó la carrera
                return previa
            sesion_id = self._nuevo_id()
            fila = sesiones.abrir(conexion, usuario_id, sesion_id, self._mensajes.idioma,
                                  viaje_id, ahora)
            sesiones.agregar_turno(conexion, usuario_id, sesion_id, "asistente",
                                   self._mensajes.texto("saludo"), "saludo", ahora)
            respuesta = sesiones.a_dict(fila, sesiones.turnos(conexion, usuario_id, sesion_id),
                                        ahora)
            guardar_respuesta(conexion, usuario_id, clave,
                              RespuestaGuardada(ABRIR, huella, 201, respuesta))
        return respuesta

    def ver_sesion(self, usuario_id: UUID, sesion_id: UUID) -> dict[str, Any]:
        with self._lectura() as conexion:
            fila = sesiones.obtener(conexion, usuario_id, sesion_id)
            if fila is None:
                raise no_encontrado()
            return sesiones.a_dict(fila, sesiones.turnos(conexion, usuario_id, sesion_id),
                                   self._reloj())

    def enviar_mensaje(self, usuario_id: UUID, authorization: str, sesion_id: UUID, clave: UUID,
                       cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        """`POST /asistente/sesiones/{sid}/mensajes`: la `Respuesta` del asistente a ese turno."""
        huella = huella_de_solicitud({"sesion": str(sesion_id), **cuerpo})
        ahora = self._reloj()
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, MENSAJE, huella)
            if previa is not None:
                return previa
            fila = sesiones.obtener(conexion, usuario_id, sesion_id)
            if fila is None:
                raise no_encontrado()
            estado = dialogo.EstadoDeSesion(
                viaje_id=str(fila["viaje_id"]) if fila["viaje_id"] else None,
                no_entendidos=fila["no_entendidos"], accion=fila["accion"],
                turnos=sesiones.turnos(conexion, usuario_id, sesion_id))
            reclamada = self._reclamar(conexion, usuario_id, sesion_id, fila, cuerpo, ahora)
        try:
            resultado = self._dialogo.atender(usuario_id, authorization, estado, cuerpo, ahora)
        except dialogo.ViajeAjeno as error:
            self._devolver(usuario_id, sesion_id, reclamada)
            raise no_encontrado() from error
        except Exception:
            self._devolver(usuario_id, sesion_id, reclamada)
            raise
        respuesta = resultado.respuesta
        with self._transaccion(usuario_id) as conexion:
            previa = self._previa(conexion, usuario_id, clave, MENSAJE, huella)
            if previa is not None:
                return previa
            intencion = respuesta["intencion"]
            sesiones.agregar_turno(conexion, usuario_id, sesion_id, "viajero",
                                   resultado.texto_del_viajero, intencion, ahora)
            for texto in respuesta["mensajes"]:
                sesiones.agregar_turno(conexion, usuario_id, sesion_id, "asistente", texto,
                                       intencion, ahora)
            realizada = respuesta.get("accionRealizada")
            if reclamada is not None and realizada is not None and realizada.get("casoId") \
                    and reclamada["datos"].get("idDeCausa"):
                contexto.marcar_derivada(conexion, usuario_id, reclamada["datos"]["idDeCausa"],
                                         realizada["casoId"])
            nuevo = resultado.estado
            sesiones.actualizar(conexion, usuario_id, sesion_id, viaje_id=nuevo.viaje_id,
                                no_entendidos=nuevo.no_entendidos, accion=nuevo.accion, ahora=ahora)
            guardar_respuesta(conexion, usuario_id, clave,
                              RespuestaGuardada(MENSAJE, huella, 200, respuesta))
        return respuesta

    def _reclamar(self, conexion, usuario_id: UUID, sesion_id: UUID, fila: Mapping[str, Any],
                  cuerpo: Mapping[str, Any], ahora: datetime) -> Mapping[str, Any] | None:
        """Si el mensaje confirma la acción pendiente, la saca de la sesión (la reclama este turno);
        si es de otra acción, ya se hizo o venció, `409`."""
        if "confirmacion" not in cuerpo:
            return None
        accion = fila["accion"]
        if (accion is None or accion["id"] != str(cuerpo["confirmacion"]["accionId"])
                or datetime.fromisoformat(accion["venceEn"]) <= ahora):
            raise Problema(409, "Conflicto", self._mensajes.texto("accion_inexistente"))
        sesiones.quitar_accion(conexion, usuario_id, sesion_id)
        return accion

    def _devolver(self, usuario_id: UUID, sesion_id: UUID,
                  reclamada: Mapping[str, Any] | None) -> None:
        """El turno falló: la acción reclamada vuelve a estar pendiente."""
        if reclamada is None:
            return
        with self._transaccion(usuario_id) as conexion:
            fila = sesiones.obtener(conexion, usuario_id, sesion_id)
            if fila is not None and fila["accion"] is None:
                sesiones.actualizar(conexion, usuario_id, sesion_id,
                                    viaje_id=str(fila["viaje_id"]) if fila["viaje_id"] else None,
                                    no_entendidos=fila["no_entendidos"], accion=reclamada,
                                    ahora=fila["ultimo_turno_en"])

    def _previa(self, conexion, usuario_id: UUID, clave: UUID, operacion: str,
                huella: str) -> dict[str, Any] | None:
        previa = respuesta_guardada(conexion, usuario_id, clave)
        if previa is None:
            return None
        if (previa.operacion, previa.huella) != (operacion, huella):
            raise Problema(400, "Solicitud inválida",
                           "La Idempotency-Key ya se usó con otra solicitud")
        return previa.cuerpo

    # --- trabajo periódico ---------------------------------------------------------------

    def tareas_periodicas(self) -> None:
        """Borra las sesiones vencidas (30 días sin turnos), las disrupciones viejas, la bandeja
        de entrada y las claves de idempotencia vencidas."""
        ahora = self._reloj()
        with self._lectura() as conexion:
            sesiones.purgar_vencidas(conexion, ahora)
            contexto.purgar_disrupciones(conexion, ahora, RETENCION)
            purgar(conexion, ahora)

    # --- API y broker --------------------------------------------------------------------

    def app(self) -> FastAPI:
        """La API del asistente. Al arrancar crea el esquema; corre el trabajo periódico cada
        `intervalo_tareas_s` (0 lo apaga) y, con broker, consume `DisrupcionDetectada`."""
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

    def topicos(self) -> dict[Carril, list[str]]:
        prefijo = self._configuracion.prefijo_topicos
        consume: dict[Carril, list[str]] = {}
        for tipo in sorted(CONSUME):
            for carril in carriles_posibles(self._contratos, tipo):
                consume.setdefault(carril, []).append(topico(self._contratos, tipo, carril, prefijo))
        return consume

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        c = self._configuracion
        if not c.broker:
            yield []
            return
        consume = self.topicos()
        await asegurar_topicos(c.broker, [t for ts in consume.values() for t in ts])
        consumidor = ConsumidorConCarriles(c.broker, CONSUMIDOR, consume, self.consumir,
                                           c.dsn_postgres, self._esquema)
        await consumidor.iniciar()
        detener = asyncio.Event()
        # Referencia propia: el bucle de eventos solo guarda referencias débiles a las tareas.
        tareas = [asyncio.create_task(consumidor.correr(detener))]
        try:
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
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de virtual-assistant")

    # --- transacciones -------------------------------------------------------------------

    @contextlib.contextmanager
    def _transaccion(self, usuario_id: UUID | str):
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.virtual_assistant.servicio:crear_app`."""
    return VirtualAssistant().app()
