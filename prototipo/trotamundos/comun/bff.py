"""Lo que comparten `bff-web` y `bff-mobile` (ADR-0005, ADR-0018, ADR-0019, ADR-0020, ADR-0027).

Un BFF por tipo de cliente, sin lógica de dominio (regla R4): los dos componen las mismas lecturas
y comandos de `itinerary`, así que los adaptadores HTTP y las rutas de esas operaciones viven acá
(ningún servicio importa a otro). Cada BFF agrega lo propio: `bff-web`, el asistente; `bff-mobile`,
`GET /panel/resumen`.

* Adaptadores HTTP hacia `itinerary-lectura` e `itinerary-escritura`: reenvían `X-Usuario-Id`,
  `X-Min-Version`, `Idempotency-Key`, `traceparent`, el plazo restante (`X-Deadline-Ms`) y el
  modo operativo.
* Rutas de panel, viajes, reservas y catálogo de tipos (`bff-web.yaml`, que `bff-mobile.yaml`
  referencia), con `ETag`/`304`, `Cache-Control` y `X-Version-Usuario`.
* Plazo propagado (ADR-0020): si la petición trae `X-Deadline-Ms`, cada llamada a un servicio usa
  como tiempo máximo lo que resta, y si restan menos de 20 ms, no se hace y se responde `503`. El
  modo operativo (`X-Modo-Operativo`) se reenvía igual.
"""

from __future__ import annotations

import contextvars
import os
import hashlib
import json
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

import httpx
from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, no_encontrado
from trotamundos.comun.sesion import usuario_de_sesion

_COMUN = "openapi/comun.yaml#/components/schemas/"
_BFF_WEB = "openapi/bff-web.yaml"
TIPO_DE_MEDIO = "application/vnd.trotamundos.v1+json"
CACHE_PRIVADA = "private, no-cache"
CACHE_CATALOGO = "public, max-age=300, stale-while-revalidate=3600"
_CABECERA_CACHE = "Cache-Control"
_CABECERA_IDEMPOTENCIA = "Idempotency-Key"
_CABECERA_VERSION = "X-Version-Usuario"
CABECERA_PLAZO = "X-Deadline-Ms"
CABECERA_MODO = "X-Modo-Operativo"
MINIMO_PLAZO_S = 0.020

_CUERPO = f"{_BFF_WEB}#/paths/{{ruta}}/post/requestBody/content/application~1vnd.trotamundos.v1+json/schema"
CUERPO_CONFIRMACION = _CUERPO.format(ruta="~1reservas~1{id}~1confirmacion")
CUERPO_RESOLUCION = _CUERPO.format(ruta="~1reservas~1{id}~1conflictos~1{cid}~1resolucion")


# --- plazo propagado (ADR-0020) -------------------------------------------------------------

_vence: contextvars.ContextVar[float | None] = contextvars.ContextVar("vence", default=None)
_modo: contextvars.ContextVar[str | None] = contextvars.ContextVar("modo", default=None)


def instalar_plazo(app: FastAPI) -> None:
    """Toma `X-Deadline-Ms` y `X-Modo-Operativo` de cada petición: las llamadas a otros servicios
    descuentan el tiempo usado y reenvían el modo."""

    @app.middleware("http")
    async def plazo(request: Request, siguiente: Callable) -> Response:
        valor = request.headers.get(CABECERA_PLAZO, "")
        marca = _vence.set(time.monotonic() + int(valor) / 1000 if valor.isdigit() else None)
        marca_modo = _modo.set(request.headers.get(CABECERA_MODO))
        try:
            return await siguiente(request)
        finally:
            _vence.reset(marca)
            _modo.reset(marca_modo)


def tiempo_para_llamar(maximo_s: float) -> float:
    """El tiempo máximo de la próxima llamada: el menor entre `maximo_s` y lo que resta del plazo.
    Si restan menos de 20 ms, lanza `503` sin llamar (ADR-0020)."""
    vence = _vence.get()
    if vence is None:
        return maximo_s
    restante = vence - time.monotonic()
    if restante < MINIMO_PLAZO_S:
        raise Problema(503, "Servicio no disponible", "Se agotó el plazo de la petición")
    return min(maximo_s, restante)


