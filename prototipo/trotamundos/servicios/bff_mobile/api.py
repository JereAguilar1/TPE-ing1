"""Módulo `api` de `bff-mobile` (`contratos/openapi/bff-mobile.yaml`, ADR-0005, ADR-0019).

Expone a `app-movil` las mismas operaciones de itinerario que `bff-web` (`comun.bff`) y
`GET /panel/resumen`, la variante compacta con `ETag` y `Cache-Control: private, no-cache`. No
expone el asistente: `bff-mobile.yaml` no lo declara.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from fastapi import FastAPI, Header
from fastapi.responses import Response

from trotamundos.comun.bff import (
    ComposicionDeItinerario,
    instalar_plazo,
    instalar_rutas_de_itinerario,
    respuesta_con_etag,
    verificar_rutas_contra_contrato,
)
from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

_CONTRATO = "openapi/bff-mobile.yaml"


class BffMobileApi(ComposicionDeItinerario, Protocol):
    def leer_panel_resumen(self, usuario_id: UUID, *, min_version: int | None = None,
                           traceparent: str | None = None) -> dict[str, Any]: ...


def crear_app(servicio: BffMobileApi, contratos: Contratos, secreto_jwt: str) -> FastAPI:
    app = FastAPI(title="bff-mobile", openapi_url=None, docs_url=None, redoc_url=None)
    instalar_manejadores(app)
    instalar_plazo(app)
    instalar_rutas_de_itinerario(app, servicio, contratos, secreto_jwt)

    @app.get("/panel/resumen")
    def obtener_panel_resumen(
        authorization: str | None = Header(default=None),
        min_version: int | None = Header(default=None, alias="X-Min-Version", ge=0),
        _accept_language: str | None = Header(default=None, alias="Accept-Language"),
        traceparent: str | None = Header(default=None),
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        resumen = servicio.leer_panel_resumen(usuario_id, min_version=min_version,
                                              traceparent=traceparent)
        return respuesta_con_etag(resumen, if_none_match)

    verificar_rutas_contra_contrato(app, contratos, _CONTRATO)
    return app
