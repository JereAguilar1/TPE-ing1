"""Errores HTTP en formato `application/problem+json` (RFC 9457).

Contrato: esquema `Problema` y respuestas comunes de `contratos/openapi/comun.yaml`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

TIPO_MEDIO_PROBLEMA = "application/problem+json"

# Títulos de los errores que genera el framework (el detalle original viene en inglés).
_TITULOS = {404: "No encontrado", 405: "Método no permitido"}


class Problema(Exception):
    """Error de negocio que se responde como `Problema`."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        errores: list[dict[str, str]] | None = None,
        cabeceras: dict[str, str] | None = None,
    ):
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.errores = errores
        self.cabeceras = cabeceras or {}

    def cuerpo(self, correlation_id: str | None = None) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {
            "type": f"https://errores.trotamundos.app/{self.status}",
            "title": self.title,
            "status": self.status,
        }
        if self.detail:
            cuerpo["detail"] = self.detail
        if self.errores:
            cuerpo["errores"] = self.errores
        if correlation_id:
            cuerpo["correlationId"] = correlation_id
        return cuerpo


def no_encontrado() -> Problema:
    """El mismo `404` para «no existe» y «no tenés acceso» (ADR-0028)."""
    return Problema(404, "No encontrado")


def instalar_manejadores(app: FastAPI) -> None:
    """Registra los manejadores que convierten errores en `Problema`."""

    def _correlacion(request: Request) -> str | None:
        return request.headers.get("traceparent")

    @app.exception_handler(Problema)
    async def _problema(request: Request, error: Problema) -> JSONResponse:
        return JSONResponse(
            error.cuerpo(_correlacion(request)),
            status_code=error.status,
            media_type=TIPO_MEDIO_PROBLEMA,
            headers=error.cabeceras,
        )

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, error: RequestValidationError) -> JSONResponse:
        problema = Problema(
            400,
            "Solicitud inválida",
            errores=[
                {"campo": ".".join(map(str, e["loc"])), "mensaje": e["msg"]}
                for e in error.errors()
            ],
        )
        return await _problema(request, problema)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, error: StarletteHTTPException) -> JSONResponse:
        # Errores que genera el propio framework (ruta inexistente → 404, método no permitido
        # → 405): también salen como Problema, para que ninguna respuesta escape del contrato.
        titulo = _TITULOS.get(error.status_code, str(error.detail))
        problema = Problema(error.status_code, titulo, cabeceras=dict(error.headers or {}))
        return await _problema(request, problema)
