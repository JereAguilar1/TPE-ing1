"""Adaptador OSDM simulado para el ferrocarril de ejemplo (`adaptador-ferrocarril-simulado`).

Es el paso 3 de la guía de extensión de QA-15 (iteración 4): incorporar trenes agrega este
complemento y su entrada en `catalogo_adaptadores.yaml`, sin tocar `provider-sync` ni el dominio.
Traduce el modelo externo simulado del operador (JSON al estilo OSDM: reservas con viajes, tren,
coche, asiento y andén) al modelo canónico. Ningún tipo ni campo del operador cruza la frontera de
anticorrupción (regla R3, ADR-0006).
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CargaInvalida,
    NoEncontrada,
    ProveedorNoDisponible,
)

# Estaciones que conoce el operador simulado, con coordenadas para que `itinerary` reconozca la
# misma ciudad que un hotel o un vuelo (criterio de «misma ciudad», iteración 2 §5.1).
_ESTACIONES: dict[str, tuple[str, str, str, float, float]] = {
    "RET": ("Retiro", "AR", "America/Argentina/Buenos_Aires", -34.5915, -58.3746),
    "CON": ("Constitución", "AR", "America/Argentina/Buenos_Aires", -34.6276, -58.3812),
    "MDQ": ("Mar del Plata", "AR", "America/Argentina/Buenos_Aires", -37.9926, -57.5848),
    "ROS": ("Rosario Norte", "AR", "America/Argentina/Cordoba", -32.9324, -60.6516),
    "ATO": ("Madrid Atocha", "ES", "Europe/Madrid", 40.4066, -3.6892),
    "BCN": ("Barcelona Sants", "ES", "Europe/Madrid", 41.3793, 2.1404),
}
_ESTADOS = {"CONFIRMED": "confirmado", "CANCELLED": "cancelado"}
_DETALLE = (("coach", "coche"), ("seat", "asiento"), ("platform", "anden"), ("class", "clase"))


def _instante_utc(valor: Any) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise CargaInvalida("Instante ausente o inválido en la carga del operador")
    try:
        instante = datetime.fromisoformat(valor.strip())
    except ValueError as error:
        raise CargaInvalida(f"Fecha inválida del operador: {valor!r}") from error
    if instante.tzinfo is None:
        raise CargaInvalida("El instante del operador debe incluir zona horaria")
    return instante.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _extremo(parada: Any) -> dict[str, Any]:
    if not isinstance(parada, Mapping) or parada.get("station") not in _ESTACIONES:
        raise CargaInvalida(f"Estación desconocida en la carga OSDM: {parada!r}")
    codigo = parada["station"]
    nombre, pais, zona, lat, lon = _ESTACIONES[codigo]
    return {"instante": _instante_utc(parada.get("time")), "precision": "instante",
            "zonaHoraria": zona,
            "lugar": {"nombre": nombre, "codigo": codigo, "esquemaDeCodigo": "interno",
                      "pais": pais, "zonaHoraria": zona,
                      "coordenadas": {"lat": lat, "lon": lon}}}


def _traducir_viaje(operador: str, indice: int, viaje: Any) -> dict[str, Any]:
    if not isinstance(viaje, Mapping):
        raise CargaInvalida("Cada viaje OSDM debe ser un objeto")
    numero = str(viaje.get("trainNumber") or "").strip()
    if not re.fullmatch(r"[A-Z0-9-]{1,8}", numero):
        raise CargaInvalida(f"Número de tren inválido: {numero!r}")
    estado = _ESTADOS.get(str(viaje.get("status") or "CONFIRMED").upper())
    if estado is None:
        raise CargaInvalida(f"Estado OSDM desconocido: {viaje.get('status')!r}")
    inicio, fin = _extremo(viaje.get("origin")), _extremo(viaje.get("destination"))
    if fin["instante"] <= inicio["instante"]:
        raise CargaInvalida("La llegada debe ser posterior a la salida")
    detalle: dict[str, Any] = {"numeroDeTren": numero}
    for externo, canonico in _DETALLE:
        valor = viaje.get(externo)
        if isinstance(valor, str) and valor.strip():
            detalle[canonico] = valor.strip()
    return {"tipo": "tren", "versionTipo": 1, "orden": indice, "inicio": inicio, "fin": fin,
            "operador": operador, "referencia": f"{operador}{numero}", "estado": estado,
            "detalle": detalle}


def _traducir_reserva(reserva: Any, *, id_evento: str, emitido: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(reserva, Mapping):
        raise CargaInvalida("Cada reserva OSDM debe ser un objeto")
    referencia = str(reserva.get("bookingRef") or "").strip()
    operador = str(reserva.get("carrier") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,8}", referencia):
        raise CargaInvalida(f"Referencia de reserva OSDM inválida: {referencia!r}")
    if not re.fullmatch(r"[A-Z]{2,4}", operador):
        raise CargaInvalida(f"Código de operador OSDM inválido: {operador!r}")
    viajes = reserva.get("trips")
    if not isinstance(viajes, list) or not viajes:
        raise CargaInvalida("La reserva OSDM debe contener al menos un viaje")
    segmentos = [_traducir_viaje(operador, i, v) for i, v in enumerate(viajes)]
    cancelada = str(reserva.get("status") or "").upper() == "CANCELLED" or all(
        s["estado"] == "cancelado" for s in segmentos)
    if cancelada:
        for segmento in segmentos:
            segmento["estado"] = "cancelado"
    return referencia, {
        "fuente": "proveedor",
        "idDeFuente": f"osdm:{operador}:{referencia}:{id_evento}",
        "versionDeFuente": _instante_utc(emitido),
        "cancelada": cancelada,
        "identificadores": [{"emisor": f"ferrocarril:{operador}", "codigo": referencia}],
        "segmentos": segmentos,
    }


class AdaptadorFerrocarrilSimulado:
    """Complemento `adaptador-ferrocarril-simulado` que implementa `AdaptadorDeProveedor` v1.0."""

    def __init__(self) -> None:
        self._reservas: dict[str, dict[str, Any]] = {}
        self._cambios: list[tuple[str, dict[str, Any]]] = []
        self._fallo_simulado: Exception | None = None

    def simular_fallo(self, error: Exception | None) -> None:
        """Permite inyectar `CuotaExcedida` o `ProveedorNoDisponible` en pruebas."""
        self._fallo_simulado = error

    def registrar_reserva_nativa(self, reserva: Mapping[str, Any], *, emitido: str,
                                 id_evento: str = "alta") -> None:
        """Registra una reserva o un cambio nativo en el operador, para `sondear` y
        `obtener_reserva`."""
        referencia, observacion = _traducir_reserva(reserva, id_evento=id_evento, emitido=emitido)
        self._reservas[referencia] = copy.deepcopy(observacion)
        self._cambios.append((observacion["versionDeFuente"],
                              {"referencia": referencia, "observacion": copy.deepcopy(observacion)}))

    def _verificar_disponibilidad(self, credencial: Mapping[str, str]) -> None:
        if not isinstance(credencial, Mapping) or not credencial.get("valor"):
            raise ProveedorNoDisponible("Credencial del operador ausente")
        if self._fallo_simulado is not None:
            raise self._fallo_simulado

    # --- Operaciones del contrato AdaptadorDeProveedor -----------------------------------

    def obtener_reserva(self, credencial: Mapping[str, str], referencia: str) -> dict[str, Any]:
        self._verificar_disponibilidad(credencial)
        if referencia not in self._reservas:
            raise NoEncontrada(f"La reserva {referencia!r} no existe en el operador")
        return copy.deepcopy(self._reservas[referencia])

    def traducir_notificacion(self, cabeceras: Mapping[str, str],
                              cuerpo: Any) -> list[dict[str, Any]]:
        if not isinstance(cuerpo, Mapping):
            raise CargaInvalida("El operador notifica en JSON")
        evento = str(cuerpo.get("eventId") or "").strip()
        reservas = cuerpo.get("bookings")
        if not evento or not isinstance(reservas, list) or not reservas:
            raise CargaInvalida("Faltan eventId o bookings en la notificación OSDM")
        salida = []
        for reserva in reservas:
            referencia, observacion = _traducir_reserva(reserva, id_evento=evento,
                                                        emitido=cuerpo.get("issuedAt"))
            self._reservas[referencia] = copy.deepcopy(observacion)
            salida.append({"referencia": referencia, "observacion": observacion})
        return salida

    def sondear(self, credencial: Mapping[str, str], desde: str) -> list[dict[str, Any]]:
        self._verificar_disponibilidad(credencial)
        instante_desde = _instante_utc(desde)
        return [copy.deepcopy(cambio) for emitido, cambio in self._cambios
                if emitido >= instante_desde]

    def detectar_disrupcion(self, cambio: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(cambio, Mapping) or "observacion" not in cambio or "referencia" not in cambio:
            raise CargaInvalida("CambioObservado inválido para detectarDisrupcion")
        observacion = cambio["observacion"]
        if observacion.get("cancelada") is not True:
            return None
        segmentos = observacion.get("segmentos") or []
        tren = segmentos[0].get("referencia", cambio["referencia"]) if segmentos else cambio["referencia"]
        return {"id": f"disr-{observacion.get('idDeFuente')}", "severidad": "alta",
                "descripcion": f"Cancelación informada por el operador para el tren {tren}",
                "referenciasAfectadas": [str(cambio["referencia"])]}


def crear_adaptador() -> AdaptadorFerrocarrilSimulado:
    return AdaptadorFerrocarrilSimulado()
