"""El elemento `bff-web`: arma los adaptadores HTTP y expone la API pública para `app-web`
(`contratos/openapi/bff-web.yaml`, ADR-0005, ADR-0034).

Es un componente sin estado propio (vista C&C N1): delega las lecturas en `itinerary-lectura`,
los comandos en `itinerary-escritura` y las conversaciones en `virtual-assistant`.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Mapping
from uuid import UUID

from fastapi import FastAPI

from trotamundos.comun.bff import ComposicionDeItinerarioHttp
from trotamundos.comun.config import _variable
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.servicios.bff_web import api, clientes


class BffWeb(ComposicionDeItinerarioHttp):
    """Composición de `itinerary-lectura`, `itinerary-escritura` y `virtual-assistant`."""

    def __init__(
        self,
        *,
        contratos: Contratos | None = None,
        lector: clientes.LectorDeItinerario | None = None,
        escritor: clientes.EscritorDeItinerario | None = None,
        asistente: clientes.ClienteDeAsistente | None = None,
        secreto_jwt: str | None = None,
    ):
        super().__init__(lector=lector, escritor=escritor)
        self._contratos = contratos or contratos_por_omision()
        self._asistente = asistente or clientes.ClienteDeAsistenteHttp(
            os.environ.get("TROTAMUNDOS_URL_VIRTUAL_ASSISTANT", "http://localhost:18106")
        )
        self._secreto_jwt = (
            secreto_jwt
            or _variable("TROTAMUNDOS_JWT_SECRETO")
            or secrets.token_hex(32)
        )

    # --- asistente virtual (virtual-assistant) -------------------------------------------

    def abrir_sesion_asistente(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._asistente.abrir_sesion(
            authorization, clave, cuerpo, traceparent=traceparent
        )

    def ver_sesion_asistente(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._asistente.ver_sesion(
            authorization, sesion_id, traceparent=traceparent
        )

    def enviar_mensaje_asistente(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._asistente.enviar_mensaje(
            authorization, sesion_id, clave, cuerpo, traceparent=traceparent
        )

    def app(self) -> FastAPI:
        return api.crear_app(self, self._contratos, self._secreto_jwt)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.bff_web.servicio:crear_app`."""
    return BffWeb().app()
