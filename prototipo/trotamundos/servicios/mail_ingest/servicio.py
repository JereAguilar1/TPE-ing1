"""El elemento `mail-ingest`: arma los módulos de la vista N2 (§3) y define las transacciones.

Los dos caminos de ADR-0004 convergen en la cola «buzones con cambios»:

* el **aviso** del proveedor (`receptor`) y el **sondeo** (`reconciliador`) encolan el buzón;
* `suscripciones` mantiene las suscripciones de avisos a partir de `EstadoDeBuzonCambiado`;
* un solo camino atiende la cola: token efímero de `identity-access` (`descargador`), metadatos,
  `filtros` **antes** de bajar el cuerpo, `normalizador`, `deduplicador` y `publicacion` de
  `MensajeDeViajeRecibido` en la *outbox*, todo en la transacción del buzón.

Con un *broker* configurado también consume `EstadoDeBuzonCambiado` y publica la *outbox*.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import UUID

import psycopg
from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.errores import Problema
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    bloquear_usuario,
    crear_esquema,
    purgar,
    registrar_en_bandeja_de_entrada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.mail_ingest import (
    api,
    cola,
    deduplicador,
    descargador,
    filtros,
    normalizador,
    publicacion,
    receptor,
    receptor_reenvio,
    reconciliador,
    suscripciones,
)
from trotamundos.servicios.mail_ingest.complementos.correo_simulado import CorreoSimulado
from trotamundos.servicios.mail_ingest.interfaz_de_correo import AdaptadorDeCorreo

ESQUEMA = "mail_ingest"
PRODUCTOR = "mail-ingest"
CONSUME = frozenset({"EstadoDeBuzonCambiado"})
PAUSA_S = 0.5
_CUERPO_AVISO = ("openapi/mail-ingest-webhooks.yaml#/paths/~1webhooks~1correo/post/requestBody"
                 "/content/application~1json/schema")

DDL = (*suscripciones.DDL, *cola.DDL, *filtros.DDL, *deduplicador.DDL,
       *receptor_reenvio.DDL, *DDL_RECHAZADOS)
# Quién puede entregar al receptor de reenvío: el servidor de correo entrante propio. La identidad
# mTLS se simula con `X-Servicio-Cliente`, como en el paso 7.
MTA_ENTRANTE = "mta-entrante"

_registro_de_errores = logging.getLogger(__name__)


class MailIngest:
    """Las operaciones de `mail-ingest`, cada una en su transacción."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None,
                 adaptadores: Mapping[str, AdaptadorDeCorreo] | None = None,
                 emisor_de_tokens: descargador.EmisorDeTokens | None = None,
                 secreto_webhook: str | None = None,
                 secreto_jwt: str | None = None,
                 intervalos: Mapping[bool, timedelta] | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        # Un complemento por vía; `reenvio` no tiene: lo entrega el servidor de correo propio.
        self.adaptadores = dict(adaptadores) if adaptadores is not None else {
            "oauth": CorreoSimulado(soporta_push=True),
            "imapDelegado": CorreoSimulado(soporta_push=False),
        }
        self._emisor = emisor_de_tokens or descargador.EmisorDeTokensHttp(
            os.environ.get("TROTAMUNDOS_URL_IDENTITY_ACCESS", "http://localhost:18103"))
        self._secreto_webhook = (secreto_webhook
                                 or os.environ.get("TROTAMUNDOS_SECRETO_WEBHOOK_CORREO")
                                 or secrets.token_hex(32))
        # Para verificar la sesión OIDC de la API de filtros (`comun.sesion`).
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._intervalos = dict(intervalos) if intervalos is not None else {
            True: reconciliador.INTERVALO_CON_PUSH, False: reconciliador.INTERVALO_SIN_PUSH}
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    def adaptador_para(self, via: str, proveedor: str | None = None) -> AdaptadorDeCorreo | None:
        """El complemento de la vía. En el prototipo todos los proveedores OAuth comparten el
        simulado; en producción, `proveedor` elegiría el de Gmail o el de Microsoft Graph."""
        return self.adaptadores.get(via)

    # --- EstadoDeBuzonCambiado -----------------------------------------------------------

    def consumir(self, evento: Evento) -> None:
        """Lanza `ErrorDeContrato` si el evento no cumple el contrato, sin dejar nada escrito."""
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"mail-ingest no consume {evento.tipo}"])
        evento.validar(self._contratos)
        usuario_id = UUID(evento.sobre["usuarioId"])
        ahora = self._reloj()
        with self._transaccion(usuario_id) as conexion:
            if not registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                return
            suscripciones.aplicar_estado(
                conexion, self.adaptador_para, usuario_id, evento.sobre.get("regionOrigen"),
                evento.carga, ahora,
                lambda buzon, push: reconciliador.proxima(buzon, self._intervalos[push], ahora))

    # --- receptor ------------------------------------------------------------------------

    def recibir_aviso(self, cuerpo: bytes, firma: str | None) -> None:
        """`POST /webhooks/correo`: firma, encolar, responder. Un aviso de una suscripción que no
        es (o ya no es) de un buzón activo se acepta y no hace nada: no se revela cuáles existen."""
        if not receptor.firma_valida(cuerpo, firma, self._secreto_webhook):
            raise Problema(401, "Firma inválida")
        try:
            datos = json.loads(cuerpo)
        except ValueError as error:
            raise Problema(400, "Solicitud inválida", "El cuerpo no es JSON") from error
        errores = self._contratos.errores(_CUERPO_AVISO, datos)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": e.partition(": ")[0], "mensaje": e.partition(": ")[2]} for e in errores])
        with self._lectura() as conexion:
            buzon = suscripciones.por_suscripcion(conexion, str(datos["suscripcionId"]))
            if buzon is not None:
                cola.encolar(conexion, buzon.buzon_id, buzon.usuario_id, "aviso", self._reloj())

    def firmar_aviso(self, cuerpo: bytes) -> str:
        """La firma que mandaría el proveedor (para pruebas y para la demostración)."""
        return receptor.firma(cuerpo, self._secreto_webhook)

    # --- receptor de reenvío (ADR-0035) ---------------------------------------------------

    def recibir_reenvio(self, crudo: bytes, alias: str, cliente: str | None) -> None:
        """`POST /webhooks/correo/reenvio`. Un mensaje que no se autentica se descarta, se audita
        y responde 403; uno aceptado sigue el camino de siempre hasta la *outbox*, sin pasar por
        la cola: ya llegó entero."""
        if cliente != MTA_ENTRANTE:
            raise Problema(403, "Prohibido")
        mensaje = normalizador.leer(crudo)
        ahora = self._reloj()
        with self._lectura() as conexion:
            buzon = suscripciones.por_alias(conexion, alias)
        motivo = ("aliasDesconocido" if buzon is None
                  else receptor_reenvio.motivo_de_rechazo(mensaje, buzon.correo_titular))
        if buzon is None or motivo is not None:
            with self._lectura() as conexion:
                receptor_reenvio.auditar_rechazo(conexion, alias, motivo or "aliasDesconocido",
                                                 ahora)
            raise Problema(403, "Prohibido", "Autenticación del remitente no superada")
        identificador = receptor_reenvio.id_de_mensaje(mensaje, crudo)
        with self._transaccion(buzon.usuario_id) as conexion:
            if not filtros.admite_reenvio(filtros.de_usuario(conexion, buzon.usuario_id),
                                          normalizador.remitente(mensaje)):
                deduplicador.registrar(conexion, buzon.buzon_id, buzon.usuario_id, identificador,
                                       ahora, descartado="bloqueado")
                return
            self._publicar_mensaje(conexion, buzon, identificador, crudo, ahora, ahora)

    # --- la cola: un solo camino ---------------------------------------------------------

    def procesar_cola(self, limite: int = 100) -> int:
        """Atiende hasta `limite` buzones de la cola y devuelve cuántos. Cada uno se reclama
        (sale de la cola) y después se lee en su propia transacción, con el usuario bloqueado.
        Si la lectura falla, esa transacción se deshace y el buzón vuelve a la cola con espera
        (ADR-0024): no frena a los demás. En una misma vuelta, cada buzón se atiende una vez."""
        atendidos, vistos = 0, set()
        while atendidos < limite:
            with self._lectura() as conexion:
                reclamado = cola.reclamar(conexion, self._reloj(), vistos)
            if reclamado is None:
                return atendidos
            vistos.add(reclamado["buzon_id"])
            try:
                with self._transaccion(reclamado["usuario_id"]) as conexion:
                    self._atender(conexion, reclamado["buzon_id"])
            except Exception:
                _registro_de_errores.exception("No se pudo atender el buzón %s",
                                               reclamado["buzon_id"])
                with self._lectura() as conexion:
                    cola.reintentar(conexion, reclamado, self._reloj())
            atendidos += 1
        return atendidos

    def _atender(self, conexion: psycopg.Connection, buzon_id: UUID) -> None:
        buzon = suscripciones.obtener(conexion, buzon_id)
        adaptador = self.adaptador_para(buzon.via, buzon.proveedor) if buzon else None
        if buzon is None or not buzon.activo or adaptador is None:
            return
        try:
            token = self._emisor.token(buzon_id)
        except descargador.BuzonNoDisponible:
            return  # ya no está Activo: llegará su EstadoDeBuzonCambiado
        ahora = self._reloj()
        novedades = adaptador.novedades(str(buzon_id), token, buzon.cursor)
        lista = filtros.de_usuario(conexion, buzon.usuario_id)
        for metadatos in novedades.mensajes:
            if deduplicador.ya_recibido(conexion, buzon_id, metadatos.id_de_mensaje):
                continue
            if not filtros.admite(lista, metadatos.remitente):
                deduplicador.registrar(conexion, buzon_id, buzon.usuario_id,
                                       metadatos.id_de_mensaje, ahora, descartado="filtrado")
                continue
            crudo = adaptador.descargar(str(buzon_id), token, metadatos.id_de_mensaje)
            self._publicar_mensaje(conexion, buzon, metadatos.id_de_mensaje, crudo,
                                   metadatos.recibido_en, ahora)
        suscripciones.guardar_cursor(conexion, buzon_id, novedades.cursor)

    def _publicar_mensaje(self, conexion: psycopg.Connection, buzon: suscripciones.Buzon,
                          id_de_mensaje: str, crudo: bytes, recibido_en: datetime | None,
                          ahora: datetime) -> bool:
        """Normaliza, deduplica y deja `MensajeDeViajeRecibido` en la *outbox*. Un mensaje que
        no se puede leer o no cumple el contrato queda registrado como descartado, con el motivo,
        y no frena a los que vienen detrás: reintentarlo daría el mismo resultado."""
        try:
            mensaje = normalizador.normalizar(crudo, recibido_en)
        except Exception:
            _registro_de_errores.warning("Mensaje %s/%s ilegible", buzon.buzon_id, id_de_mensaje,
                                         exc_info=True)
            deduplicador.registrar(conexion, buzon.buzon_id, buzon.usuario_id, id_de_mensaje,
                                   ahora, descartado="ilegible")
            return False
        evento = Evento.nuevo(
            "MensajeDeViajeRecibido",
            {"buzonId": str(buzon.buzon_id), "idDeMensaje": id_de_mensaje, "via": buzon.via,
             "mensaje": mensaje},
            productor=PRODUCTOR, usuario_id=str(buzon.usuario_id), region=buzon.region)
        try:
            evento.validar(self._contratos)
        except ErrorDeContrato:
            _registro_de_errores.warning("Mensaje %s/%s no cumple MensajeNormalizado",
                                         buzon.buzon_id, id_de_mensaje)
            deduplicador.registrar(conexion, buzon.buzon_id, buzon.usuario_id, id_de_mensaje,
                                   ahora, descartado="noCumpleElContrato")
            return False
        if not deduplicador.registrar(conexion, buzon.buzon_id, buzon.usuario_id, id_de_mensaje,
                                      ahora):
            return False
        publicacion.registrar(conexion, [evento], self._contratos)
        return True

    # --- filtros (RF-04) -----------------------------------------------------------------

    def leer_filtros(self, usuario_id: UUID) -> dict[str, list[str]]:
        with self._lectura() as conexion:
            return filtros.de_usuario(conexion, usuario_id).a_dict()

    def guardar_filtros(self, usuario_id: UUID, cuerpo: Mapping[str, Any]) -> dict[str, list[str]]:
        with self._transaccion(usuario_id) as conexion:
            filtros.guardar(conexion, usuario_id, filtros.Filtros(
                tuple(cuerpo["permitidos"]), tuple(cuerpo["bloqueados"])), self._reloj())
            return filtros.de_usuario(conexion, usuario_id).a_dict()

    def catalogo_de_remitentes(self) -> list[dict[str, str]]:
        """Los remitentes que algún extractor reconoce. Vacío hasta que haya extractores (paso 9)."""
        return []

    # --- trabajo periódico ---------------------------------------------------------------

    def tareas_periodicas(self) -> None:
        """Renueva las suscripciones (y rehace las caídas), encola los buzones cuyo turno de
        reconciliación llegó y purga lo vencido."""
        ahora = self._reloj()
        with self._lectura() as conexion:
            suscripciones.renovar(conexion, self.adaptador_para, ahora)
        with self._lectura() as conexion:
            reconciliador.vencidos(conexion, ahora, self._intervalos)
        with self._lectura() as conexion:
            purgar(conexion, ahora)
            deduplicador.purgar(conexion, ahora)

    # --- API y broker --------------------------------------------------------------------

    def app(self) -> FastAPI:
        """La API de `mail-ingest`. Al arrancar crea el esquema; corre el trabajo periódico cada
        `intervalo_tareas_s` (0 lo apaga), atiende la cola y, con broker, consume y publica."""
        intervalo = self._configuracion.intervalo_tareas_s

        @asynccontextmanager
        async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            tareas = [asyncio.create_task(self._atender_cola_siempre())]
            if intervalo > 0:
                tareas.append(asyncio.create_task(self._bucle(intervalo)))
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
                _registro_de_errores.exception("Falló la publicación de la outbox de mail-ingest")
                await asyncio.sleep(PAUSA_S)

    async def _atender_cola_siempre(self) -> None:
        while True:
            try:
                if await asyncio.to_thread(self.procesar_cola) == 0:
                    await asyncio.sleep(PAUSA_S)
            except Exception:  # un buzón que falla vuelve a la cola; se sigue
                _registro_de_errores.exception("Falló la atención de la cola de mail-ingest")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de mail-ingest")

    # --- transacciones -------------------------------------------------------------------

    @contextlib.contextmanager
    def _transaccion(self, usuario_id: UUID | str):
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.mail_ingest.servicio:crear_app`."""
    return MailIngest().app()
