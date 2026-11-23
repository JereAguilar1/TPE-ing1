"""Módulo `regiones` de `api-gateway`: salud por región y a qué región va cada usuario (paso 16;
ADR-0002, ADR-0018, QA-05).

- **Región de cada usuario:** la primaria viene en el token (`region_primaria`, ADR-0018 §1); la
  de respaldo es determinista por `hash(usuario_id)` entre las demás. Si la primaria está caída,
  el usuario va a la de respaldo; si también lo está, a cualquier región sana.
- **Detección:** el *gateway* consulta la salud de cada región cada `INTERVALO_S` y la declara
  caída después de `FALLOS_PARA_CAIDA` fallos seguidos: a lo sumo `3 × 2 s` más el tiempo de
  espera de cada consulta, dentro de los 30 s de QA-05. Al declararla, lo deja en el registro
  como alerta para el operador.
- **Sin vuelta automática:** una región caída queda fuera hasta que se reinicia el *gateway*.
  ADR-0018 §4 pide que primero se sincronice pasivamente con lo escrito en la de respaldo, y esa
  reintroducción no se construye en el prototipo.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Iterable
from uuid import UUID

FALLOS_PARA_CAIDA = 3
INTERVALO_S = 2.0
ESPERA_S = 1.0

_registro = logging.getLogger(__name__)


class SaludDeRegiones:
    def __init__(self, regiones: Iterable[str], fallos_para_caida: int = FALLOS_PARA_CAIDA):
        self._fallos = {region: 0 for region in regiones}
        self._umbral = fallos_para_caida
        self.caidas: dict[str, float] = {}  # región → instante en que se la declaró caída

    @property
    def regiones(self) -> list[str]:
        return sorted(self._fallos)

    def registrar(self, region: str, sana: bool, ahora: float) -> None:
        if region in self.caidas:
            return
        self._fallos[region] = 0 if sana else self._fallos[region] + 1
        if self._fallos[region] >= self._umbral:
            self.caidas[region] = ahora
            _registro.error("ALERTA: la región %s no responde; su tráfico va a la de respaldo",
                            region)

    def sana(self, region: str) -> bool:
        return region in self._fallos and region not in self.caidas


def region_de_respaldo(usuario_id: UUID | str, primaria: str, regiones: Iterable[str]) -> str:
    otras = sorted(r for r in regiones if r != primaria)
    if not otras:
        return primaria
    indice = int(hashlib.sha256(str(usuario_id).encode()).hexdigest(), 16) % len(otras)
    return otras[indice]


def region_para(usuario_id: UUID | str | None, primaria: str | None, salud: SaludDeRegiones,
                region_local: str) -> str | None:
    """La región que atiende al usuario; `None` si no hay ninguna sana. Sin usuario (operaciones
    públicas), la del *gateway*."""
    if primaria not in salud.regiones:
        primaria = region_local
    if salud.sana(primaria):
        return primaria
    if usuario_id is not None:
        respaldo = region_de_respaldo(usuario_id, primaria, salud.regiones)
        if salud.sana(respaldo):
            return respaldo
    return next((r for r in salud.regiones if salud.sana(r)), None)
