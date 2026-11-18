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

import hashlib
import json
from typing import Any, Mapping, Protocol
from uuid import UUID

from fastapi import Body, FastAPI, Header, Query
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores
from trotamundos.comun.sesion import usuario_de_sesion

_CONTRATO = "openapi/bff-web.yaml"
_COMUN = "openapi/comun.yaml#/components/schemas/"
TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
CACHE_PRIVADA = "private, no-cache"
CACHE_CATALOGO = "public, max-age=300, stale-while-revalidate=3600"
_CABECERA_CACHE = "Cache-Control"
_CABECERA_IDEMPOTENCIA = "Idempotency-Key"
_CABECERA_VERSION = "X-Version-Usuario"

_CUERPO = f"{_CONTRATO}#/paths/{{ruta}}/post/requestBody/content/application~1vnd.trotamundos.v1+json/schema"
CUERPO_CONFIRMACION = _CUERPO.format(ruta="~1reservas~1{id}~1confirmacion")
CUERPO_RESOLUCION = _CUERPO.format(ruta="~1reservas~1{id}~1conflictos~1{cid}~1resolucion")
CUERPO_SESION = _CUERPO.format(ruta="~1asistente~1sesiones")
CUERPO_MENSAJE = "openapi/virtual-assistant.yaml#/components/schemas/MensajeDelViajero"


