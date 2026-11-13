"""Módulo `viajes` (vista N2): agregado `Viaje`, agrupación y ciclo de vida (ADR-0010, RF-07, RF-08).

`Viaje` es el segundo agregado de ADR-0010. Su contenido es la **membresía**: qué reservas tiene,
referidas solo por id. Lo que necesita saber de cada una (cuándo empieza y termina, dónde, con qué
rol) lo toma de los eventos internos de `reservas` y lo guarda como `ResumenDeReserva`: este
módulo no importa a `reservas` (regla I1) y ninguna transacción escribe en los dos agregados.

La agrupación razona por **rol** y **lugar**, nunca por tipo de segmento (regla I4): el rol lo da
el descriptor del tipo (ADR-0011).

Invariantes: una reserva pertenece a lo sumo a un viaje (lo impone también la base), y una
asignación fijada por el usuario no la mueve ningún proceso automático.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trotamundos.comun.modelo import RolEnViaje, instante_a_texto, instante_desde_texto
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos

# Parámetros iniciales de la iteración 2 §5.11: supuestos a calibrar, no drivers.
MARGEN_DE_AGRUPACION = timedelta(hours=72)
MARGEN_DE_COMPLETADO = timedelta(hours=24)
GRACIA_DE_ARCHIVADO = timedelta(days=3)  # `diasDeGraciaArchivado` por omisión (preferences.yaml)
DISTANCIA_MISMA_CIUDAD_KM = 50.0


class EstadoViaje(StrEnum):
    """Ciclo de vida del viaje (iteración 2 §5.1, RF-08)."""

    PLANIFICADO = "Planificado"
    EN_CURSO = "EnCurso"
    COMPLETADO = "Completado"
    ARCHIVADO = "Archivado"
    ELIMINADO = "Eliminado"
    CANCELADO = "Cancelado"


# Donde se puede sumar una reserva nueva (regla 1 de la agrupación).
ACTIVOS = frozenset({EstadoViaje.PLANIFICADO, EstadoViaje.EN_CURSO})


class ViajeNoModificable(Exception):
    """El viaje está en un estado que no admite el comando (se responde 409)."""


# --- lugares ---------------------------------------------------------------------------------

def misma_ciudad(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Criterio de «misma ciudad» (supuesto a calibrar, iteración 2 §5.1 y §5.11): a 50 km o
    menos si los dos tienen coordenadas; si no, el mismo código; si no, el mismo nombre."""
    if a.get("coordenadas") and b.get("coordenadas"):
        return _distancia_km(a["coordenadas"], b["coordenadas"]) <= DISTANCIA_MISMA_CIUDAD_KM
    if a.get("codigo") and b.get("codigo"):
        return (a.get("esquemaDeCodigo"), a["codigo"]) == (b.get("esquemaDeCodigo"), b["codigo"])
    return a["nombre"].strip().casefold() == b["nombre"].strip().casefold()


