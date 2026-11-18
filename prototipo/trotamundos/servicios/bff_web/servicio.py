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

from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.servicios.bff_web import api, clientes


class BffWeb:
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
        self._contratos = contratos or contratos_por_omision()
        self._lector = lector or clientes.LectorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_LECTURA", "http://localhost:18102")
        )
        self._escritor = escritor or clientes.EscritorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_ESCRITURA", "http://localhost:18101")
        )
        self._asistente = asistente or clientes.ClienteDeAsistenteHttp(
            os.environ.get("TROTAMUNDOS_URL_VIRTUAL_ASSISTANT", "http://localhost:18106")
        )
        self._secreto_jwt = (
            secreto_jwt
            or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
            or secrets.token_hex(32)
        )

    # --- lecturas de itinerario (itinerary-lectura) --------------------------------------

    def leer_panel(
        self,
        usuario_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.leer_panel(
            usuario_id, min_version=min_version, traceparent=traceparent
        )

    def listar_viajes(
        self,
        usuario_id: UUID,
        *,
        estado: str | None = None,
        cursor: str | None = None,
        limite: int = 20,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.listar_viajes(
            usuario_id,
            estado=estado,
            cursor=cursor,
            limite=limite,
            traceparent=traceparent,
        )

    def leer_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.leer_viaje(
            usuario_id, viaje_id, min_version=min_version, traceparent=traceparent
        )

    def listar_tipos_de_segmento(
        self, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]:
        return self._lector.listar_tipos_de_segmento(traceparent=traceparent)

    # --- comandos de itinerario (itinerary-escritura) ------------------------------------

    def eliminar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.eliminar_viaje(
            usuario_id, viaje_id, traceparent=traceparent
        )

    def archivar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.archivar_viaje(
            usuario_id, viaje_id, traceparent=traceparent
        )

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.mover_reserva(
            usuario_id, viaje_id, reserva_id, traceparent=traceparent
        )

    def crear_reserva(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self._escritor.crear_reserva(
            usuario_id, clave, cuerpo, traceparent=traceparent
        )

    def editar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.editar_reserva(
            usuario_id, reserva_id, cuerpo, traceparent=traceparent
        )

    def eliminar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.eliminar_reserva(
            usuario_id, reserva_id, traceparent=traceparent
        )

    def confirmar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.confirmar_reserva(
            usuario_id, reserva_id, cuerpo, traceparent=traceparent
        )

    def resolver_conflicto(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        conflicto_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.resolver_conflicto(
            usuario_id,
            reserva_id,
            conflicto_id,
            cuerpo,
            traceparent=traceparent,
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
