"""Órdenes de borrado de la fase 1 de la supresión (ADR-0030, ADR-0042).

Al suprimir una cuenta, `identity-access` ordena a cada servicio operacional que borre todos los
datos del usuario con `DELETE /interno/usuarios/{usuarioId}`. Las órdenes se guardan en la misma
transacción que la fase 1 local, así que ninguna se pierde: se intentan enseguida y, si un servicio
no responde, se reintentan en el trabajo periódico con espera `5 s × 2^n` (tope 15 min). Una orden
que sigue pendiente pasadas las 24 h de la fase 1 se registra como error. Cuando un servicio
confirma (`204`), la orden se borra: solo `usuario_id` queda guardado mientras tanto.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx
import psycopg

ESPERA_BASE = timedelta(seconds=5)
ESPERA_MAXIMA = timedelta(minutes=15)
PLAZO_DE_LA_FASE_1 = timedelta(hours=24)

# Los servicios del plano operacional que guardan datos por usuario y reciben la orden (ADR-0030;
# el asistente, por ADR-0040; `sharing`, desde el paso 13).
SERVICIOS = {
    "sharing": ("TROTAMUNDOS_URL_SHARING", "http://localhost:18116"),
    "preferences": ("TROTAMUNDOS_URL_PREFERENCES", "http://localhost:18112"),
    "itinerary": ("TROTAMUNDOS_URL_ITINERARY_ESCRITURA", "http://localhost:18101"),
    "support-liaison": ("TROTAMUNDOS_URL_SUPPORT_LIAISON", "http://localhost:18105"),
    "virtual-assistant": ("TROTAMUNDOS_URL_VIRTUAL_ASSISTANT", "http://localhost:18106"),
}

DDL = (
    """
    CREATE TABLE IF NOT EXISTS orden_de_borrado (
        usuario_id      uuid        NOT NULL,
        servicio        text        NOT NULL,
        creada_en       timestamptz NOT NULL,
        intentos        integer     NOT NULL DEFAULT 0,
        proximo_intento timestamptz NOT NULL,
        ultimo_error    text,
        PRIMARY KEY (usuario_id, servicio)
    );
    """,
)

_registro = logging.getLogger(__name__)


class OrdenNoCumplida(Exception):
    """El servicio no confirmó el borrado: se reintenta."""


class EjecutorDeBorrado(Protocol):
    def borrar(self, servicio: str, usuario_id: UUID | str) -> None:
        """Ordena el borrado; lanza `OrdenNoCumplida` si el servicio no lo confirma."""
        ...


class EjecutorHttp:
    def __init__(self, urls: Mapping[str, str] | None = None, timeout_s: float = 10.0,
                 cliente: httpx.Client | None = None):
        self._urls = dict(urls) if urls is not None else {
            servicio: os.environ.get(variable, omision).rstrip("/")
            for servicio, (variable, omision) in SERVICIOS.items()}
        self._timeout = timeout_s
        self._http = cliente or httpx

    @property
    def servicios(self) -> list[str]:
        return sorted(self._urls)

    def borrar(self, servicio: str, usuario_id: UUID | str) -> None:
        try:
            respuesta = self._http.delete(f"{self._urls[servicio]}/interno/usuarios/{usuario_id}",
                                          timeout=self._timeout)
        except httpx.HTTPError as error:
            raise OrdenNoCumplida(f"{servicio}: {error}") from error
        if respuesta.status_code != 204:
            raise OrdenNoCumplida(f"{servicio}: {respuesta.status_code}")


def registrar(conexion: psycopg.Connection, usuario_id: UUID | str, servicios: list[str],
              ahora: datetime) -> None:
    for servicio in servicios:
        conexion.execute(
            """INSERT INTO orden_de_borrado (usuario_id, servicio, creada_en, proximo_intento)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (str(usuario_id), servicio, ahora, ahora))


def vencidas(conexion: psycopg.Connection, ahora: datetime) -> list[dict[str, Any]]:
    return conexion.execute(
        "SELECT * FROM orden_de_borrado WHERE proximo_intento <= %s ORDER BY creada_en, servicio",
        (ahora,)).fetchall()


def cumplida(conexion: psycopg.Connection, orden: Mapping[str, Any]) -> None:
    conexion.execute("DELETE FROM orden_de_borrado WHERE usuario_id = %s AND servicio = %s",
                     (orden["usuario_id"], orden["servicio"]))


def postergar(conexion: psycopg.Connection, orden: Mapping[str, Any], error: Exception,
              ahora: datetime) -> None:
    intentos = orden["intentos"] + 1
    espera = min(ESPERA_BASE * 2 ** (intentos - 1), ESPERA_MAXIMA)
    conexion.execute(
        """UPDATE orden_de_borrado SET intentos = %s, proximo_intento = %s, ultimo_error = %s
           WHERE usuario_id = %s AND servicio = %s""",
        (intentos, ahora + espera, str(error), orden["usuario_id"], orden["servicio"]))
    if ahora - orden["creada_en"] > PLAZO_DE_LA_FASE_1:
        _registro.error("La orden de borrado a %s lleva más de 24 h sin cumplirse", orden["servicio"])
