"""Identidad de una reserva por identificadores múltiples (ADR-0013, «M1 corregida»).

Una reserva tiene un **conjunto** de identificadores `(emisor, código)`. Una observación es de una
reserva si coincide con **cualquiera** de sus identificadores, o si ya se registró una versión de
esa misma observación `(fuente, idDeFuente)` (ADR-0014). Entonces:

* Ninguna reserva coincide → se crea una. El sistema **nunca** fusiona por parecido: si hay
  reservas parecidas, las devuelve como posibles duplicados para que decida el usuario (M2).
* Coincide una → la observación se agrega a esa reserva.
* Coinciden varias → la observación las liga y se unifican: la más antigua conserva el id y
  absorbe a las demás. Si alguna es manual no se unifican: la observación va a la más antigua y
  las otras se devuelven como posibles duplicados, para que el usuario confirme.

La unicidad de los identificadores por usuario se mantiene: un identificador que ya es de otra
reserva no se copia a la que recibe la observación.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trotamundos.comun.modelo import Fuente, Identificador, instante_desde_texto
from trotamundos.servicios.itinerary.fusion.consolidacion import Consolidacion, reconsolidar
from trotamundos.servicios.itinerary.reservas import EstadoReserva, ObservacionRegistrada, Reserva

MOTIVO_IDENTIFICADOR = "Comparten un identificador, pero una es manual: unificarlas requiere confirmación"
MOTIVO_PARECIDO = "Mismo tipo, fecha y lugar de inicio, sin identificadores en común"


class RepositorioDeReservas(Protocol):
    """Lo que la resolución de identidad necesita leer. Lo implementa la persistencia (paso 4)."""

    def por_identificador(self, usuario_id: UUID, identificador: Identificador) -> Reserva | None: ...

    def por_observacion(self, usuario_id: UUID, clave: tuple[Fuente, str]) -> Reserva | None: ...

    def candidatas(self, usuario_id: UUID, desde: date, hasta: date) -> Iterable[Reserva]:
        """Reservas con algún segmento que empieza entre `desde` y `hasta` (fechas locales)."""
        ...


@dataclass(frozen=True)
class PosibleDuplicado:
    """Elemento de `posiblesDuplicados` de `ResultadoComandoReserva` (`comun.yaml`)."""

    reserva_id: UUID
    motivo: str

    def a_dict(self) -> dict[str, Any]:
        return {"reservaId": str(self.reserva_id), "motivo": self.motivo}


@dataclass(frozen=True)
class ResultadoDeIngesta:
    """Qué hizo la fusión con una observación. Quien persiste guarda `reserva`, borra
    `unificadas` y publica los eventos (paso 4)."""

    reserva: Reserva
    creada: bool
    aplicada: bool  # False si la observación ya estaba registrada con esa versión o una posterior
    unificadas: tuple[Reserva, ...]
    consolidacion: Consolidacion
    posibles_duplicados: tuple[PosibleDuplicado, ...]


def ingerir(repositorio: RepositorioDeReservas, usuario_id: UUID, registrada: ObservacionRegistrada,
            ahora: datetime, nuevo_id: Callable[[], UUID] = uuid4) -> ResultadoDeIngesta:
    """Resuelve la identidad de la observación, la agrega y reconsolida (UC-1, UC-2, UC-4)."""
    coincidentes: dict[UUID, Reserva] = {}
    previa = repositorio.por_observacion(usuario_id, registrada.clave)
    if previa is not None:
        coincidentes[previa.id] = previa
    for identificador in registrada.observacion.identificadores:
        reserva = repositorio.por_identificador(usuario_id, identificador)
        if reserva is not None:
            coincidentes[reserva.id] = reserva

    duplicados: list[PosibleDuplicado] = []
    unificadas: tuple[Reserva, ...] = ()
    ajenos: set[Identificador] = set()
    if not coincidentes:
        reserva, creada = Reserva(nuevo_id(), usuario_id, ahora), True
    else:
        reserva, *otras = sorted(coincidentes.values(), key=lambda r: (r.creada_en, str(r.id)))
        creada = False
        if otras and not any(r.es_manual for r in (reserva, *otras)):
            for otra in otras:
                reserva.unir(otra)
            unificadas = tuple(otras)
        else:
            duplicados += [PosibleDuplicado(otra.id, MOTIVO_IDENTIFICADOR) for otra in otras]
            ajenos = {i for otra in otras for i in otra.identificadores}

    aplicada = reserva.registrar(registrada)
    reserva.agregar_identificadores(set(registrada.observacion.identificadores) - ajenos)
    consolidacion = reconsolidar(reserva)

    if creada:
        fechas = [fecha_local(s["inicio"]) for s in reserva.vista.segmentos]
        candidatas = repositorio.candidatas(usuario_id, min(fechas) - timedelta(days=1),
                                            max(fechas) + timedelta(days=1))
        duplicados += sugerencias(reserva, candidatas)

    return ResultadoDeIngesta(reserva, creada, aplicada, unificadas, consolidacion,
                              tuple(duplicados))


# --- coincidencia difusa: solo sugerencias (M2) ----------------------------------------------

def sugerencias(reserva: Reserva, candidatas: Iterable[Reserva]) -> list[PosibleDuplicado]:
    """Reservas parecidas a `reserva`. **Nunca** se fusionan solas: decide el usuario."""
    propias = {_huella(s) for s in reserva.vista.segmentos}
    return [
        PosibleDuplicado(candidata.id, MOTIVO_PARECIDO)
        for candidata in sorted(candidatas, key=lambda r: str(r.id))
        if candidata.id != reserva.id and candidata.consolidada
        and candidata.estado != EstadoReserva.DESCARTADA
        and not candidata.identificadores & reserva.identificadores
        and propias & {_huella(s) for s in candidata.vista.segmentos}
    ]


def _huella(segmento: Mapping[str, Any]) -> tuple:
    lugar = segmento["inicio"]["lugar"]
    donde = (lugar.get("esquemaDeCodigo"), lugar["codigo"]) if lugar.get("codigo") \
        else lugar["nombre"].casefold()
    return segmento["tipo"], fecha_local(segmento["inicio"]), donde


def fecha_local(extremo: Mapping[str, Any]) -> date:
    """Fecha del extremo en su zona horaria (un ingreso a las 23 h no cambia de día en UTC).

    Con `precision: dia` el instante es la medianoche UTC de la fecha del boleto (ver «Decisiones
    de implementación» en el README): pasarlo a la zona local lo correría un día al oeste de UTC.
    """
    instante = instante_desde_texto(extremo["instante"])
    if extremo.get("precision") == "dia":
        return instante.date()
    try:
        return instante.astimezone(ZoneInfo(extremo["zonaHoraria"])).date()
    except (ZoneInfoNotFoundError, ValueError):
        return instante.date()

