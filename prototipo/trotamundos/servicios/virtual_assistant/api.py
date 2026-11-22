"""Módulo `api` del asistente (`contratos/openapi/virtual-assistant.yaml`).

Solo la usan los BFF, que reenvían la sesión OIDC del viajero (ADR-0007, ADR-0028): el asistente
actúa siempre en su nombre. Los cuerpos se validan contra el contrato y todo error sale como
`Problema` (`comun.errores`).
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

_CONTRATO = "openapi/virtual-assistant.yaml"
_CUERPO_SESION = (f"{_CONTRATO}#/paths/~1asistente~1sesiones/post/requestBody/content/"
                  "application~1json/schema")
_CUERPO_MENSAJE = f"{_CONTRATO}#/components/schemas/MensajeDelViajero"


class AsistenteApi(Protocol):
    """Lo que la API necesita del asistente (lo implementa `servicio`)."""

    def abrir_sesion(self, usuario_id: UUID, clave: UUID,
                     cuerpo: Mapping[str, Any]) -> dict[str, Any]: ...

    def ver_sesion(self, usuario_id: UUID, sesion_id: UUID) -> dict[str, Any]: ...

    def enviar_mensaje(self, usuario_id: UUID, authorization: str, sesion_id: UUID, clave: UUID,
                       cuerpo: Mapping[str, Any]) -> dict[str, Any]: ...

    def suprimir_usuario(self, usuario_id: UUID) -> int: ...


def _validar(contratos: Contratos, referencia: str, cuerpo: Any) -> None:
    errores = contratos.errores(referencia, cuerpo)
    if errores:
        raise Problema(400, "Solicitud inválida", errores=[
            {"campo": e.partition(": ")[0].removeprefix("$."), "mensaje": e.partition(": ")[2]}
            for e in errores])


def crear_app(servicio: AsistenteApi, contratos: Contratos, secreto_jwt: str,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="virtual-assistant", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    @app.post("/asistente/sesiones", status_code=201)
    def abrir_sesion(cuerpo: dict[str, Any] | None = Body(default=None),
                     clave: UUID = Header(alias="Idempotency-Key"),
                     authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        cuerpo = cuerpo or {}
        _validar(contratos, _CUERPO_SESION, cuerpo)
        return JSONResponse(servicio.abrir_sesion(usuario_id, clave, cuerpo), status_code=201)

    @app.get("/asistente/sesiones/{sesion_id}")
    def ver_sesion(sesion_id: UUID, authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.ver_sesion(usuario_id, sesion_id))

    @app.post("/asistente/sesiones/{sesion_id}/mensajes")
    def enviar_mensaje(sesion_id: UUID, cuerpo: dict[str, Any] = Body(...),
                       clave: UUID = Header(alias="Idempotency-Key"),
                       authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        _validar(contratos, _CUERPO_MENSAJE, cuerpo)
        return JSONResponse(servicio.enviar_mensaje(usuario_id, authorization, sesion_id, clave,
                                                    cuerpo))

    @app.delete("/interno/usuarios/{usuarioId}", status_code=204)
    def suprimir_datos_de_usuario(usuario_id: UUID = Path(alias="usuarioId")) -> Response:
        """Orden de borrado de la fase 1 (ADR-0030, ADR-0042): solo desde `identity-access`."""
        servicio.suprimir_usuario(usuario_id)
        return Response(status_code=204)

    return app
