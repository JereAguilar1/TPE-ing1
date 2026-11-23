"""Módulo `modos` de `api-gateway`: la máquina automática de modos operativos (ADR-0020,
iteración 3 §5.3).

| Modo | Entra con | Sale con |
|---|---|---|
| `Normal` | — | — |
| `PicoElevado` | ≥ 1.400 req/s durante 60 s | < 1.100 req/s y p95 < 500 ms durante 10 min |
| `DisrupcionMasiva` | ≥ 2.500 req/s o p95 > 900 ms durante 30 s | < 1.800 req/s durante 15 min (vuelve a `PicoElevado`) |

La carga y el p95 se miden sobre los últimos 10 s de las peticiones que pasan por el *gateway*.
Los umbrales se pueden cambiar al construirla (las pruebas usan valores chicos). El retraso de P2 y
las colas del *broker*, que la iteración 3 también usa, no los ve el *gateway*: no entran.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

NORMAL, PICO_ELEVADO, DISRUPCION_MASIVA = "Normal", "PicoElevado", "DisrupcionMasiva"
VENTANA_S = 10.0


@dataclass(frozen=True)
class Umbrales:
    pico_rps: float = 1400
    pico_entrada_s: float = 60
    pico_salida_rps: float = 1100
    pico_salida_p95_s: float = 0.5
    pico_salida_s: float = 600
    disrupcion_rps: float = 2500
    disrupcion_p95_s: float = 0.9
    disrupcion_entrada_s: float = 30
    disrupcion_salida_rps: float = 1800
    disrupcion_salida_s: float = 900


class MaquinaDeModos:
    def __init__(self, umbrales: Umbrales | None = None):
        self.umbrales = umbrales or Umbrales()
        self.modo = NORMAL
        self._muestras: deque[tuple[float, float]] = deque()  # (instante, latencia)
        self._desde: dict[str, float | None] = {}
        self._candado = threading.Lock()

    def registrar(self, ahora: float, latencia_s: float) -> str:
        with self._candado:
            self._muestras.append((ahora, latencia_s))
            return self._evaluar(ahora)

    def evaluar(self, ahora: float) -> str:
        with self._candado:
            return self._evaluar(ahora)

    def medidas(self, ahora: float) -> tuple[float, float]:
        """(peticiones por segundo, p95 en segundos) de la ventana."""
        while self._muestras and self._muestras[0][0] < ahora - VENTANA_S:
            self._muestras.popleft()
        latencias = sorted(m[1] for m in self._muestras)
        p95 = latencias[min(len(latencias) - 1, int(0.95 * len(latencias)))] if latencias else 0.0
        return len(latencias) / VENTANA_S, p95

    def _sostenida(self, nombre: str, condicion: bool, ahora: float, durante_s: float) -> bool:
        if not condicion:
            self._desde[nombre] = None
            return False
        if self._desde.get(nombre) is None:
            self._desde[nombre] = ahora
        return ahora - self._desde[nombre] >= durante_s

    def _evaluar(self, ahora: float) -> str:
        u = self.umbrales
        rps, p95 = self.medidas(ahora)
        disrupcion = self._sostenida("disrupcion", rps >= u.disrupcion_rps or p95 > u.disrupcion_p95_s,
                                     ahora, u.disrupcion_entrada_s)
        pico = self._sostenida("pico", rps >= u.pico_rps, ahora, u.pico_entrada_s)
        if self.modo == NORMAL:
            self._cambiar(DISRUPCION_MASIVA if disrupcion else PICO_ELEVADO if pico else NORMAL)
        elif self.modo == PICO_ELEVADO:
            if disrupcion:
                self._cambiar(DISRUPCION_MASIVA)
            elif self._sostenida("salida_pico", rps < u.pico_salida_rps and p95 < u.pico_salida_p95_s,
                                 ahora, u.pico_salida_s):
                self._cambiar(NORMAL)
        elif self._sostenida("salida_disrupcion", rps < u.disrupcion_salida_rps, ahora,
                             u.disrupcion_salida_s):
            self._cambiar(PICO_ELEVADO)
        return self.modo

    def _cambiar(self, modo: str) -> None:
        if modo != self.modo:
            self.modo = modo
            for nombre in ("salida_pico", "salida_disrupcion"):
                self._desde[nombre] = None
