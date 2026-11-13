"""Consumo por carriles de prioridad (ADR-0014, ADR-0020).

`ConsumidorConCarriles` lee siempre primero P1, después P2 y después P3, que se puede pausar (modo
«Disrupción masiva»). Un mensaje que no cumple el contrato no se puede procesar nunca: se guarda en
`evento_rechazado` y el consumidor sigue (nada se descarta en silencio). Cualquier otro error se
reintenta: el desplazamiento no avanza hasta que el mensaje se procesa. La bandeja de entrada la
aplica quien maneja cada evento.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Mapping

from aiokafka import AIOKafkaConsumer
from psycopg.types.json import Jsonb

from trotamundos.comun.carriles import ORDEN_DE_LECTURA, Carril
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import transaccion

_registro_de_errores = logging.getLogger(__name__)

DDL_RECHAZADOS = (
    """
    CREATE TABLE IF NOT EXISTS evento_rechazado (
        id             bigserial   PRIMARY KEY,
        consumidor     text        NOT NULL,
        usuario_id     uuid,
        topico         text        NOT NULL,
        particion      integer     NOT NULL,
        desplazamiento bigint      NOT NULL,
        motivo         text        NOT NULL,
        cabeceras      jsonb       NOT NULL,
        valor          bytea,
        recibido_en    timestamptz NOT NULL DEFAULT now()
    );
    """,
)


class ConsumidorConCarriles:
    """Consume los tópicos de un servicio, de a un carril por vuelta y siempre el más urgente
    que tenga mensajes. `manejar` es síncrona (usa la base) y corre en un hilo."""

    def __init__(self, servidores: str, grupo: str, topicos_por_carril: Mapping[Carril, list[str]],
                 manejar: Callable[[Evento], Any], dsn: str, esquema: str, *,
                 pausar_p3: Callable[[], bool] = lambda: False, reintento_s: float = 1.0):
        self._servidores, self._grupo = servidores, grupo
        self._topicos = {c: list(t) for c, t in topicos_por_carril.items() if t}
        self._manejar, self._dsn, self._esquema = manejar, dsn, esquema
        self._pausar_p3, self._reintento_s = pausar_p3, reintento_s
        self._consumidores: dict[Carril, AIOKafkaConsumer] = {}

    async def iniciar(self) -> None:
        for carril, topicos in self._topicos.items():
            consumidor = AIOKafkaConsumer(
                *topicos, bootstrap_servers=self._servidores, group_id=f"{self._grupo}.{carril.lower()}",
                enable_auto_commit=False, auto_offset_reset="earliest")
            await consumidor.start()
            self._consumidores[carril] = consumidor

    async def detener(self) -> None:
        for consumidor in self._consumidores.values():
            await consumidor.stop()

    async def esperar_asignacion(self, limite_s: float = 30.0) -> None:
        """Espera a que el broker asigne particiones a cada carril (al unirse al grupo)."""
        async def asignado(consumidor: AIOKafkaConsumer) -> None:
            while not consumidor.assignment():
                await consumidor.getmany(timeout_ms=100, max_records=1)  # dispara la unión
            # Lo que haya devuelto ese getmany no se procesó: cada partición vuelve a su
            # desplazamiento confirmado, o al principio si el grupo es nuevo.
            for particion in consumidor.assignment():
                confirmado = await consumidor.committed(particion)
                if confirmado is None:
                    await consumidor.seek_to_beginning(particion)
                else:
                    consumidor.seek(particion, confirmado)
        await asyncio.wait_for(asyncio.gather(*(asignado(c) for c in self._consumidores.values())),
                               limite_s)

    async def vuelta(self, espera_ms: int = 200) -> tuple[Carril | None, int]:
        """Procesa un lote del carril más urgente con mensajes; devuelve el carril y cuántos."""
        for carril in ORDEN_DE_LECTURA:
            consumidor = self._consumidores.get(carril)
            if consumidor is None or (carril == Carril.P3 and self._pausar_p3()):
                continue
            # Los carriles urgentes se miran sin esperar; solo el último espera mensajes.
            lote = await consumidor.getmany(timeout_ms=0 if carril != Carril.P3 else espera_ms,
                                            max_records=100)
            if not lote:
                continue
            procesados = 0
            for particion, mensajes in lote.items():
                for mensaje in mensajes:
                    try:
                        await asyncio.to_thread(self._procesar, mensaje)
                    except Exception:
                        # Error transitorio: no se avanza; el mensaje vuelve en la próxima vuelta.
                        _registro_de_errores.exception("No se pudo procesar %s@%s",
                                                       mensaje.topic, mensaje.offset)
                        consumidor.seek(particion, mensaje.offset)
                        await asyncio.sleep(self._reintento_s)
                        break
                    procesados += 1
                    await consumidor.commit({particion: mensaje.offset + 1})
            return carril, procesados
        return None, 0

    async def correr(self, detener: asyncio.Event) -> None:
        while not detener.is_set():
            carril, _ = await self.vuelta()
            if carril is None:
                await asyncio.sleep(0.2)

    def _procesar(self, mensaje: Any) -> None:
        cabeceras = list(mensaje.headers or [])
        try:
            evento = Evento.desde_kafka(mensaje.value, cabeceras)
            self._manejar(evento)
        except ErrorDeContrato as error:
            self._rechazar(mensaje, cabeceras, str(error))

    def _rechazar(self, mensaje: Any, cabeceras: list, motivo: str) -> None:
        legibles = {k: v.decode(errors="replace") for k, v in cabeceras}
        usuario = legibles.get("usuarioId")
        with transaccion(self._dsn, self._esquema) as conexion:
            conexion.execute(
                """INSERT INTO evento_rechazado (consumidor, usuario_id, topico, particion,
                                                 desplazamiento, motivo, cabeceras, valor)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (self._grupo, usuario if _es_uuid(usuario) else None, mensaje.topic,
                 mensaje.partition, mensaje.offset, motivo[:2000], Jsonb(legibles), mensaje.value))


def _es_uuid(texto: str | None) -> bool:
    return bool(texto) and re.fullmatch(r"[0-9a-fA-F-]{36}", texto) is not None