def cabeceras_propagadas() -> dict[str, str]:
    """El plazo que resta y el modo operativo, para reenviarlos al servicio que se llama."""
    cabeceras = {}
    vence = _vence.get()
    if vence is not None:
        cabeceras[CABECERA_PLAZO] = str(max(0, int((vence - time.monotonic()) * 1000)))
    modo = _modo.get()
    if modo:
        cabeceras[CABECERA_MODO] = modo
    return cabeceras


# --- adaptadores HTTP hacia itinerary ----------------------------------------------------

_CABECERA_TRAZA = "traceparent"


def _no_disponible() -> Problema:
    return Problema(503, "Servicio no disponible")


def _cabeceras_usuario(
    usuario_id: UUID | str,
    *,
    min_version: int | None = None,
    clave: UUID | None = None,
    traceparent: str | None = None,
) -> dict[str, str]:
    cabeceras = {"X-Usuario-Id": str(usuario_id)}
    if min_version is not None:
        cabeceras["X-Min-Version"] = str(min_version)
    if clave is not None:
        cabeceras["Idempotency-Key"] = str(clave)
    if traceparent:
        cabeceras[_CABECERA_TRAZA] = traceparent
    cabeceras.update(cabeceras_propagadas())
    return cabeceras


def _lanzar_si_error(respuesta: httpx.Response) -> None:
    if 200 <= respuesta.status_code < 300:
        return
    if respuesta.status_code >= 500:
        raise _no_disponible()
    try:
        datos = respuesta.json()
    except ValueError:
        datos = {}
    if not isinstance(datos, Mapping):
        datos = {}
    if respuesta.status_code == 404 and "detail" not in datos:
        raise no_encontrado()
    raise Problema(
        respuesta.status_code,
        str(datos.get("title") or "Solicitud inválida"),
        datos.get("detail"),
        errores=datos.get("errores"),
    )


class LectorDeItinerario(Protocol):
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

    def listar_tipos_de_segmento(
        self, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]: ...


