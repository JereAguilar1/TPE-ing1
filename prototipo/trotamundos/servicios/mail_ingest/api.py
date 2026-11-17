"""Módulo `api` de `mail-ingest`: los *webhooks* entrantes (`openapi/mail-ingest-webhooks.yaml`) y
los filtros del usuario (`openapi/mail-ingest-filtros.yaml`, RF-04).

Los cuerpos se validan contra el contrato y todo error sale como `Problema` (`comun.errores`).
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

from fastapi import Body, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

# Tipo de medio versionado de la API pública (ADR-0027).
TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
_FILTROS = "openapi/mail-ingest-filtros.yaml#/components/schemas/FiltrosDeCorreo"


class MailIngestApi(Protocol):
    """Lo que la API necesita de `mail-ingest` (lo implementa `servicio`)."""

    def recibir_aviso(self, cuerpo: bytes, firma: str | None) -> None: ...

    def recibir_reenvio(self, crudo: bytes, alias: str, cliente: str | None) -> None: ...

    def leer_filtros(self, usuario_id: UUID) -> dict[str, list[str]]: ...

    def guardar_filtros(self, usuario_id: UUID, cuerpo: Mapping[str, Any]
                        ) -> dict[str, list[str]]: ...

    def catalogo_de_remitentes(self) -> list[dict[str, str]]: ...


def crear_app(servicio: MailIngestApi, contratos: Contratos, secreto_jwt: str,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="mail-ingest", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    @app.post("/webhooks/correo", status_code=202)
    async def recibir_aviso_de_correo(
        request: Request,
        _proveedor: str = Header(alias="X-Proveedor-Correo"),  # obligatoria en el contrato
        firma: str | None = Header(default=None, alias="X-Firma"),
    ) -> Response:
        # El cuerpo crudo: la firma se calcula sobre los bytes tal como llegaron. Lo demás usa
        # la base, así que corre en un hilo para no frenar el bucle de eventos.
        cuerpo = await request.body()
        await asyncio.to_thread(servicio.recibir_aviso, cuerpo, firma)
        return Response(status_code=202)

    @app.post("/webhooks/correo/reenvio", status_code=202)
    async def recibir_correo_reenviado(
        request: Request,
        alias: str = Header(alias="X-Alias-Destino"),
        cliente: str | None = Header(default=None, alias="X-Servicio-Cliente"),
    ) -> Response:
        # `message/rfc822`: el mensaje tal como lo recibió el servidor de correo propio.
        crudo = await request.body()
        await asyncio.to_thread(servicio.recibir_reenvio, crudo, alias, cliente)
        return Response(status_code=202)

    # --- filtros (RF-04) -----------------------------------------------------------------

    @app.get("/filtros-de-correo")
    def ver_filtros_de_correo(authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.leer_filtros(usuario_id), media_type=TIPO_DE_MEDIO)

    @app.put("/filtros-de-correo")
    def guardar_filtros_de_correo(cuerpo: dict[str, Any] = Body(...),
                                  authorization: str | None = Header(default=None)
                                  ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        errores = contratos.errores(_FILTROS, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": e.partition(": ")[0].removeprefix("$."), "mensaje": e.partition(": ")[2]}
                for e in errores])
        return JSONResponse(servicio.guardar_filtros(usuario_id, cuerpo), media_type=TIPO_DE_MEDIO)

    @app.get("/filtros-de-correo/catalogo")
    def ver_catalogo_de_remitentes(authorization: str | None = Header(default=None)
                                   ) -> JSONResponse:
        usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.catalogo_de_remitentes(), media_type=TIPO_DE_MEDIO)

    return app
