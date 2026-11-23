"""Módulo `cubeta` de `api-gateway`: límite de tasa por usuario (ADR-0020).

Cubeta de fichas de 20 (la ráfaga) que se recarga a 60 por minuto. Sin fichas, `429` con
`Retry-After` al azar entre 2 y 8 s, para que los clientes no reintenten todos juntos.
"""

from __future__ import annotations

import random
import threading

CAPACIDAD = 20
POR_SEGUNDO = 60 / 60
ESPERA_MINIMA_S, ESPERA_MAXIMA_S = 2, 8


class CubetaDeFichas:
    def __init__(self, capacidad: int = CAPACIDAD, por_segundo: float = POR_SEGUNDO,
                 azar: random.Random | None = None):
        self._capacidad = capacidad
        self._por_segundo = por_segundo
        self._azar = azar or random.Random()
        self._fichas: dict[str, tuple[float, float]] = {}  # clave → (fichas, instante)
        self._candado = threading.Lock()

    def tomar(self, clave: str, ahora: float) -> int | None:
        """`None` si pasa; si no, los segundos de `Retry-After`."""
        with self._candado:
            fichas, antes = self._fichas.get(clave, (self._capacidad, ahora))
            fichas = min(self._capacidad, fichas + (ahora - antes) * self._por_segundo)
            if fichas < 1:
                self._fichas[clave] = (fichas, ahora)
                return self._azar.randint(ESPERA_MINIMA_S, ESPERA_MAXIMA_S)
            self._fichas[clave] = (fichas - 1, ahora)
            if len(self._fichas) > 100_000:  # las cubetas llenas no hace falta guardarlas
                self._fichas = {k: v for k, v in self._fichas.items() if v[0] < self._capacidad}
            return None
