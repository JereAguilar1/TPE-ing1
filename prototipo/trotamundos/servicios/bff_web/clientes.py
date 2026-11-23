"""Adaptadores HTTP de `bff-web` (ADR-0005, ADR-0021, ADR-0034).

Los de `itinerary-lectura` e `itinerary-escritura` los comparte con `bff-mobile` y están en
`comun.bff`; acá queda el de `virtual-assistant`, que solo usa `bff-web`. Reenvía la sesión OIDC
(`Authorization`), la clave de idempotencia, el contexto de traza, el plazo restante y el modo
operativo. No contiene reglas de dominio (regla R4).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx

from trotamundos.comun.bff import (
    EscritorDeItinerario,
    EscritorDeItinerarioHttp,
    LectorDeItinerario,
    LectorDeItinerarioHttp,
    _lanzar_si_error,
    _no_disponible,
    cabeceras_propagadas,
    tiempo_para_llamar,
)

__all__ = ["ClienteDeAsistente", "ClienteDeAsistenteHttp", "EscritorDeItinerario",
           "EscritorDeItinerarioHttp", "LectorDeItinerario", "LectorDeItinerarioHttp"]

_CABECERA_TRAZA = "traceparent"


class ClienteDeAsistente(Protocol):
    def abrir_sesion(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def ver_sesion(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def enviar_mensaje(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...


class ClienteDeAsistenteHttp:
    def __init__(
        self,
        url_base: str,
        timeout_s: float = 5.0,
        cliente: httpx.Client | None = None,
    ):
        self._url = url_base.rstrip("/")
        self._timeout = timeout_s
        self._http = cliente or httpx

    def _enviar(
        self,
        metodo: str,
        ruta: str,
        authorization: str,
        *,
        cuerpo: Mapping[str, Any] | None = None,
        clave: UUID | None = None,
        traceparent: str | None = None,
    ) -> httpx.Response:
        cabeceras = {"Authorization": authorization}
        if clave is not None:
            cabeceras["Idempotency-Key"] = str(clave)
        if traceparent:
            cabeceras[_CABECERA_TRAZA] = traceparent
        cabeceras.update(cabeceras_propagadas())
        try:
            respuesta = self._http.request(
                metodo,
                f"{self._url}{ruta}",
                json=dict(cuerpo) if cuerpo is not None else None,
                headers=cabeceras,
                timeout=tiempo_para_llamar(self._timeout),
            )
        except httpx.HTTPError as error:
            raise _no_disponible() from error
        _lanzar_si_error(respuesta)
        return respuesta

    def abrir_sesion(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            "/asistente/sesiones",
            authorization,
            cuerpo=cuerpo,
            clave=clave,
            traceparent=traceparent,
        ).json()

    def ver_sesion(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "GET",
            f"/asistente/sesiones/{sesion_id}",
            authorization,
            traceparent=traceparent,
        ).json()

    def enviar_mensaje(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/asistente/sesiones/{sesion_id}/mensajes",
            authorization,
            cuerpo=cuerpo,
            clave=clave,
            traceparent=traceparent,
        ).json()
