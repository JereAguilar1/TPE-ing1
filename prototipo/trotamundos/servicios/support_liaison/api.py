"""Módulo `api` de `support-liaison` (`contratos/openapi/support-liaison.yaml`).

Las operaciones son públicas (las expone el BFF) y llevan la sesión OIDC del viajero. Los cuerpos se
validan contra el contrato y todo error sale como `Problema` (`comun.errores`).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

from fastapi import Body, FastAPI, Header, Path
from fastapi.responses import JSONResponse, Response

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

# Tipo de medio versionado de la API pública (ADR-0027).
TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
_CUERPO_CASO = ("openapi/support-liaison.yaml#/paths/~1casos/post/requestBody/content/"
                "application~1vnd.trotamundos.v1+json/schema")


class SupportLiaisonApi(Protocol):
    """Lo que la API necesita de `support-liaison` (lo implementa `servicio`)."""

    def abrir_caso(self, usuario_id: UUID, clave: UUID,
                   cuerpo: Mapping[str, Any]) -> tuple[int, dict[str, Any]]: ...

    def leer_caso(self, usuario_id: UUID, caso_id: UUID) -> dict[str, Any]: ...

    def resolver_caso(self, usuario_id: UUID, caso_id: UUID) -> dict[str, Any]: ...

    def suprimir_usuario(self, usuario_id: UUID) -> int: ...


def crear_app(servicio: SupportLiaisonApi, contratos: Contratos, secreto_jwt: str,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="support-liaison", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    @app.post("/casos", status_code=201)
    def abrir_caso(cuerpo: dict[str, Any] = Body(...),
                   clave: UUID = Header(alias="Idempotency-Key"),
                   authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        errores = contratos.errores(_CUERPO_CASO, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": e.partition(": ")[0].removeprefix("$."), "mensaje": e.partition(": ")[2]}
                for e in errores])
        estado, caso = servicio.abrir_caso(usuario_id, clave, cuerpo)
        return JSONResponse(caso, status_code=estado, media_type=TIPO_DE_MEDIO)

    @app.get("/casos/{caso_id}")
    def ver_caso(caso_id: UUID, authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.leer_caso(usuario_id, caso_id), media_type=TIPO_DE_MEDIO)

    @app.post("/casos/{caso_id}/resolucion")
    def marcar_caso_resuelto(caso_id: UUID,
                             authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.resolver_caso(usuario_id, caso_id), media_type=TIPO_DE_MEDIO)

    @app.delete("/interno/usuarios/{usuarioId}", status_code=204)
    def suprimir_datos_de_usuario(usuario_id: UUID = Path(alias="usuarioId")) -> Response:
        """Orden de borrado de la fase 1 (ADR-0030, ADR-0042): solo desde `identity-access`."""
        servicio.suprimir_usuario(usuario_id)
        return Response(status_code=204)

    return app
