"""Módulo `api` de `sharing` (`contratos/openapi/sharing.yaml`, ADR-0028).

Las operaciones del dueño piden su sesión OIDC (`comun.sesion`). `GET /comparticiones/{cid}` acepta
también el token de invitado (`invitado:<correo>`, alcance `lectura:comparticion:{cid}`), así que
lee el token acá; un token inválido es `401` y todo lo demás que no corresponda, el mismo `404`.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

import jwt
from fastapi import Body, FastAPI, Header, Path
from fastapi.responses import JSONResponse, Response

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

_CONTRATO = "openapi/sharing.yaml"
TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
_CUERPO = (f"{_CONTRATO}#/paths/{{ruta}}/post/requestBody/content/"
           "application~1vnd.trotamundos.v1+json/schema")
CUERPO_COMPARTIR = _CUERPO.format(ruta="~1viajes~1{id}~1comparticiones")
CUERPO_PUBLICAR = _CUERPO.format(ruta="~1viajes~1{id}~1publicaciones")
RESUMEN = f"{_CONTRATO}#/components/schemas/ResumenPublicable"


class SharingApi(Protocol):
    def listar(self, usuario_id: UUID, viaje_id: UUID) -> list[dict[str, Any]]: ...
    def compartir(self, usuario_id: UUID, viaje_id: UUID, clave: UUID,
                  cuerpo: Mapping[str, Any]) -> dict[str, Any]: ...
    def revocar(self, usuario_id: UUID, viaje_id: UUID, comparticion_id: UUID) -> None: ...
    def previsualizar(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any]: ...
    def publicar(self, usuario_id: UUID, viaje_id: UUID, clave: UUID,
                 cuerpo: Mapping[str, Any]) -> None: ...
    def ver_compartido(self, sesion: Mapping[str, Any], comparticion_id: UUID) -> dict[str, Any]: ...
    def atributos(self, comparticion_id: UUID) -> dict[str, Any]: ...
    def suprimir_usuario(self, usuario_id: UUID) -> int: ...


def _sesion_de_lector(authorization: str | None, secreto: str) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise Problema(401, "No autenticado")
    try:
        datos = jwt.decode(authorization.removeprefix("Bearer ").strip(), secreto,
                           algorithms=["HS256"])
    except jwt.InvalidTokenError as error:
        raise Problema(401, "No autenticado") from error
    if not datos.get("sub"):
        raise Problema(401, "No autenticado")
    return datos


def crear_app(servicio: SharingApi, contratos: Contratos, secreto_jwt: str,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None = None
              ) -> FastAPI:
    app = FastAPI(title="sharing", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    def validar(referencia: str, cuerpo: Any) -> None:
        errores = contratos.errores(referencia, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": e.partition(": ")[0].removeprefix("$."), "mensaje": e.partition(": ")[2]}
                for e in errores])

    @app.get("/viajes/{id}/comparticiones")
    def listar(id: UUID, authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.listar(usuario_id, id), media_type=TIPO_DE_MEDIO)

    @app.post("/viajes/{id}/comparticiones", status_code=201)
    def compartir(id: UUID, cuerpo: dict[str, Any] = Body(...),
                  clave: UUID = Header(alias="Idempotency-Key"),
                  authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(CUERPO_COMPARTIR, cuerpo)
        return JSONResponse(servicio.compartir(usuario_id, id, clave, cuerpo), status_code=201,
                            media_type=TIPO_DE_MEDIO)

    @app.delete("/viajes/{id}/comparticiones/{cid}", status_code=204)
    def revocar(id: UUID, cid: UUID, authorization: str | None = Header(default=None)) -> Response:
        servicio.revocar(usuario_de_sesion(authorization, secreto_jwt), id, cid)
        return Response(status_code=204)

    @app.get("/comparticiones/{cid}")
    def ver_compartido(cid: UUID, authorization: str | None = Header(default=None)) -> JSONResponse:
        sesion = _sesion_de_lector(authorization, secreto_jwt)
        return JSONResponse(servicio.ver_compartido(sesion, cid), media_type=TIPO_DE_MEDIO,
                            headers={"Cache-Control": "private, no-store"})

    @app.get("/viajes/{id}/publicaciones/previsualizacion")
    def previsualizar(id: UUID, authorization: str | None = Header(default=None)) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        return JSONResponse(servicio.previsualizar(usuario_id, id), media_type=TIPO_DE_MEDIO)

    @app.post("/viajes/{id}/publicaciones", status_code=202)
    def publicar(id: UUID, cuerpo: dict[str, Any] = Body(...),
                 clave: UUID = Header(alias="Idempotency-Key"),
                 authorization: str | None = Header(default=None)) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(CUERPO_PUBLICAR, cuerpo)
        servicio.publicar(usuario_id, id, clave, cuerpo)
        return Response(status_code=202)

    @app.get("/interno/comparticiones/{cid}")
    def atributos(cid: UUID) -> JSONResponse:
        """Solo para `identity-access`, por la red interna (mTLS en producción, ADR-0029)."""
        return JSONResponse(servicio.atributos(cid))

    @app.delete("/interno/usuarios/{usuarioId}", status_code=204)
    def suprimir(usuario_id: UUID = Path(alias="usuarioId")) -> Response:
        servicio.suprimir_usuario(usuario_id)
        return Response(status_code=204)

    return app
