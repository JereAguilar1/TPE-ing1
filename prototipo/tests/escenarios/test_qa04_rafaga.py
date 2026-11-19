"""Escenario QA-04 (ASR-2): una ráfaga de actualizaciones y un pico de lecturas a la vez, sin perder
ninguna actualización y con el panel respondiendo.

Corre contra los contenedores (`tests/escenarios/contenedores.py`), a escala de prototipo: lo que se
demuestra es el **mecanismo**, no las 9.000 peticiones por segundo de producción (ADR-0034). Mientras
varios lectores consultan el panel de `bff-web` sin pausa:

1. **ráfaga de correo:** varios viajeros reciben a la vez muchas confirmaciones reenviadas, y cada
   una llega **dos veces** (un reenvío repetido o un reintento del MTA);
2. **ráfaga del proveedor:** la aerolínea avisa a la vez dos cambios de horario por reserva, el más
   nuevo y uno viejo, mezclados y en desorden.

Medidas de QA-04 que se verifican: **cero actualizaciones perdidas** (cada reserva está una sola vez
y con el último horario informado, ADR-0013 y ADR-0014) y **p95 de lectura del panel ≤ 1.500 ms**
durante la ráfaga. El escalado en ≤ 3 min y los 30 min sostenidos quedan diseñados y no construidos
(ADR-0020, ADR-0021): Docker Compose no escala réplicas solo.
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    Viajero,
    ahora,
    esperar,
    esperar_seguimiento,
    exigir_contenedores,
    notificar_cambio,
    percentil,
    texto_utc,
)

VIAJEROS = 4
RESERVAS_POR_VIAJERO = 25
HILOS_DE_ESCRITURA = 16
LECTORES = 6
P95_LECTURA_EN_RAFAGA_MS = 1500  # QA-04 (degradación aceptada frente a los 800 ms)
CONVERGENCIA_S = 180


class Lectores:
    """Lectores del panel que no paran mientras dura la ráfaga; guardan cada demora y cada error."""

    def __init__(self, viajeros: list[Viajero]):
        self._viajeros = viajeros
        self._detener = threading.Event()
        self.demoras_ms: list[float] = []
        self.errores: list[str] = []
        self._hilos = [threading.Thread(target=self._leer, args=(i,), daemon=True)
                       for i in range(LECTORES)]

    def _leer(self, numero: int) -> None:
        with httpx.Client(timeout=15) as cliente:
            while not self._detener.is_set():
                viajero = self._viajeros[numero % len(self._viajeros)]
                inicio = time.perf_counter()
                try:
                    respuesta = cliente.get("http://localhost:18108/panel", headers=viajero.sesion)
                    if respuesta.status_code != 200:
                        self.errores.append(f"{respuesta.status_code} {respuesta.text[:120]}")
                except httpx.HTTPError as error:
                    self.errores.append(repr(error))
                self.demoras_ms.append((time.perf_counter() - inicio) * 1000)
                numero += 1

    def __enter__(self) -> "Lectores":
        for hilo in self._hilos:
            hilo.start()
        return self

    def __exit__(self, *_) -> None:
        self._detener.set()
        for hilo in self._hilos:
            hilo.join(20)


@pytest.fixture(scope="module")
def viajeros():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield [Viajero(cliente).iniciar_sesion().conectar_reenvio() for _ in range(VIAJEROS)]


def _en_paralelo(tareas) -> list[httpx.Response]:
    with ThreadPoolExecutor(HILOS_DE_ESCRITURA) as hilos:
        return list(hilos.map(lambda tarea: tarea(), tareas))


def _localizador() -> str:
    return ("R" + uuid4().hex.upper())[:6]


def test_qa04_rafaga_de_correos_y_de_cambios_del_proveedor_sin_perdidas(viajeros):
    base = ahora().replace(microsecond=0) + timedelta(days=5)
    plan = {v.correo: {_localizador(): base + timedelta(hours=3 * i)
                       for i in range(RESERVAS_POR_VIAJERO)} for v in viajeros}

    reposo = [viajeros[i % VIAJEROS].panel()[1] for i in range(40)]

    # --- 1. ráfaga de correo: cada confirmación, dos veces ------------------------------------
    with Lectores(viajeros) as lectores_correo:
        inicio = time.monotonic()
        with httpx.Client(timeout=30) as cliente:
            envios = []
            for viajero in viajeros:
                propio = Viajero(cliente, viajero.correo, viajero.token, viajero.usuario_id,
                                 viajero.alias)
                for localizador, salida in plan[viajero.correo].items():
                    envios += [lambda p=propio, l=localizador, s=salida: p.reenviar_confirmacion(l, s)] * 2
            random.shuffle(envios)
            respuestas = _en_paralelo(envios)
        enviado_correo = time.monotonic() - inicio
        for viajero in viajeros:
            esperar(lambda v=viajero: set(v.reservas()) == set(plan[v.correo]), CONVERGENCIA_S,
                    f"las {RESERVAS_POR_VIAJERO} reservas de {viajero.correo} en el panel")
        convergio_correo = time.monotonic() - inicio
    assert {r.status_code for r in respuestas} == {202}

    for viajero in viajeros:  # cero perdidas y ninguna duplicada
        reservas = viajero.reservas()
        assert set(reservas) == set(plan[viajero.correo])
        assert len({r["id"] for r in reservas.values()}) == RESERVAS_POR_VIAJERO
        for localizador, reserva in reservas.items():
            assert reserva["segmentos"][0]["inicio"]["instante"] == \
                texto_utc(plan[viajero.correo][localizador])

    # --- 2. ráfaga del proveedor: un cambio nuevo y uno viejo por reserva, en desorden --------
    for viajero in viajeros:
        for localizador in plan[viajero.correo]:
            esperar_seguimiento(localizador, 60)
    viejo, nuevo = ahora() - timedelta(minutes=5), ahora()
    final = {l: s + timedelta(hours=1) for p in plan.values() for l, s in p.items()}
    with Lectores(viajeros) as lectores_proveedor, httpx.Client(timeout=30) as cliente:
        inicio = time.monotonic()
        avisos = []
        for localizador, salida in final.items():
            avisos.append(lambda l=localizador, s=salida: notificar_cambio(cliente, l, s, nuevo))
            avisos.append(lambda l=localizador, s=salida: notificar_cambio(
                cliente, l, s - timedelta(hours=2), viejo))
        random.shuffle(avisos)
        respuestas = _en_paralelo(avisos)
        enviado_proveedor = time.monotonic() - inicio
        for viajero in viajeros:
            esperar(lambda v=viajero: all(
                r["segmentos"][0]["inicio"]["instante"] == texto_utc(final[l])
                for l, r in v.reservas().items()), CONVERGENCIA_S,
                f"los cambios de {viajero.correo} en el panel")
        convergio_proveedor = time.monotonic() - inicio
    assert {r.status_code for r in respuestas} == {202}
    for viajero in viajeros:  # el aviso viejo, llegado después, no pisó al nuevo
        assert all(not r.get("conflictosAbiertos") for r in viajero.reservas().values())

    # --- lecturas durante las ráfagas ---------------------------------------------------------
    total = VIAJEROS * RESERVAS_POR_VIAJERO
    lecturas = lectores_correo.demoras_ms + lectores_proveedor.demoras_ms
    print(f"\nQA-04 a escala de prototipo: {VIAJEROS} viajeros, {LECTORES} lectores continuos")
    print(f"  correo:    {2 * total} reenvíos ({total} reservas) en {enviado_correo:.1f} s "
          f"({2 * total / enviado_correo:.0f}/s); todo en el panel a los {convergio_correo:.1f} s")
    print(f"  proveedor: {2 * total} avisos en {enviado_proveedor:.1f} s "
          f"({2 * total / enviado_proveedor:.0f}/s); todo en el panel a los "
          f"{convergio_proveedor:.1f} s")
    print(f"  panel en reposo: p95 {percentil(reposo, 95):.0f} ms · durante las ráfagas: "
          f"{len(lecturas)} lecturas, p50 {percentil(lecturas, 50):.0f} ms, "
          f"p95 {percentil(lecturas, 95):.0f} ms (objetivo ≤ {P95_LECTURA_EN_RAFAGA_MS} ms)")
    assert lectores_correo.errores == [] and lectores_proveedor.errores == []
    assert len(lecturas) >= 50, "los lectores no llegaron a leer durante la ráfaga"
    assert percentil(lecturas, 95) <= P95_LECTURA_EN_RAFAGA_MS
