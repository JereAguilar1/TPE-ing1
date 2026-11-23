"""Módulo `api` de `bff-web` (`contratos/openapi/bff-web.yaml`, ADR-0005).

Expone las operaciones públicas para `app-web`: panel, viajes, reservas, catálogo de tipos de
segmento y conversaciones con el asistente virtual (`virtual-assistant`, ADR-0034).

Responsabilidades de la capa de composición (regla R4, ADR-0005, ADR-0018, ADR-0019, ADR-0027):
- Verifica la sesión OIDC del viajero en todas las rutas autenticadas (`comun.sesion`).
- Valida cuerpos y parámetros de consulta contra `contratos/openapi/bff-web.yaml` (ADR-0009).
- Sirve toda representación con `application/vnd.trotamundos.v1+json` (ADR-0027).
- En las lecturas de datos del usuario fija `Cache-Control: private, no-cache` y valida `ETag` /
  `If-None-Match` (`304 Not Modified`); en `GET /tipos-de-segmento`,
  `Cache-Control: public, max-age=300, stale-while-revalidate=3600` (ADR-0019).
- Propaga `X-Version-Usuario` en las mutaciones y `X-Min-Version` en las lecturas (ADR-0018).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from uuid import UUID

from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse

from trotamundos.comun.bff import (
    CACHE_PRIVADA,
    TIPO_DE_MEDIO,
    ComposicionDeItinerario,
    instalar_plazo,
    instalar_rutas_de_itinerario,
    validador,
    verificar_rutas_contra_contrato,
)
from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

_CONTRATO = "openapi/bff-web.yaml"
_CABECERA_CACHE = "Cache-Control"
_CABECERA_IDEMPOTENCIA = "Idempotency-Key"

_CUERPO = f"{_CONTRATO}#/paths/{{ruta}}/post/requestBody/content/application~1vnd.trotamundos.v1+json/schema"
CUERPO_SESION = _CUERPO.format(ruta="~1asistente~1sesiones")
CUERPO_MENSAJE = "openapi/virtual-assistant.yaml#/components/schemas/MensajeDelViajero"


class BffWebApi(ComposicionDeItinerario, Protocol):
    """Lo que la API necesita de `bff-web` (lo implementa `servicio`)."""

    def abrir_sesion_asistente(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def ver_sesion_asistente(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def enviar_mensaje_asistente(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...


def crear_app(servicio: BffWebApi, contratos: Contratos, secreto_jwt: str) -> FastAPI:
    app = FastAPI(title="bff-web", openapi_url=None, docs_url=None, redoc_url=None)
    instalar_manejadores(app)

    instalar_plazo(app)
    validar = validador(contratos)
    instalar_rutas_de_itinerario(app, servicio, contratos, secreto_jwt)

    # --- asistente virtual (Opción B, ADR-0005, ADR-0034) --------------------------------

    @app.post("/asistente/sesiones", status_code=201)
    def abrir_sesion(
        cuerpo: dict[str, Any] | None = Body(default=None),
        clave: UUID = Header(alias=_CABECERA_IDEMPOTENCIA),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_de_sesion(authorization, secreto_jwt)
        cuerpo = cuerpo or {}
        validar(CUERPO_SESION, cuerpo)
        sesion = servicio.abrir_sesion_asistente(
            str(authorization), clave, cuerpo, traceparent=traceparent
        )
        return JSONResponse(sesion, status_code=201, media_type=TIPO_DE_MEDIO)

    @app.get("/asistente/sesiones/{sid}")
    def ver_sesion(
        sid: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_de_sesion(authorization, secreto_jwt)
        sesion = servicio.ver_sesion_asistente(
            str(authorization), sid, traceparent=traceparent
        )
        return JSONResponse(
            sesion,
            media_type=TIPO_DE_MEDIO,
            headers={_CABECERA_CACHE: CACHE_PRIVADA},
        )

    @app.post("/asistente/sesiones/{sid}/mensajes")
    def enviar_mensaje(
        sid: UUID,
        cuerpo: dict[str, Any] = Body(...),
        clave: UUID = Header(alias=_CABECERA_IDEMPOTENCIA),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_de_sesion(authorization, secreto_jwt)
        validar(CUERPO_MENSAJE, cuerpo)
        respuesta = servicio.enviar_mensaje_asistente(
            str(authorization), sid, clave, cuerpo, traceparent=traceparent
        )
        return JSONResponse(respuesta, media_type=TIPO_DE_MEDIO)

    verificar_rutas_contra_contrato(app, contratos, _CONTRATO)
    return app