def _distancia_km(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Distancia de gran círculo (fórmula del haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _zona(nombre: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _limites(extremo: Mapping[str, Any]) -> tuple[datetime, datetime]:
    """El intervalo que cubre un extremo. Con `precision: dia` (boleto abierto) es el día local
    entero; el instante es la medianoche UTC de esa fecha (ver el README del prototipo)."""
    instante = instante_desde_texto(extremo["instante"])
    if extremo["precision"] != "dia":
        return instante, instante
    zona = _zona(extremo["zonaHoraria"])
    dia: date = instante.date()
    return (datetime.combine(dia, time(), zona).astimezone(timezone.utc),
            datetime.combine(dia + timedelta(days=1), time(), zona).astimezone(timezone.utc))


# --- lo que el viaje sabe de cada reserva ----------------------------------------------------

@dataclass(frozen=True)
class Tramo:
    rol: RolEnViaje
    inicio: datetime
    fin: datetime
    lugar_inicio: Mapping[str, Any]
    lugar_fin: Mapping[str, Any]
    cancelado: bool


@dataclass(frozen=True)
class ResumenDeReserva:
    """Lo que `viajes` guarda de una reserva: el estado y el núcleo de sus segmentos, con la
    forma del contrato (`Reserva`), tomados de `ReservaActualizada`."""

    reserva_id: UUID
    estado: str
    segmentos: tuple[Mapping[str, Any], ...]

    @classmethod
    def desde_reserva(cls, reserva: Mapping[str, Any]) -> ResumenDeReserva:
        nucleo = ("tipo", "versionTipo", "inicio", "fin", "estado")
        return cls(UUID(reserva["id"]), reserva["estado"],
                   tuple({k: s[k] for k in nucleo} for s in reserva["segmentos"]))

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> ResumenDeReserva:
        return cls(UUID(datos["reservaId"]), datos["estado"], tuple(datos["segmentos"]))

    def a_dict(self) -> dict[str, Any]:
        return {"reservaId": str(self.reserva_id), "estado": self.estado,
                "segmentos": [dict(s) for s in self.segmentos]}

    @property
    def cancelada(self) -> bool:
        return self.estado == "Cancelada"

    def tramos(self, registro: RegistroDeTipos) -> list[Tramo]:
        tramos = []
        for s in self.segmentos:
            inicio, _ = _limites(s["inicio"])
            _, fin = _limites(s["fin"])
            tramos.append(Tramo(registro.rol(s["tipo"], s["versionTipo"]), inicio, fin,
                                s["inicio"]["lugar"], s["fin"]["lugar"],
                                self.cancelada or s["estado"] == "cancelado"))
        return sorted(tramos, key=lambda t: (t.inicio, t.fin))


@dataclass
class Miembro:
    resumen: ResumenDeReserva
    fijada: bool = False


# --- el agregado -----------------------------------------------------------------------------

@dataclass
class Viaje:
    """Raíz del agregado `Viaje` (ADR-0010). El estado se guarda, porque las transiciones por
    tiempo publican un evento una sola vez; `refrescar` lo recalcula."""

    id: UUID
    usuario_id: UUID
    creado_en: datetime
    version: int = 0
    estado: EstadoViaje = EstadoViaje.PLANIFICADO
    miembros: dict[UUID, Miembro] = field(default_factory=dict)
    completado_en: datetime | None = None
    archivado_en: datetime | None = None
    motivo_de_archivo: str | None = None
    eliminado: bool = False
    # Título, período y destino de la última vez que tuvo reservas: un viaje que se queda sin
    # ninguna los sigue publicando (el contrato de `ViajeArmado` los exige).
    derivados: dict[str, Any] = field(default_factory=dict)

    # --- membresía -----------------------------------------------------------------------

    def incorporar(self, resumen: ResumenDeReserva, *, fijada: bool = False) -> None:
        self.miembros[resumen.reserva_id] = Miembro(resumen, fijada)

    def actualizar(self, resumen: ResumenDeReserva) -> None:
        self.miembros[resumen.reserva_id].resumen = resumen

    def quitar(self, reserva_id: UUID) -> Miembro | None:
        return self.miembros.pop(reserva_id, None)

    # --- comandos del usuario ------------------------------------------------------------

    def archivar(self, ahora: datetime) -> None:
        """Archivo manual (`POST /viajes/{id}/archivo`)."""
        if self.estado in (EstadoViaje.ARCHIVADO, EstadoViaje.ELIMINADO):
            raise ViajeNoModificable(f"El viaje ya está {self.estado}")
        self.archivado_en, self.motivo_de_archivo = ahora, "manual"

    def eliminar(self) -> None:
        """El viaje sale de toda vista. Sus reservas no cambian: quedan ocultas con él."""
        if self.estado == EstadoViaje.ELIMINADO:
            raise ViajeNoModificable("El viaje ya está eliminado")
        self.eliminado = True

    # --- lo que se deriva de las reservas ------------------------------------------------

    def tramos(self, registro: RegistroDeTipos) -> list[Tramo]:
        return sorted((t for m in self.miembros.values() for t in m.resumen.tramos(registro)),
                      key=lambda t: (t.inicio, t.fin))

    def _vigentes(self, registro: RegistroDeTipos) -> list[Tramo]:
        """Los tramos activos; si todos están cancelados, todos (el viaje cancelado igual tiene
        período)."""
        tramos = self.tramos(registro)
        return [t for t in tramos if not t.cancelado] or tramos

    def periodo(self, registro: RegistroDeTipos) -> tuple[datetime, datetime]:
        tramos = self._vigentes(registro)
        return min(t.inicio for t in tramos), max(t.fin for t in tramos)

    def destino_principal(self, registro: RegistroDeTipos) -> Mapping[str, Any]:
        """Adonde se va: el fin del primer traslado; si no hay, el alojamiento más largo; si no,
        el primer lugar del viaje (supuesto, iteración 2 §5.1: el título se deriva)."""
        tramos = self._vigentes(registro)
        traslados = [t for t in tramos if t.rol == RolEnViaje.TRASLADO]
        if traslados:
            return traslados[0].lugar_fin
        alojamientos = [t for t in tramos if t.rol == RolEnViaje.ALOJAMIENTO]
        if alojamientos:
            return max(alojamientos, key=lambda t: t.fin - t.inicio).lugar_inicio
        return tramos[0].lugar_inicio

    def titulo(self, registro: RegistroDeTipos) -> str:
        return f"Viaje a {self.destino_principal(registro)['nombre']}"

    def llegadas(self, registro: RegistroDeTipos) -> list[Mapping[str, Any]]:
        """Los lugares donde el viajero está o va a estar: el fin de cada traslado y los lugares
        del alojamiento y la movilidad local (para la continuidad geográfica)."""
        lugares: list[Mapping[str, Any]] = []
        for t in self._vigentes(registro):
            lugares.append(t.lugar_fin)
            if t.rol != RolEnViaje.TRASLADO:
                lugares.append(t.lugar_inicio)
        return lugares

    # --- ciclo de vida (RF-08) -----------------------------------------------------------

    def estado_calculado(self, ahora: datetime, registro: RegistroDeTipos) -> EstadoViaje:
        if self.eliminado or not self.miembros:
            return EstadoViaje.ELIMINADO  # un viaje sin reservas sale de toda vista
        if self.archivado_en is not None:
            return EstadoViaje.ARCHIVADO
        if all(m.resumen.cancelada for m in self.miembros.values()):
            return EstadoViaje.CANCELADO
        if self.completado_en is not None:
            return EstadoViaje.COMPLETADO
        desde, _ = self.periodo(registro)
        return EstadoViaje.EN_CURSO if ahora >= desde else EstadoViaje.PLANIFICADO

    def refrescar(self, ahora: datetime, registro: RegistroDeTipos) -> None:
        if self.miembros:
            desde, hasta = self.periodo(registro)
            self.derivados = {"titulo": self.titulo(registro), "desde": instante_a_texto(desde),
                              "hasta": instante_a_texto(hasta),
                              "destinoPrincipal": dict(self.destino_principal(registro))}
        self.estado = self.estado_calculado(ahora, registro)

    def avanzar(self, ahora: datetime, registro: RegistroDeTipos,
                gracia: timedelta = GRACIA_DE_ARCHIVADO) -> list[str]:
        """Aplica las transiciones por tiempo que vencieron; devuelve `completado` y/o
        `archivado`. `Completado`: pasó el margen tras el fin del último tramo activo.
        `Archivado`: pasó la gracia desde `Completado`."""
        transiciones = []
        self.refrescar(ahora, registro)
        if self.estado in ACTIVOS and ahora >= self._fin_activo(registro) + MARGEN_DE_COMPLETADO:
            self.completado_en = ahora
            transiciones.append("completado")
            self.refrescar(ahora, registro)
        if self.estado == EstadoViaje.COMPLETADO and ahora >= self.completado_en + gracia:
            self.archivado_en, self.motivo_de_archivo = ahora, "automatico"
            transiciones.append("archivado")
            self.refrescar(ahora, registro)
        return transiciones

    def proxima_transicion(self, registro: RegistroDeTipos,
                           gracia: timedelta = GRACIA_DE_ARCHIVADO) -> datetime | None:
        """Cuándo tiene que volver a mirarlo el trabajo programado (nada si no cambia solo)."""
        if self.estado == EstadoViaje.PLANIFICADO:
            return self.periodo(registro)[0]
        if self.estado == EstadoViaje.EN_CURSO:
            return self._fin_activo(registro) + MARGEN_DE_COMPLETADO
        if self.estado == EstadoViaje.COMPLETADO:
            return self.completado_en + gracia
        return None

    def _fin_activo(self, registro: RegistroDeTipos) -> datetime:
        return self.periodo(registro)[1]

    # --- representación ------------------------------------------------------------------

    def datos_publicos(self) -> dict[str, Any]:
        """Carga de `ViajeArmado` (contrato AsyncAPI), tal como quedó en el último `refrescar`."""
        return {"viajeId": str(self.id), **self.derivados, "estado": self.estado.value,
                "reservaIds": sorted(str(r) for r in self.miembros), "version": self.version}

    def huella(self) -> tuple:
        """Lo que publica `ViajeArmado` sin la versión: si cambia, el viaje cambió."""
        datos = {k: v for k, v in self.datos_publicos().items() if k != "version"}
        return tuple(sorted((k, repr(v)) for k, v in datos.items()))
