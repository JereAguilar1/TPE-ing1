"""Módulo `resumen` de `bff-mobile`: el panel compacto para el arranque en frío (ADR-0019, QA-03).

Pasa el `Panel` de `itinerary-lectura` a `PanelResumen`: por viaje, solo sus datos de cabecera, la
cantidad de reservas y el próximo tramo; por confirmar y conflictos, solo las cantidades. El cuerpo
serializado no pasa de 15 KB: si no entra, se dejan afuera los viajes más lejanos (el cliente
pide el panel completo cuando el viajero los abre). Es composición de presentación, sin reglas de
dominio (regla R4).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

LIMITE_BYTES = 15 * 1024


def _instante(segmento: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(segmento["inicio"]["instante"].replace("Z", "+00:00"))


def _proximo_segmento(viaje: Mapping[str, Any], ahora: datetime) -> dict[str, Any] | None:
    segmentos = sorted((s for r in viaje.get("reservas", []) for s in r.get("segmentos", [])),
                       key=_instante)
    futuros = [s for s in segmentos if _instante(s) >= ahora]
    return futuros[0] if futuros else None


def _viaje(viaje: Mapping[str, Any], ahora: datetime) -> dict[str, Any]:
    resumen = {k: viaje[k] for k in ("id", "titulo", "estado", "desde", "hasta")}
    resumen["cantidadReservas"] = len(viaje.get("reservas", []))
    if viaje.get("destinoPrincipal"):
        resumen["destinoPrincipal"] = viaje["destinoPrincipal"]["nombre"]
    proximo = _proximo_segmento(viaje, ahora)
    if proximo is not None:
        resumen["proximoSegmento"] = proximo
    return resumen


def tamano(cuerpo: Mapping[str, Any]) -> int:
    return len(json.dumps(cuerpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def del_panel(panel: Mapping[str, Any], ahora: datetime) -> dict[str, Any]:
    viajes = sorted(panel["viajesActivos"], key=lambda v: v["desde"])
    resumen = {"viajesActivos": [_viaje(v, ahora) for v in viajes],
               "cantidadPorConfirmar": len(panel["porConfirmar"]),
               "cantidadConflictos": len(panel["conflictosAbiertos"]),
               "versionUsuario": panel["versionUsuario"]}
    while resumen["viajesActivos"] and tamano(resumen) > LIMITE_BYTES:
        resumen["viajesActivos"].pop()  # el más lejano
    return resumen