class LectorDeItinerarioHttp:
    def __init__(
        self,
        url_base: str,
        timeout_s: float = 5.0,
        cliente: httpx.Client | None = None,
    ):
        self._url = url_base.rstrip("/")
        self._timeout = timeout_s
        self._http = cliente or httpx

    def _get(
        self,
        ruta: str,
        *,
        cabeceras: Mapping[str, str] | None = None,
        parametros: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            respuesta = self._http.get(
                f"{self._url}{ruta}",
                headers=dict(cabeceras or {}),
                params=dict(parametros or {}),
                timeout=tiempo_para_llamar(self._timeout),
            )
        except httpx.HTTPError as error:
            raise _no_disponible() from error
        _lanzar_si_error(respuesta)
        return respuesta

    def leer_panel(
        self,
        usuario_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        cabeceras = _cabeceras_usuario(
            usuario_id, min_version=min_version, traceparent=traceparent
        )
        return self._get("/panel", cabeceras=cabeceras).json()

    def listar_viajes(
        self,
        usuario_id: UUID,
        *,
        estado: str | None = None,
        cursor: str | None = None,
        limite: int = 20,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        cabeceras = _cabeceras_usuario(usuario_id, traceparent=traceparent)
        parametros: dict[str, Any] = {"limite": limite}
        if estado is not None:
            parametros["estado"] = estado
        if cursor is not None:
            parametros["cursor"] = cursor
        return self._get("/viajes", cabeceras=cabeceras, parametros=parametros).json()

    def leer_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        cabeceras = _cabeceras_usuario(
            usuario_id, min_version=min_version, traceparent=traceparent
        )
        return self._get(f"/viajes/{viaje_id}", cabeceras=cabeceras).json()

    def listar_tipos_de_segmento(
        self, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]:
        cabeceras = {_CABECERA_TRAZA: traceparent} if traceparent else {}
        return self._get("/tipos-de-segmento", cabeceras=cabeceras).json()


class EscritorDeItinerario(Protocol):
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

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
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

    def eliminar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int: ...


class EscritorDeItinerarioHttp:
    def __init__(
        self,
        url_base: str,
        timeout_s: float = 5.0,
        cliente: httpx.Client | None = None,
    ):
        self._url = url_base.rstrip("/")
        self._timeout = timeout_s
        self._http = cliente or httpx

    def _enviar(
        self,
        metodo: str,
        ruta: str,
        usuario_id: UUID,
        *,
        cuerpo: Mapping[str, Any] | None = None,
        clave: UUID | None = None,
        traceparent: str | None = None,
    ) -> httpx.Response:
        cabeceras = _cabeceras_usuario(
            usuario_id, clave=clave, traceparent=traceparent
        )
        try:
            respuesta = self._http.request(
                metodo,
                f"{self._url}{ruta}",
                json=dict(cuerpo) if cuerpo is not None else None,
                headers=cabeceras,
                timeout=tiempo_para_llamar(self._timeout),
            )
        except httpx.HTTPError as error:
            raise _no_disponible() from error
        _lanzar_si_error(respuesta)
        return respuesta

    @staticmethod
    def _version_de_204(respuesta: httpx.Response) -> int:
        valor = respuesta.headers.get("X-Version-Usuario")
        return int(valor) if valor and valor.isdigit() else 0

    def crear_reserva(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        respuesta = self._enviar(
            "POST",
            "/reservas",
            usuario_id,
            cuerpo=cuerpo,
            clave=clave,
            traceparent=traceparent,
        )
        return respuesta.status_code, respuesta.json()

    def editar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "PUT",
            f"/reservas/{reserva_id}",
            usuario_id,
            cuerpo=cuerpo,
            traceparent=traceparent,
        ).json()

    def eliminar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        respuesta = self._enviar(
            "DELETE",
            f"/reservas/{reserva_id}",
            usuario_id,
            traceparent=traceparent,
        )
        return self._version_de_204(respuesta)

    def confirmar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/reservas/{reserva_id}/confirmacion",
            usuario_id,
            cuerpo=cuerpo,
            traceparent=traceparent,
        ).json()

    def resolver_conflicto(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        conflicto_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/reservas/{reserva_id}/conflictos/{conflicto_id}/resolucion",
            usuario_id,
            cuerpo=cuerpo,
            traceparent=traceparent,
        ).json()

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        respuesta = self._enviar(
            "PUT",
            f"/viajes/{viaje_id}/reservas/{reserva_id}",
            usuario_id,
            traceparent=traceparent,
        )
        return self._version_de_204(respuesta)

    def archivar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        respuesta = self._enviar(
            "POST",
            f"/viajes/{viaje_id}/archivo",
            usuario_id,
            traceparent=traceparent,
        )
        return self._version_de_204(respuesta)

    def eliminar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        respuesta = self._enviar(
            "DELETE",
            f"/viajes/{viaje_id}",
            usuario_id,
            traceparent=traceparent,
        )
        return self._version_de_204(respuesta)


# --- composición de itinerary (la base de los dos BFF) -----------------------------------------

class ComposicionDeItinerarioHttp:
    """Delega las lecturas en `itinerary-lectura` y los comandos en `itinerary-escritura`."""

    def __init__(self, *, lector: LectorDeItinerario | None = None,
                 escritor: EscritorDeItinerario | None = None):
        self._lector = lector or LectorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_LECTURA", "http://localhost:18102"))
        self._escritor = escritor or EscritorDeItinerarioHttp(
            os.environ.get("TROTAMUNDOS_URL_ITINERARY_ESCRITURA", "http://localhost:18101"))

    # --- lecturas de itinerario (itinerary-lectura) --------------------------------------

    def leer_panel(
        self,
        usuario_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.leer_panel(
            usuario_id, min_version=min_version, traceparent=traceparent
        )

    def listar_viajes(
        self,
        usuario_id: UUID,
        *,
        estado: str | None = None,
        cursor: str | None = None,
        limite: int = 20,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.listar_viajes(
            usuario_id,
            estado=estado,
            cursor=cursor,
            limite=limite,
            traceparent=traceparent,
        )

    def leer_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        min_version: int | None = None,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._lector.leer_viaje(
            usuario_id, viaje_id, min_version=min_version, traceparent=traceparent
        )

    def listar_tipos_de_segmento(
        self, *, traceparent: str | None = None
    ) -> list[dict[str, Any]]:
        return self._lector.listar_tipos_de_segmento(traceparent=traceparent)

    # --- comandos de itinerario (itinerary-escritura) ------------------------------------

    def eliminar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.eliminar_viaje(
            usuario_id, viaje_id, traceparent=traceparent
        )

    def archivar_viaje(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.archivar_viaje(
            usuario_id, viaje_id, traceparent=traceparent
        )

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.mover_reserva(
            usuario_id, viaje_id, reserva_id, traceparent=traceparent
        )

    def crear_reserva(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self._escritor.crear_reserva(
            usuario_id, clave, cuerpo, traceparent=traceparent
        )

    def editar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.editar_reserva(
            usuario_id, reserva_id, cuerpo, traceparent=traceparent
        )

    def eliminar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> int:
        return self._escritor.eliminar_reserva(
            usuario_id, reserva_id, traceparent=traceparent
        )

    def confirmar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.confirmar_reserva(
            usuario_id, reserva_id, cuerpo, traceparent=traceparent
        )

    def resolver_conflicto(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        conflicto_id: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._escritor.resolver_conflicto(
            usuario_id,
            reserva_id,
            conflicto_id,
            cuerpo,
            traceparent=traceparent,
        )


# --- rutas compartidas ----------------------------------------------------------------

class ComposicionDeItinerario(Protocol):
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


def validador(contratos: Contratos) -> Callable[[str, Any], None]:
    def validar(referencia: str, instancia: Any) -> None:
        errores = contratos.errores(referencia, instancia)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[_error(e) for e in errores])
    return validar


def instalar_rutas_de_itinerario(app: FastAPI, servicio: ComposicionDeItinerario,
                                 contratos: Contratos, secreto_jwt: str) -> None:
    """Panel, viajes, reservas y catálogo de tipos: las operaciones de `bff-web.yaml` que también
    expone `bff-mobile.yaml`."""
    validar = validador(contratos)

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
        return respuesta_con_etag(panel, if_none_match)

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
        return respuesta_con_etag(viaje, if_none_match)

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


def verificar_rutas_contra_contrato(app: FastAPI, contratos: Contratos, contrato: str) -> None:
    """Verifica que las rutas expuestas coincidan exactamente con `contrato` (ADR-0009)."""
    declaradas = {
        (metodo.upper(), ruta)
        for ruta, operaciones in operaciones_de(contratos, contrato)["paths"].items()
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
            f"Las rutas de {app.title} no coinciden con {contrato}: {diferencia}"
        )




def operaciones_de(contratos: Contratos, contrato: str) -> dict[str, Any]:
    """Los `paths` del contrato, resolviendo los `$ref` a otro contrato (como hace `bff-mobile.yaml`)."""
    rutas = {}
    for ruta, item in contratos.documento(contrato)["paths"].items():
        if "$ref" in item:
            archivo, _, puntero = item["$ref"].partition("#/paths/")
            otro = contratos.documento(f"openapi/{archivo}")["paths"]
            item = otro[puntero.replace("~1", "/").replace("~0", "~")]
        rutas[ruta] = item
    return {"paths": rutas}


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


def respuesta_con_etag(
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
