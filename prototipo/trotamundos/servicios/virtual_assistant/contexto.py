"""Módulo `contexto` del asistente: qué tiene el viajero en su itinerario y qué disrupciones se
conocen (ADR-0038, ADR-0040).

Lee de `itinerary-lectura`, siempre en nombre del viajero (`X-Usuario-Id`): `GET /panel` (viajes
activos, reservas por confirmar y conflictos abiertos) y `GET /viajes/{id}`. No guarda copias del
itinerario. Si `itinerary` no responde, lanza `ItinerarioNoDisponible` y el asistente lo dice, sin
adivinar.

La única proyección propia es la de `DisrupcionDetectada` (carril P1, con bandeja de entrada): por
usuario afectado, qué reservas tienen una disrupción, con qué severidad, su `disrupcionId` y, si el asistente ya la
derivó, el caso. Se purga con la misma ventana que la bandeja de entrada.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx
import psycopg

DDL = (
    """
    CREATE TABLE IF NOT EXISTS disrupcion_conocida (
        usuario_id    uuid        NOT NULL,
        reserva_id    uuid        NOT NULL,
        disrupcion_id text        NOT NULL,
        severidad     text        NOT NULL,
        proveedor     text        NOT NULL,
        descripcion   text        NOT NULL,
        recibida_en   timestamptz NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id, disrupcion_id)
    );
    CREATE INDEX IF NOT EXISTS disrupcion_conocida_por_antiguedad
        ON disrupcion_conocida (recibida_en);
    -- El caso que abrió el asistente por esta disrupción: una sola derivación por disrupción.
    ALTER TABLE disrupcion_conocida ADD COLUMN IF NOT EXISTS caso_id uuid;
    """,
)

_SEVERIDAD = {"alta": 3, "media": 2, "baja": 1}


class ItinerarioNoDisponible(Exception):
    """`itinerary-lectura` no respondió o respondió con un error."""


class LectorDeItinerario(Protocol):
    def panel(self, usuario_id: UUID | str) -> dict[str, Any]:
        """`Panel` de `comun.yaml`."""
        ...

    def viaje(self, usuario_id: UUID | str, viaje_id: UUID | str) -> dict[str, Any] | None:
        """El viaje con sus reservas, o `None` si no existe o no es del viajero."""
        ...


class LectorDeItinerarioHttp:
    def __init__(self, url_base: str, timeout_s: float = 5.0):
        self._url, self._timeout = url_base.rstrip("/"), timeout_s

    def _get(self, usuario_id: UUID | str, ruta: str) -> httpx.Response:
        try:
            respuesta = httpx.get(f"{self._url}{ruta}", headers={"X-Usuario-Id": str(usuario_id)},
                                  timeout=self._timeout)
        except httpx.HTTPError as error:
            raise ItinerarioNoDisponible(str(error)) from error
        if respuesta.status_code >= 500:
            raise ItinerarioNoDisponible(f"{ruta}: {respuesta.status_code}")
        return respuesta

    def panel(self, usuario_id: UUID | str) -> dict[str, Any]:
        respuesta = self._get(usuario_id, "/panel")
        if respuesta.status_code != 200:
            raise ItinerarioNoDisponible(f"/panel: {respuesta.status_code}")
        return respuesta.json()

    def viaje(self, usuario_id: UUID | str, viaje_id: UUID | str) -> dict[str, Any] | None:
        respuesta = self._get(usuario_id, f"/viajes/{viaje_id}")
        if respuesta.status_code == 404:
            return None
        if respuesta.status_code != 200:
            raise ItinerarioNoDisponible(f"/viajes/{viaje_id}: {respuesta.status_code}")
        return respuesta.json()


# --- proyección de disrupciones -------------------------------------------------------------

def registrar_disrupcion(conexion: psycopg.Connection, carga: Mapping[str, Any],
                         ahora: datetime) -> int:
    """Guarda, por usuario y reserva afectados, la disrupción. Repetida, no se duplica."""
    filas = [(a["usuarioId"], reserva_id, carga["disrupcionId"], carga["severidad"],
              carga["proveedor"], carga["descripcion"], ahora)
             for a in carga["afectados"] for reserva_id in a["reservaIds"]]
    with conexion.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO disrupcion_conocida (usuario_id, reserva_id, disrupcion_id, severidad,
                   proveedor, descripcion, recibida_en) VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""", filas)
    return len(filas)


def disrupcion_de(conexion: psycopg.Connection, usuario_id: UUID | str,
                  reserva_id: UUID | str) -> dict[str, Any] | None:
    """La disrupción más grave (y, a igual severidad, la más reciente) de una reserva."""
    filas = conexion.execute(
        """SELECT disrupcion_id, severidad, proveedor, descripcion, recibida_en, caso_id
           FROM disrupcion_conocida WHERE usuario_id = %s AND reserva_id = %s""",
        (str(usuario_id), str(reserva_id))).fetchall()
    if not filas:
        return None
    return max(filas, key=lambda f: (_SEVERIDAD.get(f["severidad"], 0), f["recibida_en"]))


def marcar_derivada(conexion: psycopg.Connection, usuario_id: UUID | str, disrupcion_id: str,
                    caso_id: str) -> None:
    """La disrupción ya tiene su caso: el asistente no propone derivarla otra vez."""
    conexion.execute(
        """UPDATE disrupcion_conocida SET caso_id = %s
           WHERE usuario_id = %s AND disrupcion_id = %s AND caso_id IS NULL""",
        (caso_id, str(usuario_id), disrupcion_id))


def purgar_disrupciones(conexion: psycopg.Connection, ahora: datetime, retencion: timedelta) -> int:
    return conexion.execute("DELETE FROM disrupcion_conocida WHERE recibida_en < %s",
                            (ahora - retencion,)).rowcount
