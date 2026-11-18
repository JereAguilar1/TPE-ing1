"""Adaptadores HTTP de `bff-web` hacia `itinerary-lectura`, `itinerary-escritura` y
`virtual-assistant` (ADR-0005, ADR-0021, ADR-0034).

Reenvían el identificador del viajero (`X-Usuario-Id`), la sesión OIDC (`Authorization`), la
versión mínima (`X-Min-Version`), la clave de idempotencia (`Idempotency-Key`) y el contexto de
traza (`traceparent`). No contienen reglas de dominio (regla R4).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx

from trotamundos.comun.errores import Problema, no_encontrado

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
                timeout=self._timeout,
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
                timeout=self._timeout,
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


class ClienteDeAsistente(Protocol):
    def abrir_sesion(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def ver_sesion(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...

    def enviar_mensaje(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]: ...


class ClienteDeAsistenteHttp:
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
        authorization: str,
        *,
        cuerpo: Mapping[str, Any] | None = None,
        clave: UUID | None = None,
        traceparent: str | None = None,
    ) -> httpx.Response:
        cabeceras = {"Authorization": authorization}
        if clave is not None:
            cabeceras["Idempotency-Key"] = str(clave)
        if traceparent:
            cabeceras[_CABECERA_TRAZA] = traceparent
        try:
            respuesta = self._http.request(
                metodo,
                f"{self._url}{ruta}",
                json=dict(cuerpo) if cuerpo is not None else None,
                headers=cabeceras,
                timeout=self._timeout,
            )
        except httpx.HTTPError as error:
            raise _no_disponible() from error
        _lanzar_si_error(respuesta)
        return respuesta

    def abrir_sesion(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            "/asistente/sesiones",
            authorization,
            cuerpo=cuerpo,
            clave=clave,
            traceparent=traceparent,
        ).json()

    def ver_sesion(
        self,
        authorization: str,
        sesion_id: UUID,
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "GET",
            f"/asistente/sesiones/{sesion_id}",
            authorization,
            traceparent=traceparent,
        ).json()

    def enviar_mensaje(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        *,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/asistente/sesiones/{sesion_id}/mensajes",
            authorization,
            cuerpo=cuerpo,
            clave=clave,
            traceparent=traceparent,
        ).json()
