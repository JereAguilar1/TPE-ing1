"""Módulo `api` de `provider-sync`: webhooks entrantes de proveedores (`provider-sync-webhooks.yaml`)."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol

from fastapi import FastAPI, Header, Request, Response

from trotamundos.comun.errores import instalar_manejadores


class ProviderSyncApi(Protocol):
    def recibir_notificacion(self, proveedor_id: str, tipo_contenido: str | None,
                             cabeceras: Mapping[str, str], cuerpo_crudo: bytes,
                             firma_recibida: str | None,
                             traceparent: str | None = None) -> None: ...


def crear_app(servicio: ProviderSyncApi,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="provider-sync", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    @app.post("/webhooks/proveedor", status_code=202)
    async def recibir_notificacion_de_proveedor(
        request: Request,
        proveedor_id: str = Header(alias="X-Proveedor-Id"),
        firma: str | None = Header(default=None, alias="X-Firma"),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        cuerpo_crudo = await request.body()
        tipo_contenido = request.headers.get("content-type")
        cabeceras = {k.lower(): v for k, v in request.headers.items()}
        await asyncio.to_thread(
            servicio.recibir_notificacion,
            proveedor_id,
            tipo_contenido,
            cabeceras,
            cuerpo_crudo,
            firma,
            traceparent,
        )
        return Response(status_code=202)

    return app
