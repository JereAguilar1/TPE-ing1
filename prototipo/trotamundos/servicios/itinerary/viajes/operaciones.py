"""Operaciones sobre viajes: agrupación (RF-07), asignación del usuario y ciclo de vida (RF-08).

Reglas de agrupación (iteración 2 §5.1), por rol y lugar, nunca por tipo:

1. Una reserva que entra al itinerario se une al viaje activo cuyo período, ampliado por el
   margen (72 h), la contiene o la toca, **y** con el que tiene continuidad geográfica: empieza en
   la misma ciudad que una llegada del viaje (el fin de un traslado, o un alojamiento o una
   movilidad local). Si hay varios, el más cercano en el tiempo.
2. Si ninguno cumple, se crea un viaje nuevo.
3. Una asignación hecha por el usuario queda fijada: ningún proceso automático la mueve.
4. Título y período se derivan de las reservas.

La asignación automática se decide **una vez**, cuando la reserva entra al itinerario: si después
cambia, el viaje recalcula su período y su título, pero la reserva no cambia de viaje. Las
reservas `PorConfirmar` no entran (banda media, ADR-0015) y las `Descartada` salen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Protocol
from uuid import UUID, uuid4

from trotamundos.comun.eventos import Causa, Evento
from trotamundos.comun.modelo import instante_a_texto
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.itinerary.viajes import (
    ACTIVOS,
    GRACIA_DE_ARCHIVADO,
    MARGEN_DE_AGRUPACION,
    EstadoViaje,
    ResumenDeReserva,
    Viaje,
    misma_ciudad,
)

PRODUCTOR = "itinerary"
FUERA_DEL_ITINERARIO = frozenset({"PorConfirmar", "Descartada"})


class ReservaSinViaje(LookupError):
    """La reserva no está en ningún viaje (no existe, está por confirmar o descartada)."""


class ViajeInexistente(LookupError):
    """El viaje no existe, es de otro usuario o está eliminado."""


class RepositorioDeViajes(Protocol):
    def obtener(self, usuario_id: UUID, viaje_id: UUID) -> Viaje | None: ...

    def de_reserva(self, usuario_id: UUID, reserva_id: UUID) -> Viaje | None: ...

    def activos(self, usuario_id: UUID) -> list[Viaje]: ...

    def guardar(self, viaje: Viaje) -> None: ...


class Sesion:
    """Los viajes que toca una operación. Al cerrar, cada uno se refresca, sube de versión si
    cambió lo que publica y se guarda; de ahí salen los eventos (ADR-0010: una transacción, un
    agregado; acá, solo viajes)."""

    def __init__(self, repositorio: RepositorioDeViajes, registro: RegistroDeTipos,
                 usuario_id: UUID, ahora: datetime, causa: Causa,
                 nuevo_id: Callable[[], UUID] = uuid4, gracia: timedelta = GRACIA_DE_ARCHIVADO):
        self.repositorio, self.registro, self.usuario_id = repositorio, registro, usuario_id
        self.ahora, self.causa, self.nuevo_id, self.gracia = ahora, causa, nuevo_id, gracia
        self._antes: dict[UUID, tuple | None] = {}
        self._tocados: dict[UUID, Viaje] = {}
        self._transiciones: list[tuple[Viaje, str]] = []

    def tocar(self, viaje: Viaje, *, nuevo: bool = False) -> Viaje:
        if viaje.id not in self._tocados:
            self._tocados[viaje.id] = viaje
            self._antes[viaje.id] = None if nuevo else viaje.huella()
        return viaje

    def transicion(self, viaje: Viaje, nombre: str) -> None:
        self._transiciones.append((viaje, nombre))

    def cerrar(self) -> list[Evento]:
        """Guarda lo que cambió y devuelve `ViajeArmado`, `ViajeCompletado` y `ViajeArchivado`."""
        eventos = []
        for viaje in self._tocados.values():
            viaje.refrescar(self.ahora, self.registro)
            if viaje.huella() == self._antes[viaje.id]:
                continue
            viaje.version += 1
            self.repositorio.guardar(viaje)
            eventos.append(self._evento("ViajeArmado", viaje.datos_publicos()))
        for viaje, nombre in self._transiciones:
            if nombre == "completado":
                eventos.append(self._evento("ViajeCompletado", {
                    "viajeId": str(viaje.id), "completadoEn": instante_a_texto(viaje.completado_en)}))
            elif nombre == "archivado":
                eventos.append(self._evento("ViajeArchivado", {
                    "viajeId": str(viaje.id), "archivadoEn": instante_a_texto(viaje.archivado_en),
                    "motivo": viaje.motivo_de_archivo}))
        return eventos

    def _evento(self, tipo: str, carga: dict[str, Any]) -> Evento:
        c = self.causa
        return Evento.nuevo(tipo, carga, productor=PRODUCTOR, usuario_id=str(self.usuario_id),
                            region=c.region, id_de_causa=c.id_de_causa, traceparent=c.traceparent,
                            id_de_correlacion=c.id_de_correlacion)


# --- operaciones -----------------------------------------------------------------------------

def aplicar_reserva(sesion: Sesion, reserva: Mapping[str, Any],
                    absorbidas: Iterable[str] = ()) -> Viaje | None:
    """Refleja en los viajes un cambio de una reserva (la carga de `ReservaActualizada`).
    Devuelve el viaje en que quedó, o `None` si está fuera del itinerario."""
    repositorio, usuario = sesion.repositorio, sesion.usuario_id
    for absorbida in absorbidas:  # unificadas: dejan de existir
        viaje = repositorio.de_reserva(usuario, UUID(absorbida))
        if viaje is not None:
            sesion.tocar(viaje).quitar(UUID(absorbida))

    reserva_id = UUID(reserva["id"])
    actual = repositorio.de_reserva(usuario, reserva_id)
    if reserva["estado"] in FUERA_DEL_ITINERARIO:
        if actual is not None:
            sesion.tocar(actual).quitar(reserva_id)
        return None

    resumen = ResumenDeReserva.desde_reserva(reserva)
    if actual is not None:
        sesion.tocar(actual).actualizar(resumen)  # la asignación no se reevalúa
        return actual
    destino = elegir_viaje(resumen, repositorio.activos(usuario), sesion.registro, sesion.ahora)
    if destino is None:
        destino = sesion.tocar(Viaje(sesion.nuevo_id(), usuario, sesion.ahora), nuevo=True)
    sesion.tocar(destino).incorporar(resumen)
    return destino


def elegir_viaje(resumen: ResumenDeReserva, candidatos: Iterable[Viaje],
                 registro: RegistroDeTipos, ahora: datetime) -> Viaje | None:
    """Regla 1 de la agrupación; `None` si la reserva va a un viaje nuevo (regla 2)."""
    tramos = [t for t in resumen.tramos(registro) if not t.cancelado] or resumen.tramos(registro)
    inicio, fin = min(t.inicio for t in tramos), max(t.fin for t in tramos)
    origen = tramos[0].lugar_inicio
    elegibles = []
    for viaje in candidatos:
        if not viaje.miembros or viaje.estado_calculado(ahora, registro) not in ACTIVOS:
            continue
        desde, hasta = viaje.periodo(registro)
        if inicio > hasta + MARGEN_DE_AGRUPACION or fin < desde - MARGEN_DE_AGRUPACION:
            continue
        if not any(misma_ciudad(origen, llegada) for llegada in viaje.llegadas(registro)):
            continue
        distancia = max(timedelta(0), inicio - hasta, desde - fin)
        elegibles.append((distancia, viaje.creado_en, str(viaje.id), viaje))
    return min(elegibles, key=lambda e: e[:3])[3] if elegibles else None


def mover(sesion: Sesion, reserva_id: UUID, viaje_id: UUID) -> Viaje:
    """El usuario pone la reserva en un viaje: la asignación queda fijada (regla 3)."""
    repositorio, usuario = sesion.repositorio, sesion.usuario_id
    origen = repositorio.de_reserva(usuario, reserva_id)
    destino = repositorio.obtener(usuario, viaje_id)
    if origen is None:
        raise ReservaSinViaje(str(reserva_id))
    if destino is None or destino.estado == EstadoViaje.ELIMINADO:
        raise ViajeInexistente(str(viaje_id))
    miembro = sesion.tocar(origen).quitar(reserva_id)
    sesion.tocar(destino).incorporar(miembro.resumen, fijada=True)
    return destino


def archivar(sesion: Sesion, viaje_id: UUID) -> Viaje:
    viaje = _visible(sesion, viaje_id)
    sesion.tocar(viaje).archivar(sesion.ahora)
    sesion.transicion(viaje, "archivado")
    return viaje


def eliminar(sesion: Sesion, viaje_id: UUID) -> Viaje:
    viaje = _visible(sesion, viaje_id)
    sesion.tocar(viaje).eliminar()
    return viaje


def avanzar(sesion: Sesion, viaje: Viaje) -> None:
    """Transiciones por tiempo de un viaje (las corre el trabajo programado)."""
    sesion.tocar(viaje)
    for nombre in viaje.avanzar(sesion.ahora, sesion.registro, sesion.gracia):
        sesion.transicion(viaje, nombre)


def _visible(sesion: Sesion, viaje_id: UUID) -> Viaje:
    viaje = sesion.repositorio.obtener(sesion.usuario_id, viaje_id)
    if viaje is None or viaje.estado == EstadoViaje.ELIMINADO:
        raise ViajeInexistente(str(viaje_id))
    return viaje
