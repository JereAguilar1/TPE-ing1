"""Módulo `descargador` (vista N2, §3; ADR-0029, QA-13).

Antes de cada lectura pide a `identity-access` un token de uso acotado (`TTL ≤ 15 min`) y no lo
guarda: lo usa y lo olvida. `mail-ingest` nunca ve ni custodia la credencial del buzón.

La identidad mTLS de `mail-ingest` se simula con las cabeceras `X-Servicio-Cliente` y
`X-Instancia-Cliente`, como en el paso 7.
"""

from __future__ import annotations

import socket
from typing import Protocol
from uuid import UUID

import httpx

SERVICIO = "mail-ingest"


class BuzonNoDisponible(Exception):
    """`identity-access` no da token: el buzón ya no está `Activo` (409) o no existe (404)."""


class TokenDenegado(Exception):
    """`identity-access` respondió 403: esta instancia está bloqueada por anomalía (ADR-0029)."""


class EmisorDeTokens(Protocol):
    def token(self, buzon_id: UUID | str) -> str: ...


class EmisorDeTokensHttp:
    """`POST /buzones/{id}/token-efimero` de `identity-access` (`x-interna`)."""

    def __init__(self, url_base: str, instancia: str | None = None, timeout_s: float = 5.0):
        self._url = url_base.rstrip("/")
        self._instancia = instancia or f"{SERVICIO}-{socket.gethostname()}"
        self._timeout = timeout_s

    def token(self, buzon_id: UUID | str) -> str:
        respuesta = httpx.post(
            f"{self._url}/buzones/{buzon_id}/token-efimero",
            headers={"X-Servicio-Cliente": SERVICIO, "X-Instancia-Cliente": self._instancia},
            timeout=self._timeout)
        if respuesta.status_code in (404, 409):
            raise BuzonNoDisponible(str(buzon_id))
        if respuesta.status_code == 403:
            raise TokenDenegado(self._instancia)
        respuesta.raise_for_status()
        return respuesta.json()["token"]
