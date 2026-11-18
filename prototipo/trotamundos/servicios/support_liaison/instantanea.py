"""La instantánea del viaje que guarda cada caso (iteración 2 §5.7, UC-7).

Se toma de `GET /viajes/{id}` de `itinerary-lectura`, en nombre del viajero (`X-Usuario-Id`). Un
viaje que no existe o no es suyo responde `404`, igual que uno inexistente (ADR-0028).
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import httpx


class LectorDeViajes(Protocol):
    def viaje(self, usuario_id: UUID | str, viaje_id: UUID | str) -> dict[str, Any] | None:
        """El viaje con sus reservas (`Viaje` de `comun.yaml`), o `None` si no es del viajero."""
        ...


class LectorDeViajesHttp:
    def __init__(self, url_base: str, timeout_s: float = 5.0):
        self._url, self._timeout = url_base.rstrip("/"), timeout_s

    def viaje(self, usuario_id: UUID | str, viaje_id: UUID | str) -> dict[str, Any] | None:
        respuesta = httpx.get(f"{self._url}/viajes/{viaje_id}",
                              headers={"X-Usuario-Id": str(usuario_id)}, timeout=self._timeout)
        if respuesta.status_code == 404:
            return None
        respuesta.raise_for_status()
        return respuesta.json()