class BffWebApi(Protocol):
    """Puerto que implementa el armado de `bff-web` (`servicio`)."""

    def leer_panel(
        self,
        usuario_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def listar_viajes(
        self,
        usuario_id: UUID,
        *,
        estado: str | None = None,
        cursor: str | None = None,
        limite: int = 20,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def leer_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def eliminar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int: ...

    def archivar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int: ...

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int: ...

    def crear_reserva(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]: ...

    def editar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def eliminar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int: ...

    def confirmar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def resolver_conflicto(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        conflicto_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def listar_tipos_de_segmento(
        self, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]: ...

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

    def validar(referencia: str, instancia: Any) -> None:
        errores = contratos.errores(referencia, instancia)
        if errores:
            raise Problema(
                400,
                "Solicitud inválida",
                errores=[_error(e) for e in errores],
            )

    # --- panel y viajes (UC-3, RF-08, RF-09) ---------------------------------------------

    @app.get("/panel")
    def obtener_panel(
        authorization: str | None = Header(default=None),
        min_version: int | None = Header(default=None, alias="X-Min-Version", ge=0),
        _accept_language: str | None = Header(default=None, alias="Accept-Language"),
        traceparent: str | None = Header(default=None),
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        panel = servicio.leer_panel(
            usuario_id, min_version=min_version, traceparent=traceparent
        )
        return _respuesta_con_etag(panel, if_none_match)

    @app.get("/viajes")
    def listar_viajes(
        authorization: str | None = Header(default=None),
        estado: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limite: int = Query(default=20, ge=1, le=100),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        if estado is not None:
            validar(_COMUN + "EstadoViaje", estado)
        pagina = servicio.listar_viajes(
            usuario_id,
            estado=estado,
            cursor=cursor,
            limite=limite,
            traceparent=traceparent,
        )
        return JSONResponse(
            pagina,
            media_type=TIPO_DE_MEDIO,
            headers={_CABECERA_CACHE: CACHE_PRIVADA},
        )

    @app.get("/viajes/{id}")
    def obtener_viaje(
        id: UUID,
        authorization: str | None = Header(default=None),
        min_version: int | None = Header(default=None, alias="X-Min-Version", ge=0),
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        viaje = servicio.leer_viaje(
            usuario_id, id, min_version=min_version, traceparent=traceparent
        )
        return _respuesta_con_etag(viaje, if_none_match)

    @app.delete("/viajes/{id}", status_code=204)
    def eliminar_viaje(
        id: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        version = servicio.eliminar_viaje(usuario_id, id, traceparent=traceparent)
        return _respuesta_204(version)

    @app.post("/viajes/{id}/archivo", status_code=204)
    def archivar_viaje(
        id: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        version = servicio.archivar_viaje(usuario_id, id, traceparent=traceparent)
        return _respuesta_204(version)

    @app.put("/viajes/{vid}/reservas/{rid}", status_code=204)
    def mover_reserva_a_viaje(
        vid: UUID,
        rid: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        version = servicio.mover_reserva(usuario_id, vid, rid, traceparent=traceparent)
        return _respuesta_204(version)

    # --- reservas (UC-4, RF-06, ADR-0013, ADR-0015) --------------------------------------

    @app.post("/reservas", status_code=201)
    def crear_reserva(
        cuerpo: dict[str, Any] = Body(...),
        clave: UUID = Header(alias=_CABECERA_IDEMPOTENCIA),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(_COMUN + "ReservaNueva", cuerpo)
        estado, resultado = servicio.crear_reserva(
            usuario_id, clave, cuerpo, traceparent=traceparent
        )
        return _respuesta_comando_reserva(resultado, status_code=estado)

    @app.put("/reservas/{id}")
    def editar_reserva(
        id: UUID,
        cuerpo: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(_COMUN + "EdicionReserva", cuerpo)
        resultado = servicio.editar_reserva(
            usuario_id, id, cuerpo, traceparent=traceparent
        )
        return _respuesta_comando_reserva(resultado)

    @app.delete("/reservas/{id}", status_code=204)
    def eliminar_reserva(
        id: UUID,
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> Response:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        version = servicio.eliminar_reserva(usuario_id, id, traceparent=traceparent)
        return _respuesta_204(version)

    @app.post("/reservas/{id}/confirmacion")
    def confirmar_reserva(
        id: UUID,
        cuerpo: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(CUERPO_CONFIRMACION, cuerpo)
        resultado = servicio.confirmar_reserva(
            usuario_id, id, cuerpo, traceparent=traceparent
        )
        return _respuesta_comando_reserva(resultado)

    @app.post("/reservas/{id}/conflictos/{cid}/resolucion")
    def resolver_conflicto(
        id: UUID,
        cid: UUID,
        cuerpo: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        usuario_id = usuario_de_sesion(authorization, secreto_jwt)
        validar(CUERPO_RESOLUCION, cuerpo)
        resultado = servicio.resolver_conflicto(
            usuario_id, id, cid, cuerpo, traceparent=traceparent
        )
        return _respuesta_comando_reserva(resultado)

    # --- catálogo público de tipos de segmento (ADR-0011, ADR-0019) ----------------------

    @app.get("/tipos-de-segmento")
    def listar_tipos_de_segmento(
        traceparent: str | None = Header(default=None),
    ) -> JSONResponse:
        tipos = servicio.listar_tipos_de_segmento(traceparent=traceparent)
        return JSONResponse(
            tipos,
            media_type=TIPO_DE_MEDIO,
            headers={_CABECERA_CACHE: CACHE_CATALOGO},
        )

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

    _verificar_rutas_contra_contrato(app, contratos)
    return app


def _verificar_rutas_contra_contrato(app: FastAPI, contratos: Contratos) -> None:
    """Verifica que las rutas expuestas coincidan exactamente con `openapi/bff-web.yaml` (ADR-0009)."""
    declaradas = {
        (metodo.upper(), ruta)
        for ruta, operaciones in contratos.documento(_CONTRATO)["paths"].items()
        for metodo, operacion in operaciones.items()
        if isinstance(operacion, dict) and "operationId" in operacion
    }
    registradas = {
        (metodo, ruta.path)
        for ruta in app.router.routes
        if isinstance(ruta, APIRoute)
        for metodo in ruta.methods
    }
    if registradas != declaradas:
        diferencia = sorted(registradas ^ declaradas)
        raise RuntimeError(
            f"Las rutas de bff-web no coinciden con {_CONTRATO}: {diferencia}"
        )


def _calcular_etag(cuerpo: Mapping[str, Any]) -> str:
    serializado = json.dumps(
        cuerpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f'"{hashlib.sha256(serializado).hexdigest()[:16]}"'


def _coincide_etag(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidatos = {
        item.strip().removeprefix("W/")
        for item in if_none_match.split(",")
        if item.strip()
    }
    return "*" in candidatos or etag in candidatos


def _respuesta_con_etag(
    cuerpo: Mapping[str, Any], if_none_match: str | None
) -> Response:
    etag = _calcular_etag(cuerpo)
    cabeceras = {"ETag": etag, _CABECERA_CACHE: CACHE_PRIVADA}
    if _coincide_etag(if_none_match, etag):
        return Response(status_code=304, headers=cabeceras)
    return JSONResponse(dict(cuerpo), media_type=TIPO_DE_MEDIO, headers=cabeceras)


def _respuesta_comando_reserva(
    resultado: Mapping[str, Any], *, status_code: int = 200
) -> JSONResponse:
    cabeceras = {_CABECERA_VERSION: str(resultado["versionUsuario"])}
    return JSONResponse(
        dict(resultado),
        status_code=status_code,
        media_type=TIPO_DE_MEDIO,
        headers=cabeceras,
    )


def _respuesta_204(version: int) -> Response:
    return Response(
        status_code=204, headers={_CABECERA_VERSION: str(version)}
    )


def _error(texto: str) -> dict[str, str]:
    campo, _, mensaje = texto.partition(": ")
    return {
        "campo": campo.removeprefix("$.").removeprefix("$"),
        "mensaje": mensaje,
    }
