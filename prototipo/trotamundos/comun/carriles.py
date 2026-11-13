"""Carriles de prioridad y tópicos del *broker* (ADR-0020, iteración 3 §5.3).

Cada evento viaja en un carril: `P1` crítico, `P2` estándar o `P3` diferible. El contrato AsyncAPI
lo dice en `x-carril`; cuando es una regla («P1 si el viaje está EnCurso…»), la aplica el
productor. Cada carril es un tópico propio, `<address del canal>.<carril>` (por ejemplo
`dominio.reserva-observada.p1`), particionado por `usuarioId`: dentro de un tópico, los eventos de
un usuario llegan en orden, y P1 no espera detrás de una avalancha de P2. Que dos eventos del
mismo usuario viajen por carriles distintos y lleguen en otro orden es seguro: la fusión no
depende del orden de llegada (ADR-0010, ADR-0014).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Iterable

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from trotamundos.comun.contratos import Contratos

PARTICIONES = 6  # 96 por región en producción (vista de despliegue N2); en una notebook, 6


class Carril(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


ORDEN_DE_LECTURA = (Carril.P1, Carril.P2, Carril.P3)


def carriles_posibles(contratos: Contratos, tipo: str) -> tuple[Carril, ...]:
    """Los carriles por los que puede viajar el evento según `x-carril` (los tres si la regla
    no nombra ninguno, como «según la reserva»)."""
    nombrados = sorted(set(re.findall(r"\bP[123]\b", contratos.carril_de_evento(tipo))))
    return tuple(Carril(c) for c in nombrados) or ORDEN_DE_LECTURA


def carril_fijo(contratos: Contratos, tipo: str) -> Carril | None:
    """El carril si el contrato lo fija; `None` si es una regla que aplica el productor."""
    texto = contratos.carril_de_evento(tipo).strip()
    return Carril(texto) if texto in Carril.__members__ else None


def topico(contratos: Contratos, tipo: str, carril: Carril | str, prefijo: str = "") -> str:
    """Tópico físico: el canal del contrato más el carril. `prefijo` aísla entornos (pruebas)."""
    return f"{prefijo}{contratos.canal_de_evento(tipo)}.{Carril(carril).value.lower()}"


class TopicoNoCreado(RuntimeError):
    """El broker rechazó crear un tópico (por ejemplo, por su límite de particiones)."""


_YA_EXISTE = 36  # código de error de Kafka TOPIC_ALREADY_EXISTS


async def asegurar_topicos(servidores: str, nombres: Iterable[str],
                           particiones: int = PARTICIONES) -> None:
    """Crea los tópicos que falten (Redpanda no siempre los crea solo). El cliente no lanza
    excepción si un tópico no se pudo crear: se revisa la respuesta, para no seguir sin él."""
    administrador = AIOKafkaAdminClient(bootstrap_servers=servidores)
    await administrador.start()
    try:
        existentes = set(await administrador.list_topics())
        nuevos = [NewTopic(n, particiones, 1) for n in sorted(set(nombres)) if n not in existentes]
        if not nuevos:
            return
        try:
            respuesta = await administrador.create_topics(nuevos)
        except TopicAlreadyExistsError:  # otro proceso lo creó en el medio
            return
        errores = [f"{nombre}: {mensaje}" for nombre, codigo, mensaje in respuesta.topic_errors
                   if codigo not in (0, _YA_EXISTE)]
        if errores:
            raise TopicoNoCreado("; ".join(errores))
    finally:
        await administrador.close()


async def borrar_topicos(servidores: str, prefijo: str) -> None:
    """Borra los tópicos que empiezan con `prefijo` (entornos de prueba)."""
    if not prefijo:
        raise ValueError("Sin prefijo se borrarían los tópicos de todos los servicios")
    administrador = AIOKafkaAdminClient(bootstrap_servers=servidores)
    await administrador.start()
    try:
        propios = [t for t in await administrador.list_topics() if t.startswith(prefijo)]
        if propios:
            await administrador.delete_topics(propios)
    finally:
        await administrador.close()
