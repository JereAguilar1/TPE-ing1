"""Módulo `acciones` del asistente: lo que cambia el itinerario, siempre en dos pasos (ADR-0038).

Arma la corrección de una reserva (el tramo con su inicio y su fin corridos lo mismo) y los
problemas menores (confirmar o descartar una reserva por confirmar, resolver un conflicto), y los
ejecuta en `itinerary-escritura` solo cuando el viajero confirmó la propuesta. Usa operaciones que
`itinerary` ya exponía, en nombre del viajero (`X-Usuario-Id`), y respeta su control de versión: un
`409` no se pisa, se vuelve a proponer.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

# Tipos de acción del contrato (`TipoDeAccion`) que cambian el itinerario.
CORREGIR = "corregirReserva"
CONFIRMAR = "confirmarReserva"
DESCARTAR = "descartarReserva"
RESOLVER = "resolverConflicto"
_CAMPOS_DE_SEGMENTO = ("id", "tipo", "inicio", "fin", "operador", "referencia", "detalle")


class ReservaCambiada(Exception):
    """`409` de `itinerary`: la reserva cambió, ya no está por confirmar o el conflicto se cerró."""


class ReservaInexistente(Exception):
    """`404` de `itinerary`: la reserva ya no existe o no es del viajero."""


class EscrituraNoDisponible(Exception):
    """`itinerary-escritura` no respondió o respondió con un error inesperado."""


class EscritorDeItinerario(Protocol):
    def editar(self, usuario_id: UUID | str, reserva_id: str, cuerpo: Mapping[str, Any]) -> None:
        """`PUT /reservas/{id}`."""
        ...

    def confirmar(self, usuario_id: UUID | str, reserva_id: str, decision: str) -> None:
        """`POST /reservas/{id}/confirmacion`."""
        ...

    def resolver(self, usuario_id: UUID | str, reserva_id: str, conflicto_id: str,
                 cuerpo: Mapping[str, Any]) -> None:
        """`POST /reservas/{id}/conflictos/{cid}/resolucion`."""
        ...


class EscritorDeItinerarioHttp:
    def __init__(self, url_base: str, timeout_s: float = 5.0):
        self._url, self._timeout = url_base.rstrip("/"), timeout_s

    def _enviar(self, metodo: str, usuario_id: UUID | str, ruta: str,
                cuerpo: Mapping[str, Any]) -> None:
        try:
            respuesta = httpx.request(metodo, f"{self._url}{ruta}", json=dict(cuerpo),
                                      headers={"X-Usuario-Id": str(usuario_id)},
                                      timeout=self._timeout)
        except httpx.HTTPError as error:
            raise EscrituraNoDisponible(str(error)) from error
        if respuesta.status_code == 409:
            raise ReservaCambiada(ruta)
        if respuesta.status_code == 404:
            raise ReservaInexistente(ruta)
        if respuesta.status_code != 200:
            raise EscrituraNoDisponible(f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text}")

    def editar(self, usuario_id: UUID | str, reserva_id: str, cuerpo: Mapping[str, Any]) -> None:
        self._enviar("PUT", usuario_id, f"/reservas/{reserva_id}", cuerpo)

    def confirmar(self, usuario_id: UUID | str, reserva_id: str, decision: str) -> None:
        self._enviar("POST", usuario_id, f"/reservas/{reserva_id}/confirmacion",
                     {"decision": decision})

    def resolver(self, usuario_id: UUID | str, reserva_id: str, conflicto_id: str,
                 cuerpo: Mapping[str, Any]) -> None:
        self._enviar("POST", usuario_id, f"/reservas/{reserva_id}/conflictos/{conflicto_id}/resolucion",
                     cuerpo)


# --- corrección del itinerario ----------------------------------------------------------------

def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


def _texto(instante: datetime) -> str:
    return instante.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def segmento_de(reserva: Mapping[str, Any], segmento_id: str | None) -> Mapping[str, Any] | None:
    return next((s for s in reserva.get("segmentos", []) if s["id"] == segmento_id), None)


def nuevo_inicio(segmento: Mapping[str, Any], fecha: date | None, hora: time | None) -> datetime:
    """El inicio del tramo con la fecha o la hora que dijo el viajero, en la zona del lugar. Un
    tramo que vale todo el día (`precision: dia`) solo cambia de fecha."""
    zona = ZoneInfo(segmento["inicio"]["zonaHoraria"])
    local = _instante(segmento["inicio"]["instante"]).astimezone(zona)
    if fecha is not None:
        local = local.replace(year=fecha.year, month=fecha.month, day=fecha.day)
    if hora is not None and segmento["inicio"]["precision"] == "instante":
        local = local.replace(hour=hora.hour, minute=hora.minute, second=0, microsecond=0)
    return datetime.combine(local.date(), local.time(), zona).astimezone(timezone.utc)


def edicion_corregida(reserva: Mapping[str, Any], segmento_id: str,
                      inicio: datetime) -> dict[str, Any] | None:
    """`EdicionReserva` con el tramo corrido a `inicio` (y su fin, lo mismo), con la `version`
    leída. `None` si el tramo ya empieza ahí."""
    segmentos = []
    cambia = False
    for segmento in reserva["segmentos"]:
        copia = {k: segmento[k] for k in _CAMPOS_DE_SEGMENTO if k in segmento}
        if segmento["id"] == segmento_id:
            corrimiento = inicio - _instante(segmento["inicio"]["instante"])
            cambia = corrimiento.total_seconds() != 0
            copia["inicio"] = {**segmento["inicio"], "instante": _texto(inicio)}
            copia["fin"] = {**segmento["fin"],
                            "instante": _texto(_instante(segmento["fin"]["instante"]) + corrimiento)}
        segmentos.append(copia)
    return {"version": reserva["version"], "segmentos": segmentos} if cambia else None


# --- ejecución, solo con la confirmación -------------------------------------------------------

def ejecutar(escritor: EscritorDeItinerario, usuario_id: UUID | str, tipo: str,
             datos: Mapping[str, Any]) -> None:
    """Ejecuta una acción confirmada. Lanza `ReservaCambiada`, `ReservaInexistente` o
    `EscrituraNoDisponible`."""
    if tipo == CORREGIR:
        escritor.editar(usuario_id, datos["reservaId"], datos["edicion"])
    elif tipo in (CONFIRMAR, DESCARTAR):
        escritor.confirmar(usuario_id, datos["reservaId"],
                           "confirmar" if tipo == CONFIRMAR else "descartar")
    elif tipo == RESOLVER:
        cuerpo = {"eleccion": datos["eleccion"]}
        if datos["eleccion"] == "aceptarFuente":
            cuerpo["fuente"] = datos["fuente"]
        escritor.resolver(usuario_id, datos["reservaId"], datos["conflictoId"], cuerpo)
    else:
        raise ValueError(f"{tipo} no cambia el itinerario")
