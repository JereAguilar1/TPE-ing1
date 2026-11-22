"""Módulo `api` de `preferences` (`contratos/openapi/preferences.yaml`).

`GET` y `PUT /preferencias` llevan la sesión OIDC del viajero; el cuerpo se valida contra el
contrato. `DELETE /interno/usuarios/{usuarioId}` es la orden de borrado de la fase 1 (ADR-0042).
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

TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
_PREFERENCIAS = "openapi/preferences.yaml#/components/schemas/Preferencias"


class PreferencesApi(Protocol):
    def leer(self, usuario_id: UUID) -> dict[str, Any]: ...

    def guardar(self, usuario_id: UUID, preferencias: Mapping[str, Any]) -> dict[str, Any]: ...

    def suprimir_usuario(self, usuario_id: UUID) -> int: ...


def crear_app(servicio: PreferencesApi, contratos: Contratos, secreto_jwt: str,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="preferences", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    @app.get("/preferencias")
    def leer_preferencias(authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.leer(usuario_id), media_type=TIPO_DE_MEDIO)

    @app.put("/preferencias")
    def guardar_preferencias(cuerpo: dict[str, Any] = Body(...),
                             authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        errores = contratos.errores(_PREFERENCIAS, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": e.partition(": ")[0].removeprefix("$."), "mensaje": e.partition(": ")[2]}
                for e in errores])
        return JSONResponse(servicio.guardar(usuario_id, cuerpo), media_type=TIPO_DE_MEDIO)

    @app.delete("/interno/usuarios/{usuarioId}", status_code=204)
    def suprimir_datos_de_usuario(usuario_id: UUID = Path(alias="usuarioId")) -> Response:
        """Orden de borrado de la fase 1 (ADR-0030, ADR-0042): solo desde `identity-access`."""
        servicio.suprimir_usuario(usuario_id)
        return Response(status_code=204)

    return app
