"""Módulo `proteccion` de `provider-sync` (ADR-0024; vista de módulos de adaptadores, QA-06).

Toda llamada a un proveedor pasa por un `ProtectorDeProveedores`, con una barrera por adaptador:

* **Cortacircuitos de ventana deslizante:** evalúa ventanas de 20 s (mínimo 10 llamadas) y abre si
  los fallos transitorios llegan al 50 % o hay 5 seguidos (apertura en ≤ 25 s). Queda abierto 30 s
  y pasa a semiabierto: 3 sondas exitosas lo cierran; un fallo lo vuelve a abrir.
* **Mamparo:** como máximo 50 llamadas simultáneas por proveedor y réplica.
* **Cuota:** el 80 % de la cuota contractual por minuto (`cuotaPorMinuto` del manifiesto), con
  alerta operativa al 70 %, repartida por prioridad: 60 % para lo vivo (webhooks y viajes en curso),
  25 % para viajes futuros y 15 % para la reconciliación de fondo. El drenaje de atrasos usa como
  mucho el 50 % de la cuota. Un `429` frena las llamadas hasta su `Retry-After`, sin contar como
  falla de salud.
* **`cola_pendientes`:** el trabajo que no se pudo hacer por una falla transitoria (o porque la
  barrera no lo dejó pasar) se guarda hasta 24 h, con espera `5 s × 2^n` (tope 15 min) y variación
  aleatoria de ±30 %.

Los errores `NoEncontrada` y `CargaInvalida` no son reintentables: pasan tal cual. El panel nunca
llama a un proveedor (las lecturas son de `itinerary`), así que un proveedor caído no lo afecta.
El estado de los cortacircuitos, del mamparo y de la cuota es de cada réplica (en memoria).
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

import psycopg

from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CuotaExcedida,
    ProveedorNoDisponible,
)

T = TypeVar("T")
_registro = logging.getLogger(__name__)

# --- parámetros de ADR-0024 ---------------------------------------------------------------------
VENTANA = timedelta(seconds=20)
MINIMO_DE_LLAMADAS = 10
UMBRAL_DE_FALLOS = 0.5
FALLOS_SEGUIDOS = 5
ABIERTO_DURANTE = timedelta(seconds=30)
SONDAS = 3
MAMPARO = 50
FRACCION_DE_CUOTA = 0.80
ALERTA_DE_CUOTA = 0.70
REPARTO = {"vivo": 0.60, "futuro": 0.25, "reconciliacion": 0.15}
FRACCION_DE_DRENAJE = 0.50
MINUTO = timedelta(minutes=1)
FRENO_SIN_RETRY_AFTER = timedelta(seconds=30)
RETENCION_DE_PENDIENTES = timedelta(hours=24)
ESPERA_BASE = timedelta(seconds=5)
ESPERA_MAXIMA = timedelta(minutes=15)
VARIACION = 0.30

CERRADO, ABIERTO, SEMIABIERTO = "Cerrado", "Abierto", "Semiabierto"

DDL = (
    """
    CREATE TABLE IF NOT EXISTS cola_pendientes (
        adaptador_id    text        NOT NULL,
        operacion       text        NOT NULL,
        argumento       text        NOT NULL,
        intentos        integer     NOT NULL,
        primer_fallo    timestamptz NOT NULL,
        proximo_intento timestamptz NOT NULL,
        ultimo_error    text        NOT NULL,
        PRIMARY KEY (adaptador_id, operacion, argumento)
    );
    CREATE INDEX IF NOT EXISTS cola_pendientes_por_vencimiento ON cola_pendientes (proximo_intento);
    """,
)


class Reintentable(Exception):
    """La llamada no se hizo o falló de forma transitoria: el trabajo va a `cola_pendientes`."""


class CortacircuitosAbierto(Reintentable):
    pass


class MamparoLleno(Reintentable):
    pass


class SinCuota(Reintentable):
    pass


class FallaTransitoria(Reintentable):
    pass


# --- cortacircuitos -----------------------------------------------------------------------------

@dataclass
class Cortacircuitos:
    estado: str = CERRADO
    abierto_desde: datetime | None = None
    seguidos: int = 0
    sondas_ok: int = 0
    sondas_en_vuelo: int = 0  # llamadas de prueba en curso mientras está semiabierto
    llamadas: deque = field(default_factory=deque)  # (instante, falló)

    def permite(self, ahora: datetime) -> bool:
        if self.estado == ABIERTO and ahora - self.abierto_desde >= ABIERTO_DURANTE:
            self.estado, self.sondas_ok = SEMIABIERTO, 0
        if self.estado == SEMIABIERTO:
            # Semiabierto deja pasar solo las sondas que faltan, no todo el tráfico (ADR-0024).
            return self.sondas_ok + self.sondas_en_vuelo < SONDAS
        return self.estado != ABIERTO

    def exito(self, ahora: datetime) -> None:
        self.seguidos = 0
        self._registrar(ahora, False)
        if self.estado == SEMIABIERTO:
            self.sondas_ok += 1
            if self.sondas_ok >= SONDAS:
                self.estado, self.llamadas = CERRADO, deque()

    def fallo(self, ahora: datetime) -> None:
        self.seguidos += 1
        self._registrar(ahora, True)
        fallos = sum(1 for _, fallo in self.llamadas if fallo)
        por_proporcion = (len(self.llamadas) >= MINIMO_DE_LLAMADAS
                          and fallos / len(self.llamadas) >= UMBRAL_DE_FALLOS)
        if self.estado == SEMIABIERTO or self.seguidos >= FALLOS_SEGUIDOS or por_proporcion:
            self.estado, self.abierto_desde = ABIERTO, ahora

    def _registrar(self, ahora: datetime, fallo: bool) -> None:
        self.llamadas.append((ahora, fallo))
        while self.llamadas and ahora - self.llamadas[0][0] > VENTANA:
            self.llamadas.popleft()


# --- cuota --------------------------------------------------------------------------------------

@dataclass
class Cuota:
    """Presupuesto por minuto de un proveedor, repartido por prioridad (ventana fija de 1 min)."""

    por_minuto: int
    desde: datetime | None = None
    usadas: dict[str, int] = field(default_factory=dict)
    drenaje: int = 0
    frenada_hasta: datetime | None = None
    alertada: bool = False

    @property
    def limite(self) -> int:
        return max(1, int(self.por_minuto * FRACCION_DE_CUOTA))

    def tomar(self, prioridad: str, ahora: datetime, drenando: bool) -> bool:
        if self.frenada_hasta is not None and ahora < self.frenada_hasta:
            return False
        if self.desde is None or ahora - self.desde >= MINUTO:
            self.desde, self.usadas, self.drenaje, self.alertada = ahora, {}, 0, False
        cupo = max(1, int(self.limite * REPARTO[prioridad]))
        if self.usadas.get(prioridad, 0) >= cupo:
            return False
        if drenando and self.drenaje >= max(1, int(self.limite * FRACCION_DE_DRENAJE)):
            return False
        self.usadas[prioridad] = self.usadas.get(prioridad, 0) + 1
        self.drenaje += drenando
        if not self.alertada and sum(self.usadas.values()) >= self.por_minuto * ALERTA_DE_CUOTA:
            self.alertada = True
            _registro.warning("Cuota del proveedor al 70 %% (%s de %s por minuto)",
                              sum(self.usadas.values()), self.por_minuto)
        return True

    def frenar(self, ahora: datetime, retry_after: int | None) -> None:
        espera = timedelta(seconds=retry_after) if retry_after else FRENO_SIN_RETRY_AFTER
        self.frenada_hasta = ahora + espera


# --- la barrera ---------------------------------------------------------------------------------

class ProtectorDeProveedores:
    """Una barrera por adaptador: cortacircuitos, mamparo y cuota (ADR-0024)."""

    def __init__(self, cuotas_por_minuto: dict[str, int]):
        self._cortacircuitos = {a: Cortacircuitos() for a in cuotas_por_minuto}
        self._mamparos = {a: threading.BoundedSemaphore(MAMPARO) for a in cuotas_por_minuto}
        self._cuotas = {a: Cuota(c) for a, c in cuotas_por_minuto.items()}
        self._candado = threading.Lock()

    def estado(self, adaptador_id: str) -> str:
        return self._cortacircuitos[adaptador_id].estado

    def llamar(self, adaptador_id: str, prioridad: str, llamada: Callable[[], T],
               ahora: datetime, *, drenando: bool = False) -> T:
        """Hace la llamada si la barrera la deja pasar. Lanza `Reintentable` si no pasó o falló de
        forma transitoria; los errores no reintentables del adaptador pasan tal cual."""
        cortacircuitos, cuota = self._cortacircuitos[adaptador_id], self._cuotas[adaptador_id]
        with self._candado:
            if not cortacircuitos.permite(ahora):
                raise CortacircuitosAbierto(adaptador_id)
            sonda = cortacircuitos.estado == SEMIABIERTO
            if sonda:
                cortacircuitos.sondas_en_vuelo += 1
        mamparo = self._mamparos[adaptador_id]
        if not mamparo.acquire(blocking=False):
            if sonda:
                with self._candado:
                    cortacircuitos.sondas_en_vuelo -= 1
            raise MamparoLleno(adaptador_id)
        try:
            # La cuota se toma recién con lugar en el mamparo: una llamada que no sale no la gasta.
            with self._candado:
                if not cuota.tomar(prioridad, ahora, drenando):
                    raise SinCuota(adaptador_id)
            try:
                resultado = llamada()
            except ProveedorNoDisponible as error:
                with self._candado:
                    cortacircuitos.fallo(ahora)
                raise FallaTransitoria(str(error)) from error
            except CuotaExcedida as error:  # freno de cuota: no es una falla de salud
                with self._candado:
                    cuota.frenar(ahora, error.retry_after)
                raise SinCuota(str(error)) from error
            with self._candado:
                cortacircuitos.exito(ahora)
            return resultado
        finally:
            mamparo.release()
            if sonda:
                with self._candado:
                    cortacircuitos.sondas_en_vuelo -= 1


# --- cola_pendientes ----------------------------------------------------------------------------

def espera(intentos: int, aleatorio: Callable[[], float] = random.random) -> timedelta:
    """`5 s × 2^n` con tope de 15 min, más o menos 30 % al azar."""
    base = min(ESPERA_BASE * (2 ** max(0, intentos - 1)), ESPERA_MAXIMA)
    return base * (1 + VARIACION * (2 * aleatorio() - 1))


def postergar(conexion: psycopg.Connection, adaptador_id: str, operacion: str, argumento: str,
              error: Exception, ahora: datetime,
              aleatorio: Callable[[], float] = random.random) -> dict[str, Any]:
    """Guarda (o reprograma) un trabajo que no se pudo hacer, con su próxima espera."""
    previa = conexion.execute(
        "SELECT intentos FROM cola_pendientes WHERE adaptador_id = %s AND operacion = %s "
        "AND argumento = %s", (adaptador_id, operacion, argumento)).fetchone()
    intentos = (previa["intentos"] if previa else 0) + 1
    return conexion.execute(
        """INSERT INTO cola_pendientes (adaptador_id, operacion, argumento, intentos,
               primer_fallo, proximo_intento, ultimo_error)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (adaptador_id, operacion, argumento) DO UPDATE
               SET intentos = EXCLUDED.intentos, proximo_intento = EXCLUDED.proximo_intento,
                   ultimo_error = EXCLUDED.ultimo_error
           RETURNING *""",
        (adaptador_id, operacion, argumento, intentos, ahora,
         ahora + espera(intentos, aleatorio), f"{type(error).__name__}: {error}")).fetchone()


def pendiente(conexion: psycopg.Connection, adaptador_id: str,
              operacion: str) -> dict[str, Any] | None:
    return conexion.execute(
        "SELECT * FROM cola_pendientes WHERE adaptador_id = %s AND operacion = %s "
        "ORDER BY proximo_intento LIMIT 1", (adaptador_id, operacion)).fetchone()


def quitar(conexion: psycopg.Connection, adaptador_id: str, operacion: str) -> None:
    conexion.execute("DELETE FROM cola_pendientes WHERE adaptador_id = %s AND operacion = %s",
                     (adaptador_id, operacion))


def purgar_vencidos(conexion: psycopg.Connection, ahora: datetime) -> int:
    """Descarta lo que lleva más de 24 h sin poder hacerse (y lo registra)."""
    vencidos = conexion.execute(
        "DELETE FROM cola_pendientes WHERE primer_fallo < %s RETURNING adaptador_id, operacion",
        (ahora - RETENCION_DE_PENDIENTES,)).fetchall()
    for fila in vencidos:
        _registro.error("Se descarta %s de %s tras 24 h de reintentos", fila["operacion"],
                        fila["adaptador_id"])
    return len(vencidos)
