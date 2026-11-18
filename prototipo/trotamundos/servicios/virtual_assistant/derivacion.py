"""Módulo `derivacion` del asistente: cuándo y cómo pasarle el caso a la agencia (ADR-0039).

Evalúa los cuatro disparadores (cambio ante el proveedor, el viajero lo pide, dos «no entendidos»
seguidos y una disrupción de severidad alta sobre la reserva por la que pregunta), arma la síntesis
del caso y lo abre con `POST /casos` de `support-liaison`, con la sesión del viajero y una
`Idempotency-Key` derivada de la acción propuesta: confirmar dos veces abre un solo caso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import httpx

from trotamundos.servicios.virtual_assistant.catalogo import Mensajes

DERIVAR = "derivarALaAgencia"
MOTIVO_OTRO = "otro"
LARGO_MAXIMO = 2000  # `descripcion` de `POST /casos`
NO_ENTENDIDOS_PARA_DERIVAR = 2
_CONSULTAS = frozenset({"estadoDelViaje", "proximoTramo"})
_TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"


@dataclass(frozen=True)
class Disparador:
    nombre: str  # cambioAnteProveedor, pedirAgencia, noEntendido o disrupcion
    motivo: str
    disrupcion: Mapping[str, Any] | None = None

    @property
    def id_de_causa(self) -> str | None:
        return self.disrupcion["disrupcion_id"] if self.disrupcion else None


class SinAgencia(Exception):
    """`422` de `support-liaison`: el viajero no tiene agencia preferida."""


class ViajeNoEncontrado(Exception):
    """`404` de `support-liaison`: el viaje ya no existe o no es del viajero."""


class SoporteNoDisponible(Exception):
    """`support-liaison` no respondió o respondió con un error inesperado."""


class AbridorDeCasos(Protocol):
    def abrir(self, authorization: str, clave: str, cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        """`POST /casos` con la sesión del viajero; devuelve el `Caso`."""
        ...


class AbridorDeCasosHttp:
    def __init__(self, url_base: str, timeout_s: float = 10.0):
        self._url, self._timeout = url_base.rstrip("/"), timeout_s

    def abrir(self, authorization: str, clave: str, cuerpo: Mapping[str, Any]) -> dict[str, Any]:
        try:
            respuesta = httpx.post(f"{self._url}/casos", json=dict(cuerpo), timeout=self._timeout,
                                   headers={"Authorization": authorization, "Idempotency-Key": clave,
                                            "Content-Type": _TIPO_DE_MEDIO})
        except httpx.HTTPError as error:
            raise SoporteNoDisponible(str(error)) from error
        if respuesta.status_code == 422:
            raise SinAgencia()
        if respuesta.status_code == 404:
            raise ViajeNoEncontrado()
        if respuesta.status_code != 201:
            raise SoporteNoDisponible(f"POST /casos: {respuesta.status_code} {respuesta.text}")
        return respuesta.json()


# --- disparadores -----------------------------------------------------------------------------

def disparador(intencion: str, entidades: Mapping[str, str], no_entendidos: int,
               disrupcion: Mapping[str, Any] | None) -> Disparador | None:
    """El disparador de derivación de este turno, si hay uno (los cuatro de ADR-0039).

    `no_entendidos` ya cuenta este turno; `disrupcion` es la de la reserva por la que pregunta.
    Una consulta solo propone derivar ante una disrupción alta, y nunca abre un caso sola.
    """
    if intencion == "cambioAnteProveedor":
        return Disparador(intencion, entidades.get("motivo", MOTIVO_OTRO))
    if intencion == "pedirAgencia":
        return Disparador(intencion, MOTIVO_OTRO)
    if intencion == "noEntendido" and no_entendidos >= NO_ENTENDIDOS_PARA_DERIVAR:
        return Disparador(intencion, MOTIVO_OTRO)
    if intencion in _CONSULTAS and disrupcion is not None and disrupcion["severidad"] == "alta":
        # DisrupcionDetectada no dice si es una cancelación o una demora: `otro`, con la
        # descripción de la disrupción en la del caso.
        return Disparador("disrupcion", MOTIVO_OTRO, disrupcion)
    return None


def viaje_para_el_caso(viaje_en_foco: str | None,
                       viajes: Sequence[Mapping[str, Any]]) -> tuple[str | None, str]:
    """`POST /casos` pide un viaje: el de la conversación o, si tiene uno solo, ese.
    Devuelve el viaje y `"elegido"`, o `None` y `"ninguno"` o `"varios"`."""
    if viaje_en_foco is not None:
        return viaje_en_foco, "elegido"
    if len(viajes) == 1:
        return viajes[0]["id"], "elegido"
    return None, "ninguno" if not viajes else "varios"


# --- síntesis y caso --------------------------------------------------------------------------

def sintesis(mensajes: Mensajes, motivo: Disparador, pedido: str,
             reserva: Mapping[str, str] | None = None) -> str:
    """La `descripcion` del caso: qué pasó, qué reserva y qué pide el viajero, sin copiar la
    conversación entera (≤ 2.000 caracteres)."""
    if motivo.nombre == "disrupcion":
        texto = mensajes.texto("sintesis.disrupcion", proveedor=motivo.disrupcion["proveedor"],
                               descripcion=motivo.disrupcion["descripcion"], pedido=pedido)
    else:
        texto = mensajes.texto(f"sintesis.{motivo.nombre}", pedido=pedido)
    if reserva is not None:
        texto += mensajes.texto("sintesis.reserva", **reserva)
    return texto if len(texto) <= LARGO_MAXIMO else texto[:LARGO_MAXIMO - 1] + "…"


def cuerpo_del_caso(datos: Mapping[str, Any]) -> dict[str, Any]:
    """El cuerpo de `POST /casos` a partir de los datos de la acción propuesta."""
    cuerpo = {"viajeId": datos["viajeId"], "motivo": datos["motivo"],
              "descripcion": datos["descripcion"]}
    for campo in ("reservaId", "idDeCausa"):
        if datos.get(campo):
            cuerpo[campo] = datos[campo]
    return cuerpo


def abrir_caso(abridor: AbridorDeCasos, authorization: str, accion_id: str,
               datos: Mapping[str, Any]) -> dict[str, Any]:
    """Abre el caso, idempotente por la acción. Lanza `SinAgencia`, `ViajeNoEncontrado` o
    `SoporteNoDisponible`."""
    return abridor.abrir(authorization, accion_id, cuerpo_del_caso(datos))
