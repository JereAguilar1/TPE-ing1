"""Publicación de la *outbox* en el *broker* (ADR-0012).

`PublicadorDeOutbox` lleva al *broker* lo que un servicio escribió en su `bandeja_salida`, en el
orden en que se escribió, por el tópico del carril de cada evento, y lo marca como publicado. Es
«al menos una vez»: si falla entre enviar y marcar, el evento se vuelve a enviar, y la bandeja de
entrada del consumidor evita el segundo efecto (ADR-0014).
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
from aiokafka import AIOKafkaProducer

from trotamundos.comun.carriles import topico
from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar, transaccion


def pendientes(conexion: psycopg.Connection, limite: int) -> list[dict[str, Any]]:
    return conexion.execute(
        """SELECT evento_id, tipo, carril, clave_de_particion, sobre, carga FROM bandeja_salida
           WHERE publicado_en IS NULL ORDER BY seq LIMIT %s""", (limite,)).fetchall()


def marcar_publicados(conexion: psycopg.Connection, eventos_id: list) -> None:
    conexion.execute("UPDATE bandeja_salida SET publicado_en = now() WHERE evento_id = ANY(%s)",
                     ([str(e) for e in eventos_id],))


class PublicadorDeOutbox:
    """Publica la `bandeja_salida` de un esquema. Uno solo a la vez por esquema: un bloqueo
    consultivo de sesión evita que dos procesos mezclen el orden."""

    def __init__(self, dsn: str, esquema: str, servidores: str, contratos: Contratos,
                 prefijo: str = ""):
        self._dsn, self._esquema, self._servidores = dsn, esquema, servidores
        self._contratos, self._prefijo = contratos, prefijo
        self._productor: AIOKafkaProducer | None = None
        self._cerrojo: psycopg.Connection | None = None

    async def iniciar(self) -> None:
        self._productor = AIOKafkaProducer(bootstrap_servers=self._servidores, acks="all",
                                           enable_idempotence=True)
        await self._productor.start()

    async def detener(self) -> None:
        if self._productor is not None:
            await self._productor.stop()
        if self._cerrojo is not None:
            await asyncio.to_thread(self._cerrojo.close)

    def _tengo_el_turno(self) -> bool:
        if self._cerrojo is None:
            self._cerrojo = conectar(self._dsn, self._esquema)
            self._cerrojo.autocommit = True
        fila = self._cerrojo.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS ok",
                                     (f"publicador:{self._esquema}",)).fetchone()
        return fila["ok"]

    async def publicar_pendientes(self, limite: int = 200) -> int:
        """Publica hasta `limite` eventos pendientes, en orden; devuelve cuántos. Si algo falla
        después de enviar y antes de marcar, esos eventos se vuelven a enviar en la próxima
        vuelta (al menos una vez; la bandeja de entrada del consumidor evita el doble efecto)."""
        if not await asyncio.to_thread(self._tengo_el_turno):
            return 0
        filas = await asyncio.to_thread(self._leer, limite)
        enviados = []
        try:
            for fila in filas:
                evento = Evento(fila["tipo"], fila["sobre"], fila["carga"])
                clave, valor, cabeceras = evento.a_kafka()
                await self._productor.send_and_wait(
                    topico(self._contratos, evento.tipo, fila["carril"], self._prefijo),
                    valor, key=clave, headers=cabeceras)
                enviados.append(fila["evento_id"])
        finally:
            if enviados:
                await asyncio.to_thread(self._marcar, enviados)
        return len(enviados)

    def _leer(self, limite: int) -> list[dict[str, Any]]:
        with transaccion(self._dsn, self._esquema) as conexion:
            return pendientes(conexion, limite)

    def _marcar(self, eventos_id: list) -> None:
        with transaccion(self._dsn, self._esquema) as conexion:
            marcar_publicados(conexion, eventos_id)
