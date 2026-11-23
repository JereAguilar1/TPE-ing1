"""Módulo `puertos` de `sharing`: lo que necesita de otros elementos, detrás de interfaces.

* **Viajes** (`itinerary-lectura`): el viaje se lee siempre en nombre de su dueño, con
  `X-Usuario-Id` (ADR-0012); un viaje ajeno o inexistente es el mismo `404`.
* **Autorización** (`identity-access`, ADR-0028): `POST /autorizaciones/evaluar` decide con sus
  políticas ABAC y emite un vale JWS de 60 s ligado a la compartición; `sharing` verifica el vale
  localmente antes de mostrar el viaje.
* **Redes sociales** (E-13): el conector que publica el `ResumenPublicable`; en el prototipo, un
  complemento simulado (`complementos/red_social_simulada.py`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx
import jwt

from trotamundos.comun.bff import tiempo_para_llamar
from trotamundos.comun.errores import Problema


def _no_disponible(error: Exception) -> Problema:
    problema = Problema(503, "Servicio no disponible")
    problema.__cause__ = error
    return problema


class LectorDeViajes(Protocol):
    def viaje(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None: ...


class Autorizador(Protocol):
    def vale(self, sujeto: Mapping[str, Any], comparticion_id: UUID) -> str | None:
        """El vale de lectura de la compartición, o `None` si la política lo deniega."""
        ...


class ConectorDeRedes(Protocol):
    def publicar(self, red: str, resumen: Mapping[str, Any]) -> str:
        """Publica y devuelve la referencia de la red."""
        ...


class LectorDeViajesHttp:
    def __init__(self, url_base: str, timeout_s: float = 5.0, cliente: httpx.Client | None = None):
        self._url, self._timeout, self._http = url_base.rstrip("/"), timeout_s, cliente or httpx

    def viaje(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None:
        try:
            respuesta = self._http.get(f"{self._url}/viajes/{viaje_id}",
                                       headers={"X-Usuario-Id": str(usuario_id)},
                                       timeout=tiempo_para_llamar(self._timeout))
        except httpx.HTTPError as error:
            raise _no_disponible(error) from error
        if respuesta.status_code == 404:
            return None
        if respuesta.status_code != 200:
            raise Problema(503, "Servicio no disponible")
        return respuesta.json()


class AutorizadorHttp:
    """Pide la decisión a `identity-access` (mTLS simulado con `X-Servicio-Cliente`)."""

    def __init__(self, url_base: str, timeout_s: float = 5.0, cliente: httpx.Client | None = None):
        self._url, self._timeout, self._http = url_base.rstrip("/"), timeout_s, cliente or httpx

    def vale(self, sujeto: Mapping[str, Any], comparticion_id: UUID) -> str | None:
        try:
            respuesta = self._http.post(
                f"{self._url}/autorizaciones/evaluar",
                json={"sujeto": dict(sujeto), "accion": "leer",
                      "recurso": {"tipo": "comparticion", "id": str(comparticion_id)}},
                headers={"X-Servicio-Cliente": "sharing"},
                timeout=tiempo_para_llamar(self._timeout))
        except httpx.HTTPError as error:
            raise _no_disponible(error) from error
        if respuesta.status_code != 200:
            raise Problema(503, "Servicio no disponible")
        datos = respuesta.json()
        return datos.get("vale") if datos.get("decision") == "permitir" else None


def vale_valido(vale: str, secreto_vale: str, comparticion_id: UUID) -> bool:
    """Firma, vigencia (60 s) y ligadura a esta compartición y a la acción `leer` (ADR-0028)."""
    try:
        datos = jwt.decode(vale, secreto_vale, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return False
    return (datos.get("recurso_tipo") == "comparticion" and datos.get("accion") == "leer"
            and datos.get("recurso_id") == str(comparticion_id)
            and int(datos["exp"]) >= int(datetime.now(timezone.utc).timestamp()))
