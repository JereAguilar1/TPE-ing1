"""Armado de `provider-sync` (iteración 2 §5.5; vista de adaptadores §1; paso 10).

Coordina `registro_de_adaptadores`, `seguimiento`, `receptor_de_notificaciones`, `programador`,
`detector_de_disrupciones` y `publicacion`. Consume `ReservaActualizada` y `ReservaCancelada` para
mantener el índice de reservas seguidas, y publica `ReservaObservada` y `DisrupcionDetectada` a
través de la *outbox* transaccional.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterable, Mapping
from uuid import UUID

import psycopg
from fastapi import FastAPI

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion, _variable
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RETENCION,
    bloquear_usuario,
    crear_esquema,
    purgar,
    registrar_en_bandeja_de_entrada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.servicios.provider_sync import (
    api,
    detector_de_disrupciones,
    programador,
    proteccion,
    publicacion,
    receptor_de_notificaciones,
    seguimiento,
)
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import CargaInvalida
from trotamundos.servicios.provider_sync.registro_de_adaptadores import RegistroDeAdaptadores

ESQUEMA = "provider_sync"
PRODUCTOR = "provider-sync"
CONSUME = frozenset({"ReservaActualizada", "ReservaCancelada"})
PAUSA_S = 0.5

DDL = (
    *seguimiento.DDL,
    *programador.DDL,
    *proteccion.DDL,
    *detector_de_disrupciones.DDL,
    *DDL_RECHAZADOS,
    """
    CREATE TABLE IF NOT EXISTS observacion_emitida (
        adaptador_id text NOT NULL,
        usuario_id uuid NOT NULL,
        id_de_fuente text NOT NULL,
        emitida_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (adaptador_id, usuario_id, id_de_fuente)
    );
    """,
)

_registro = logging.getLogger(__name__)


class ProviderSync:
    """Anfitrión de los complementos adaptadores de proveedores de viaje."""

    def __init__(self, configuracion: Configuracion | None = None, *,
                 esquema: str = ESQUEMA,
                 contratos: Contratos | None = None,
                 registro: RegistroDeAdaptadores | None = None,
                 secreto_webhook: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self.registro = registro or RegistroDeAdaptadores(self._contratos)
        # Una barrera por adaptador, con la cuota de su manifiesto (ADR-0024)
        self.protector = proteccion.ProtectorDeProveedores({
            adaptador_id: int(self.registro.obtener(adaptador_id).capacidades["cuotaPorMinuto"])
            for adaptador_id in self.registro.ids()})
        self._secreto_webhook = (
            secreto_webhook
            or os.environ.get("TROTAMUNDOS_SECRETO_WEBHOOK_PROVEEDOR")
            or _variable("TROTAMUNDOS_SECRETO_WEBHOOK_PROVEEDOR")
            or secrets.token_hex(32)
        )
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- Seguimiento (ReservaActualizada / ReservaCancelada) -----------------------------

    def seguir_reserva(self, adaptador_id: str, referencia: str,
                       usuario_id: UUID | str, reserva_id: UUID | str, *,
                       inicio_proximo: datetime | None = None,
                       fin_ultimo: datetime | None = None) -> None:
        """Registra explícitamente una reserva en el índice de `seguimiento`."""
        self.registro.obtener(adaptador_id)
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            seguimiento.registrar(
                conexion, adaptador_id, referencia, usuario_id, reserva_id,
                inicio_proximo=inicio_proximo, fin_ultimo=fin_ultimo, ahora=self._reloj(),
            )

    def consumir(self, evento: Evento) -> None:
        if evento.tipo not in CONSUME:
            raise ErrorDeContrato(evento.tipo, [f"provider-sync no consume {evento.tipo}"])
        evento.validar(self._contratos)
        usuario_id = evento.sobre["usuarioId"]
        ahora = self._reloj()
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            if not registrar_en_bandeja_de_entrada(conexion, PRODUCTOR, evento):
                return
            if evento.tipo == "ReservaActualizada":
                seguimiento.actualizar_desde_reserva(
                    conexion,
                    usuario_id,
                    evento.carga["reserva"],
                    self.registro.adaptadores_para_emisor,
                    ahora,
                    unificada_con=evento.carga.get("unificadaCon") or (),
                )
            elif evento.tipo == "ReservaCancelada":
                seguimiento.baja_reserva(conexion, usuario_id, evento.carga["reservaId"])

    # --- Webhook entrante (POST /webhooks/proveedor) -------------------------------------

    def recibir_notificacion(self, proveedor_id: str, tipo_contenido: str | None,
                             cabeceras: Mapping[str, str], cuerpo_crudo: bytes,
                             firma_recibida: str | None,
                             traceparent: str | None = None) -> None:
        if not receptor_de_notificaciones.firma_valida(cuerpo_crudo, firma_recibida,
                                                       self._secreto_webhook):
            raise Problema(401, "No autorizado", "Firma de webhook inválida")

        if not self.registro.existe(proveedor_id):
            raise no_encontrado()

        adaptador = self.registro.obtener(proveedor_id)
        if not adaptador.capacidades.get("push"):
            raise no_encontrado()

        try:
            cuerpo = receptor_de_notificaciones.decodificar_cuerpo(cuerpo_crudo, tipo_contenido)
            cambios = self.registro.traducir_notificacion(proveedor_id, cabeceras, cuerpo)
        except (receptor_de_notificaciones.CargaWebhookInvalida, CargaInvalida,
                ErrorDeContrato) as error:
            raise Problema(400, "Solicitud inválida", str(error)) from error

        ahora = self._reloj()
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            self._procesar_cambios(conexion, proveedor_id, cambios, ahora,
                                   traceparent=traceparent)

    # --- Sondeo programado ---------------------------------------------------------------

    def sondear_proveedores(self) -> int:
        ahora = self._reloj()
        emitidos = 0
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            for adaptador_id, cambios in programador.sondear_todos(conexion, self.registro, ahora,
                                                                   self.protector):
                emitidos += self._procesar_cambios(conexion, adaptador_id, cambios, ahora)
        return emitidos

    def _procesar_cambios(self, conexion: psycopg.Connection, adaptador_id: str,
                          cambios: Iterable[Mapping[str, Any]], ahora: datetime, *,
                          traceparent: str | None = None) -> int:
        lista_cambios = list(cambios)
        if not lista_cambios:
            return 0

        adaptador = self.registro.obtener(adaptador_id)
        disrupciones, causas_por_ref = detector_de_disrupciones.detectar_y_expandir(
            conexion, self.registro, adaptador_id, lista_cambios, ahora
        )

        salidas: list[Evento | tuple[Evento, Carril]] = []
        for disrupcion in disrupciones:
            evento_disrupcion = Evento.nuevo(
                "DisrupcionDetectada",
                disrupcion.a_carga(),
                productor=PRODUCTOR,
                usuario_id=disrupcion.primer_usuario_id,
                region=self._configuracion.region,
                id_de_causa=disrupcion.disrupcion_id,
                traceparent=traceparent,
            )
            salidas.append((evento_disrupcion, Carril.P1))

        for cambio in lista_cambios:
            referencia = str(cambio["referencia"])
            observacion = cambio["observacion"]
            id_de_fuente = str(observacion["idDeFuente"])
            causa_id = causas_por_ref.get(referencia)

            for seguida in seguimiento.resolver(conexion, adaptador_id, referencia):
                bloquear_usuario(conexion, seguida.usuario_id)
                nueva = conexion.execute(
                    """
                    INSERT INTO observacion_emitida (adaptador_id, usuario_id, id_de_fuente, emitida_en)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id_de_fuente
                    """,
                    (adaptador_id, seguida.usuario_id, id_de_fuente, ahora),
                ).fetchone()
                if nueva is None:
                    continue

                carril = publicacion.carril_reserva_observada(
                    observacion,
                    inicio_proximo=seguida.inicio_proximo,
                    fin_ultimo=seguida.fin_ultimo,
                    ahora=ahora,
                    tiene_disrupcion=causa_id is not None,
                )
                evento_obs = Evento.nuevo(
                    "ReservaObservada",
                    {
                        "adaptador": {"id": adaptador.id, "version": adaptador.version},
                        "observacion": observacion,
                    },
                    productor=PRODUCTOR,
                    usuario_id=seguida.usuario_id,
                    region=self._configuracion.region,
                    id_de_causa=causa_id,
                    traceparent=traceparent,
                )
                salidas.append((evento_obs, carril))

        if salidas:
            publicacion.registrar(conexion, salidas, self._contratos)
        return len(salidas)

    # --- Trabajo periódico y ciclo de vida -----------------------------------------------

    def tareas_periodicas(self) -> None:
        self.sondear_proveedores()
        ahora = self._reloj()
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            purgar(conexion, ahora)
            detector_de_disrupciones.purgar_emitidas(conexion, ahora, RETENCION)
            proteccion.purgar_vencidos(conexion, ahora)
            conexion.execute(
                "DELETE FROM observacion_emitida WHERE emitida_en < %s",
                (ahora - RETENCION,),
            )

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

        app = api.crear_app(self, lifespan=ciclo_de_vida)
        app.state.servicio = self
        return app

    def topicos(self) -> tuple[list[str], dict[Carril, list[str]]]:
        prefijo = self._configuracion.prefijo_topicos
        publica = [
            topico(self._contratos, tipo, carril, prefijo)
            for tipo in sorted(publicacion.PUBLICA)
            for carril in carriles_posibles(self._contratos, tipo)
        ]
        consume: dict[Carril, list[str]] = {}
        for tipo in sorted(CONSUME):
            for carril in carriles_posibles(self._contratos, tipo):
                consume.setdefault(carril, []).append(
                    topico(self._contratos, tipo, carril, prefijo)
                )
        return publica, consume

    @contextlib.asynccontextmanager
    async def con_broker(self) -> AsyncIterator[list[asyncio.Task]]:
        c = self._configuracion
        if not c.broker:
            yield []
            return
        publica, consume = self.topicos()
        await asegurar_topicos(c.broker, publica + [t for ts in consume.values() for t in ts])
        publicador = PublicadorDeOutbox(
            c.dsn_postgres, self._esquema, c.broker, self._contratos, c.prefijo_topicos
        )
        consumidor = ConsumidorConCarriles(
            c.broker, PRODUCTOR, consume, self.consumir, c.dsn_postgres, self._esquema
        )
        detener = asyncio.Event()
        tareas: list[asyncio.Task] = []
        try:
            await publicador.iniciar()
            await consumidor.iniciar()
            tareas = [
                asyncio.create_task(self._publicar_siempre(publicador, detener)),
                asyncio.create_task(consumidor.correr(detener)),
            ]
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
                _registro.warning("No se pudo publicar la outbox de provider-sync; se reintentará")
                await asyncio.sleep(PAUSA_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:
                _registro.warning("Falló el trabajo periódico de provider-sync; se reintentará")


def crear_app() -> FastAPI:
    """Fábrica de Uvicorn: `uvicorn --factory trotamundos.servicios.provider_sync.servicio:crear_app`."""
    return ProviderSync().app()
