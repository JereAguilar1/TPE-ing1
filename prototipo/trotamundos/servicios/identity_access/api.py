"""Módulo `api` de `identity-access` (`contratos/openapi/identity-access.yaml`).

Expone sesiones OIDC, flujo OTP de invitados, consentimiento de buzones, emisión de tokens
efímeros, evaluación ABAC con vales JWS y derechos de privacidad. Todo cuerpo se valida contra
el contrato antes de ejecutarse y todo error sale como `Problema` (`comun.errores`).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

import jwt
from fastapi import Body, FastAPI, Header, Response
from fastapi.responses import JSONResponse

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores, no_encontrado

_CONTRATO = "openapi/identity-access.yaml"
_CUERPO = "openapi/identity-access.yaml#/paths/{ruta}/post/requestBody/content/application~1json/schema"
_CUERPO_SESIONES = _CUERPO.format(ruta="~1sesiones")
_CUERPO_INV_CODIGO = _CUERPO.format(ruta="~1sesiones~1invitado~1codigo")
_CUERPO_INV_VERIF = _CUERPO.format(ruta="~1sesiones~1invitado~1verificacion")
_CUERPO_BUZON = _CUERPO.format(ruta="~1buzones")
_CUERPO_AUTORIZACION = _CUERPO.format(ruta="~1buzones~1{id}~1autorizacion")
_CUERPO_ABAC = _CUERPO.format(ruta="~1autorizaciones~1evaluar")

_SERVICIOS_INTERNOS_ABAC = frozenset(
    {"api-gateway", "bff-web", "bff-mobile", "sharing", "itinerary", "support-liaison"}
)


class IdentidadYAcceso(Protocol):
    """Operaciones de `identity-access` implementadas por `servicio.py`."""

    def crear_sesion(self, cuerpo: Mapping[str, Any]) -> dict[str, Any]: ...

    def solicitar_codigo_invitado(self, cuerpo: Mapping[str, Any]) -> None: ...

    def verificar_codigo_invitado(self, cuerpo: Mapping[str, Any]) -> dict[str, Any]: ...

    def listar_buzones(self, usuario_id: UUID) -> list[dict[str, Any]]: ...

    def conectar_buzon(
        self, usuario_id: UUID, clave: UUID, cuerpo: Mapping[str, Any],
        *, traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]: ...

    def autorizar_buzon(
        self, usuario_id: UUID, buzon_id: UUID, cuerpo: Mapping[str, Any],
        *, traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def desconectar_buzon(
        self, usuario_id: UUID, buzon_id: UUID, *, traceparent: str | None = None,
    ) -> None: ...

    def emitir_token_efimero(
        self, buzon_id: UUID, instancia_id: str, buckets_arrendados: set[int] | None,
    ) -> dict[str, Any]: ...

    def evaluar_autorizacion(
        self, cuerpo: Mapping[str, Any], servicio_cliente: str,
    ) -> dict[str, Any]: ...

    def listar_exportaciones(self, usuario_id: UUID) -> list[dict[str, Any]]: ...

    def pedir_exportacion(self, usuario_id: UUID, clave: UUID) -> tuple[int, dict[str, Any]]: ...

    def suprimir_cuenta(
        self, usuario_id: UUID, clave: UUID, *, traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]: ...


def _error(mensaje: str) -> dict[str, str]:
    ubicacion, _, detalle = mensaje.partition(": ")
    return {"campo": ubicacion or "$", "mensaje": detalle or mensaje}


def _parsear_buckets(cabecera: str | None) -> set[int] | None:
    if cabecera is None or not cabecera.strip():
        return None
    try:
        valores = {int(parte.strip()) for parte in cabecera.split(",") if parte.strip()}
    except ValueError as exc:
        raise Problema(400, "Cabecera X-Buckets-Arrendados inválida") from exc
    if any(b < 0 or b >= 64 for b in valores):
        raise Problema(400, "Bucket fuera de rango (0..63)")
    return valores


def crear_app(
    servicio: IdentidadYAcceso,
    contratos: Contratos,
    secreto_jwt: str,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager] | None = None,
) -> FastAPI:
    """Construye la aplicación FastAPI de `identity-access`."""
    app = FastAPI(title="identity-access", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    def validar(referencia: str, cuerpo: Any) -> None:
        errores = contratos.errores(referencia, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[_error(e) for e in errores])

    def usuario_desde_oidc(authorization: str | None) -> UUID:
        if not authorization or not authorization.startswith("Bearer "):
            raise Problema(401, "No autenticado")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            datos = jwt.decode(token, secreto_jwt, algorithms=["HS256"])
            return UUID(str(datos["sub"]))
        except Exception as exc:
            raise Problema(401, "No autenticado") from exc

    # --- Sesiones ----------------------------------------------------------------------------

    @app.post("/sesiones")
    def crear_sesion(cuerpo: dict[str, Any] = Body(...)) -> JSONResponse:
        validar(_CUERPO_SESIONES, cuerpo)
        return JSONResponse(servicio.crear_sesion(cuerpo), status_code=201)

    @app.post("/sesiones/invitado/codigo", status_code=202)
    def solicitar_codigo_invitado(cuerpo: dict[str, Any] = Body(...)) -> Response:
        validar(_CUERPO_INV_CODIGO, cuerpo)
        servicio.solicitar_codigo_invitado(cuerpo)
        return Response(status_code=202)

    @app.post("/sesiones/invitado/verificacion")
    def verificar_codigo_invitado(cuerpo: dict[str, Any] = Body(...)) -> JSONResponse:
        validar(_CUERPO_INV_VERIF, cuerpo)
        return JSONResponse(servicio.verificar_codigo_invitado(cuerpo), status_code=201)

    # --- Buzones -----------------------------------------------------------------------------

    @app.get("/buzones")
    def listar_buzones(authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
        usuario_id = usuario_desde_oidc(authorization)
        return servicio.listar_buzones(usuario_id)

    @app.post("/buzones")
    def conectar_buzon(
        authorization: str | None = Header(default=None),
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
        traceparent: str | None = Header(default=None),
        cuerpo: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        usuario_id = usuario_desde_oidc(authorization)
        validar(_CUERPO_BUZON, cuerpo)
        estado, respuesta = servicio.conectar_buzon(
            usuario_id, idempotency_key, cuerpo, traceparent=traceparent,
        )
        return JSONResponse(respuesta, status_code=estado)

    @app.post("/buzones/{buzon_id}/autorizacion")
    def autorizar_buzon(
        buzon_id: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
        cuerpo: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        usuario_id = usuario_desde_oidc(authorization)
        validar(_CUERPO_AUTORIZACION, cuerpo)
        return servicio.autorizar_buzon(usuario_id, buzon_id, cuerpo, traceparent=traceparent)

    @app.delete("/buzones/{buzon_id}", status_code=204)
    def desconectar_buzon(
        buzon_id: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_desde_oidc(authorization)
        servicio.desconectar_buzon(usuario_id, buzon_id, traceparent=traceparent)
        return Response(status_code=204)

    @app.post("/buzones/{buzon_id}/token-efimero")
    def emitir_token_efimero(
        buzon_id: UUID,
        servicio_cliente: str | None = Header(default=None, alias="X-Servicio-Cliente"),
        instancia_cliente: str | None = Header(default=None, alias="X-Instancia-Cliente"),
        buckets_hdr: str | None = Header(default=None, alias="X-Buckets-Arrendados"),
    ) -> dict[str, Any]:
        # Regla R5 / ADR-0029: únicamente `mail-ingest` puede pedir tokens efímeros.
        if servicio_cliente != "mail-ingest":
            raise Problema(403, "Prohibido")
        instancia = instancia_cliente or servicio_cliente
        buckets = _parsear_buckets(buckets_hdr)
        return servicio.emitir_token_efimero(buzon_id, instancia, buckets)

    # --- Autorización ABAC -------------------------------------------------------------------

    @app.post("/autorizaciones/evaluar")
    def evaluar_autorizacion(
        servicio_cliente: str | None = Header(default=None, alias="X-Servicio-Cliente"),
        cuerpo: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        if not servicio_cliente or servicio_cliente not in _SERVICIOS_INTERNOS_ABAC:
            raise Problema(403, "Prohibido")
        validar(_CUERPO_ABAC, cuerpo)
        return servicio.evaluar_autorizacion(cuerpo, servicio_cliente)

    # --- Privacidad (ADR-0030) ---------------------------------------------------------------

    @app.get("/privacidad/exportaciones")
    def listar_exportaciones(
        authorization: str | None = Header(default=None),
    ) -> list[dict[str, Any]]:
        usuario_id = usuario_desde_oidc(authorization)
        return servicio.listar_exportaciones(usuario_id)

    @app.post("/privacidad/exportaciones")
    def pedir_exportacion(
        authorization: str | None = Header(default=None),
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
    ) -> JSONResponse:
        usuario_id = usuario_desde_oidc(authorization)
        estado, respuesta = servicio.pedir_exportacion(usuario_id, idempotency_key)
        return JSONResponse(respuesta, status_code=estado)

    @app.delete("/privacidad/cuenta")
    def suprimir_cuenta(
        authorization: str | None = Header(default=None),
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_desde_oidc(authorization)
        estado, respuesta = servicio.suprimir_cuenta(
            usuario_id, idempotency_key, traceparent=traceparent,
        )
        return JSONResponse(respuesta, status_code=estado)

    return app
