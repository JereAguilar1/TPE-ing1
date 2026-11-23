"""Módulo `rutas` de `api-gateway`: a qué servicio va cada petición, según `api-gateway.yaml`.

Las rutas publicadas salen de `paths` (con sus `$ref` resueltos) y el destino, de `x-backend`. Si
el destino es `bff-web | bff-mobile`, elige por el tipo de cliente (`X-Tipo-Cliente: movil`). Una
operación con `security: []` en su contrato no exige sesión. Lo que no está en el contrato no se
publica (`404`): las operaciones internas y los *webhooks* tienen su propio camino.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from trotamundos.comun.bff import operaciones_de
from trotamundos.comun.contratos import Contratos

CONTRATO = "openapi/api-gateway.yaml"
WEB, MOVIL = "web", "movil"


@dataclass(frozen=True)
class Destino:
    servicio: str
    publica: bool


def _patron(plantilla: str) -> re.Pattern[str]:
    comodin = plantilla.endswith("*")
    cuerpo = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(plantilla.rstrip("*")))
    return re.compile(f"^{cuerpo}{'.*' if comodin else ''}$")


class Rutas:
    def __init__(self, contratos: Contratos):
        documento = contratos.documento(CONTRATO)
        self._operaciones: list[tuple[re.Pattern[str], str, dict[str, Any]]] = [
            (_patron(ruta), ruta, item)
            for ruta, item in operaciones_de(contratos, CONTRATO)["paths"].items()]
        # el más específico primero: «/viajes/{id}/comparticiones*» antes que «/viajes*»
        self._backends = sorted(
            ((_patron(clave), valor.partition("→")[0].strip())
             for clave, valor in documento["x-backend"].items()),
            key=lambda par: -len(par[0].pattern))

    def destino(self, metodo: str, ruta: str, tipo_de_cliente: str) -> Destino | None:
        """`None` si el contrato no publica esa operación."""
        for patron, _, item in self._operaciones:
            if patron.match(ruta):
                operacion = item.get(metodo.lower())
                if not isinstance(operacion, dict):
                    return None
                break
        else:
            return None
        servicio = next(nombre for patron, nombre in self._backends if patron.match(ruta))
        if "|" in servicio:  # bff-web | bff-mobile
            servicio = "bff-mobile" if tipo_de_cliente == MOVIL else "bff-web"
        return Destino(servicio, operacion.get("security") == [])
