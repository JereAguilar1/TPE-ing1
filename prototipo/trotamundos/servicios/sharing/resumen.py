"""Módulo `publicacion-resumen` de `sharing`: el `ResumenPublicable` (RF-13, ADR-0028).

Lista blanca estricta: del viaje solo salen el título, las ciudades de destino, el mes y año, y los
tipos de transporte. Localizadores, números de vuelo, horarios exactos, precios, direcciones y
correos no tienen dónde ir. Qué tipo es transporte y qué tramo es alojamiento lo dice el
`rolEnViaje` de cada descriptor (ADR-0011): este módulo no nombra tipos.
"""

from __future__ import annotations

from typing import Any, Mapping

from trotamundos.comun.modelo import RolEnViaje
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, TipoNoRegistrado

_TRANSPORTE = {RolEnViaje.TRASLADO, RolEnViaje.MOVILIDAD_LOCAL}


def _rol(registro: RegistroDeTipos, segmento: Mapping[str, Any]) -> RolEnViaje | None:
    try:
        return registro.obtener(segmento["tipo"], segmento.get("versionTipo")).rol_en_viaje
    except TipoNoRegistrado:
        return None


def del_viaje(viaje: Mapping[str, Any], registro: RegistroDeTipos) -> dict[str, Any]:
    segmentos = [s for r in viaje.get("reservas", []) for s in r.get("segmentos", [])]
    ciudades: list[str] = []
    if viaje.get("destinoPrincipal"):
        ciudades.append(viaje["destinoPrincipal"]["nombre"])
    for segmento in segmentos:
        if _rol(registro, segmento) == RolEnViaje.ALOJAMIENTO:
            nombre = segmento["fin"]["lugar"]["nombre"]
            if nombre not in ciudades:
                ciudades.append(nombre)
    transportes = sorted({s["tipo"] for s in segmentos if _rol(registro, s) in _TRANSPORTE})
    return {"tituloViaje": viaje["titulo"][:80], "ciudadesDestino": ciudades,
            "mesAnio": viaje["desde"][:7], "tiposTransporte": transportes}
