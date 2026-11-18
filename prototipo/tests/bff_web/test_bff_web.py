"""Pruebas de `bff-web` (`contratos/openapi/bff-web.yaml`, ADR-0005, ADR-0018, ADR-0019,
ADR-0027, ADR-0028, ADR-0034).

Verifica que `bff-web`:
- compone `itinerary-lectura`, `itinerary-escritura` y `virtual-assistant` sin lógica de dominio;
- exige y verifica la sesión OIDC en las rutas autenticadas (`401`), salvo en `GET /tipos-de-segmento`;
- sirve todas las respuestas con `application/vnd.trotamundos.v1+json` (ADR-0027);
- emite `Cache-Control: private, no-cache`, `ETag` y `304 Not Modified` en lecturas del usuario, y
  `Cache-Control: public, max-age=300, stale-while-revalidate=3600` en el catálogo público (ADR-0019);
- propaga `X-Version-Usuario` en mutaciones y `X-Min-Version` en lecturas (ADR-0018);
- valida cuerpos y parámetros contra `contratos/` (`400`) y responde errores como `Problema`.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from trotamundos.comun.errores import Problema, instalar_manejadores, no_encontrado
from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.bff_web import api, clientes
from trotamundos.servicios.bff_web.servicio import BffWeb

USUARIO = UUID("00000000-0000-4000-8000-0000000000b1")
OTRO = UUID("00000000-0000-4000-8000-0000000000b2")
VIAJE = UUID("00000000-0000-4000-8000-0000000000c1")
RESERVA = UUID("00000000-0000-4000-8000-0000000000c2")
CONFLICTO = UUID("00000000-0000-4000-8000-0000000000c3")
SESION_ID = UUID("00000000-0000-4000-8000-0000000000c4")
SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
TIPO = "application/vnd.trotamundos.v1+json"
PROBLEMA = "openapi/comun.yaml#/components/schemas/Problema"
PANEL = "openapi/comun.yaml#/components/schemas/Panel"
VIAJE_SCHEMA = "openapi/comun.yaml#/components/schemas/Viaje"
RESULTADO = "openapi/comun.yaml#/components/schemas/ResultadoComandoReserva"
SESION_SCHEMA = "openapi/virtual-assistant.yaml#/components/schemas/Sesion"
RESPUESTA_SCHEMA = "openapi/virtual-assistant.yaml#/components/schemas/Respuesta"


def _sesion(usuario: UUID = USUARIO, *, vencido: bool = False) -> dict[str, str]:
    delta = timedelta(hours=-1) if vencido else timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(usuario), "exp": datetime.now(timezone.utc) + delta},
        SECRETO_JWT,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class DobleDownstream:
    """Implementa los tres puertos de `bff-web` en memoria para pruebas unitarias de la API."""

    def __init__(self, observacion: dict[str, Any]):
        segmento = {
            **copy.deepcopy(observacion["segmentos"][0]),
            "id": str(uuid4()),
            "orden": 0,
            "estado": "confirmado",
        }
        self.version_usuario = 1
        self.reserva = {
            "id": str(RESERVA),
            "estado": "Confirmada",
            "version": 1,
            "identificadores": observacion["identificadores"],
            "segmentos": [segmento],
            "fuentes": ["correo"],
            "viajeId": str(VIAJE),
        }
        self.viaje = {
            "id": str(VIAJE),
            "titulo": "Viaje a Mendoza",
            "estado": "Planificado",
            "desde": segmento["inicio"]["instante"],
            "hasta": segmento["fin"]["instante"],
            "version": 1,
            "reservas": [self.reserva],
        }
        self.sesion = {
            "id": str(SESION_ID),
            "abiertaEn": "2026-11-18T12:00:00Z",
            "viajeId": str(VIAJE),
            "turnos": [
                {
                    "autor": "asistente",
                    "texto": "Hola, ¿en qué te ayudo?",
                    "en": "2026-11-18T12:00:00Z",
                    "intencion": "saludo",
                }
            ],
        }
        self.llamadas: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.error: Problema | None = None

    def _registrar(self, nombre: str, *args: Any, **kwargs: Any) -> None:
        self.llamadas.append((nombre, args, kwargs))
        if self.error is not None:
            raise self.error

    def _exigir_titular(self, usuario_id: UUID) -> None:
        if usuario_id != USUARIO:
            raise no_encontrado()

    # --- LectorDeItinerario ---

    def leer_panel(self, usuario_id: UUID, **kwargs: Any) -> dict[str, Any]:
        self._registrar("leer_panel", usuario_id, **kwargs)
        viajes = [self.viaje] if usuario_id == USUARIO else []
        return {
            "viajesActivos": viajes,
            "porConfirmar": [],
            "conflictosAbiertos": [],
            "versionUsuario": self.version_usuario,
        }

    def listar_viajes(
        self,
        usuario_id: UUID,
        *,
        estado: str | None = None,
        cursor: str | None = None,
        limite: int = 20,
        traceparent: str | None = None,
    ) -> dict[str, Any]:
        self._registrar(
            "listar_viajes",
            usuario_id,
            estado=estado,
            cursor=cursor,
            limite=limite,
            traceparent=traceparent,
        )
        if cursor == "invalido":
            raise Problema(
                400,
                "Solicitud inválida",
                errores=[{"campo": "cursor", "mensaje": "cursor inválido"}],
            )
        resumen = {
            "id": str(VIAJE),
            "titulo": self.viaje["titulo"],
            "estado": estado or self.viaje["estado"],
            "desde": self.viaje["desde"],
            "hasta": self.viaje["hasta"],
            "cantidadReservas": 1,
        }
        return {
            "viajes": [resumen] if usuario_id == USUARIO else [],
            "siguienteCursor": None,
        }

    def leer_viaje(
        self, usuario_id: UUID, viaje_id: UUID, **kwargs: Any
    ) -> dict[str, Any]:
        self._registrar("leer_viaje", usuario_id, viaje_id, **kwargs)
        self._exigir_titular(usuario_id)
        if viaje_id != VIAJE:
            raise no_encontrado()
        return self.viaje

    def listar_tipos_de_segmento(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._registrar("listar_tipos_de_segmento", **kwargs)
        return registro_por_omision().documentos()

    # --- EscritorDeItinerario ---

    def _resultado_reserva(self) -> dict[str, Any]:
        self.version_usuario += 1
        return {
            "reserva": self.reserva,
            "viajeId": str(VIAJE),
            "versionUsuario": self.version_usuario,
        }

    def crear_reserva(
        self,
        usuario_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        self._registrar("crear_reserva", usuario_id, clave, dict(cuerpo), **kwargs)
        return 201, self._resultado_reserva()

    def editar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._registrar(
            "editar_reserva", usuario_id, reserva_id, dict(cuerpo), **kwargs
        )
        self._exigir_titular(usuario_id)
        if reserva_id != RESERVA:
            raise no_encontrado()
        return self._resultado_reserva()

    def eliminar_reserva(
        self, usuario_id: UUID, reserva_id: UUID, **kwargs: Any
    ) -> int:
        self._registrar("eliminar_reserva", usuario_id, reserva_id, **kwargs)
        self._exigir_titular(usuario_id)
        if reserva_id != RESERVA:
            raise no_encontrado()
        self.version_usuario += 1
        return self.version_usuario

    def confirmar_reserva(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._registrar(
            "confirmar_reserva", usuario_id, reserva_id, dict(cuerpo), **kwargs
        )
        self._exigir_titular(usuario_id)
        if reserva_id != RESERVA:
            raise no_encontrado()
        return self._resultado_reserva()

    def resolver_conflicto(
        self,
        usuario_id: UUID,
        reserva_id: UUID,
        conflicto_id: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._registrar(
            "resolver_conflicto",
            usuario_id,
            reserva_id,
            conflicto_id,
            dict(cuerpo),
            **kwargs,
        )
        self._exigir_titular(usuario_id)
        if reserva_id != RESERVA or conflicto_id != CONFLICTO:
            raise no_encontrado()
        return self._resultado_reserva()

    def mover_reserva(
        self,
        usuario_id: UUID,
        viaje_id: UUID,
        reserva_id: UUID,
        **kwargs: Any,
    ) -> int:
        self._registrar(
            "mover_reserva", usuario_id, viaje_id, reserva_id, **kwargs
        )
        self._exigir_titular(usuario_id)
        if viaje_id != VIAJE or reserva_id != RESERVA:
            raise no_encontrado()
        self.version_usuario += 1
        return self.version_usuario

    def archivar_viaje(
        self, usuario_id: UUID, viaje_id: UUID, **kwargs: Any
    ) -> int:
        self._registrar("archivar_viaje", usuario_id, viaje_id, **kwargs)
        self._exigir_titular(usuario_id)
        if viaje_id != VIAJE:
            raise no_encontrado()
        self.version_usuario += 1
        return self.version_usuario

    def eliminar_viaje(
        self, usuario_id: UUID, viaje_id: UUID, **kwargs: Any
    ) -> int:
        self._registrar("eliminar_viaje", usuario_id, viaje_id, **kwargs)
        self._exigir_titular(usuario_id)
        if viaje_id != VIAJE:
            raise no_encontrado()
        self.version_usuario += 1
        return self.version_usuario

    # --- ClienteDeAsistente ---

    def abrir_sesion(
        self,
        authorization: str,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._registrar(
            "abrir_sesion", authorization, clave, dict(cuerpo), **kwargs
        )
        return self.sesion

    def ver_sesion(
        self, authorization: str, sesion_id: UUID, **kwargs: Any
    ) -> dict[str, Any]:
        self._registrar("ver_sesion", authorization, sesion_id, **kwargs)
        if sesion_id != SESION_ID:
            raise no_encontrado()
        return self.sesion

    def enviar_mensaje(
        self,
        authorization: str,
        sesion_id: UUID,
        clave: UUID,
        cuerpo: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._registrar(
            "enviar_mensaje",
            authorization,
            sesion_id,
            clave,
            dict(cuerpo),
            **kwargs,
        )
        if sesion_id != SESION_ID:
            raise no_encontrado()
        return {
            "intencion": "proximoTramo",
            "mensajes": ["Tu próximo tramo sale el 1/12 a las 10:00."],
            "viajeId": str(VIAJE),
        }


@pytest.fixture
def doble(observacion):
    return DobleDownstream(observacion)


@pytest.fixture
def cliente(doble, contratos):
    bff = BffWeb(
        contratos=contratos,
        lector=doble,
        escritor=doble,
        asistente=doble,
        secreto_jwt=SECRETO_JWT,
    )
    return TestClient(bff.app())


@pytest.fixture
def alta(observacion):
    segmento = copy.deepcopy(observacion["segmentos"][0])
    del segmento["versionTipo"]
    return {"segmentos": [segmento]}


def _problema(contratos, respuesta, estado: int) -> dict[str, Any]:
    assert respuesta.status_code == estado, respuesta.text
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    contratos.validar(PROBLEMA, respuesta.json())
    return respuesta.json()


# --- panel, caché y ETag (UC-3, QA-02, ADR-0018, ADR-0019, ADR-0027) ------------------------


def test_obtener_panel_devuelve_v1_cache_privada_y_revalida_con_etag(
    cliente, doble, contratos
):
    respuesta = cliente.get(
        "/panel",
        headers={
            **_sesion(),
            "X-Min-Version": "1",
            "Accept-Language": "es-AR",
            "traceparent": "00-traza-1",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(TIPO)
    assert respuesta.headers["cache-control"] == "private, no-cache"
    etag = respuesta.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    contratos.validar(PANEL, respuesta.json())
    assert doble.llamadas[-1] == (
        "leer_panel",
        (USUARIO,),
        {"min_version": 1, "traceparent": "00-traza-1"},
    )

    # Mismo ETag → 304 Not Modified sin cuerpo (ADR-0019).
    sin_cambios = cliente.get(
        "/panel", headers={**_sesion(), "If-None-Match": etag}
    )
    assert sin_cambios.status_code == 304
    assert sin_cambios.content == b""
    assert sin_cambios.headers["etag"] == etag
    assert sin_cambios.headers["cache-control"] == "private, no-cache"

    # ETag débil o comodín también coinciden.
    assert (
        cliente.get(
            "/panel", headers={**_sesion(), "If-None-Match": f"W/{etag}"}
        ).status_code
        == 304
    )
    assert (
        cliente.get(
            "/panel", headers={**_sesion(), "If-None-Match": "*"}
        ).status_code
        == 304
    )

    # Si el panel cambia (sube versionUsuario), el ETag viejo devuelve 200 con ETag nuevo.
    doble.version_usuario = 2
    actualizado = cliente.get(
        "/panel", headers={**_sesion(), "If-None-Match": etag}
    )
    assert actualizado.status_code == 200
    assert actualizado.headers["etag"] != etag


# --- viajes (RF-08, ADR-0018, ADR-0019, ADR-0028) -------------------------------------------


def test_listar_y_obtener_viaje_con_etag_y_cache_privada(
    cliente, doble, contratos
):
    lista = cliente.get(
        "/viajes",
        params={"estado": "Archivado", "limite": 10},
        headers=_sesion(),
    )
    assert lista.status_code == 200
    assert lista.headers["content-type"].startswith(TIPO)
    assert lista.headers["cache-control"] == "private, no-cache"
    contratos.validar(
        "openapi/bff-web.yaml#/paths/~1viajes/get/responses/200/content/"
        "application~1vnd.trotamundos.v1+json/schema",
        lista.json(),
    )

    detalle = cliente.get(
        f"/viajes/{VIAJE}",
        headers={**_sesion(), "X-Min-Version": "1"},
    )
    assert detalle.status_code == 200
    assert detalle.headers["content-type"].startswith(TIPO)
    assert detalle.headers["cache-control"] == "private, no-cache"
    etag = detalle.headers["etag"]
    contratos.validar(VIAJE_SCHEMA, detalle.json())

    assert (
        cliente.get(
            f"/viajes/{VIAJE}",
            headers={**_sesion(), "If-None-Match": etag},
        ).status_code
        == 304
    )

    # Viaje ajeno o inexistente → 404 opaco idéntico (ADR-0028).
    ajeno = _problema(
        contratos,
        cliente.get(f"/viajes/{VIAJE}", headers=_sesion(OTRO)),
        404,
    )
    inexistente = _problema(
        contratos,
        cliente.get(f"/viajes/{uuid4()}", headers=_sesion()),
        404,
    )
    assert ajeno == inexistente and "detail" not in ajeno


def test_comandos_de_viaje_devuelven_204_con_version_usuario(cliente, contratos):
    movida = cliente.put(
        f"/viajes/{VIAJE}/reservas/{RESERVA}", headers=_sesion()
    )
    assert movida.status_code == 204
    assert movida.headers["x-version-usuario"] == "2"

    archivado = cliente.post(f"/viajes/{VIAJE}/archivo", headers=_sesion())
    assert archivado.status_code == 204
    assert archivado.headers["x-version-usuario"] == "3"

    eliminado = cliente.delete(f"/viajes/{VIAJE}", headers=_sesion())
    assert eliminado.status_code == 204
    assert eliminado.headers["x-version-usuario"] == "4"

    _problema(
        contratos,
        cliente.delete(f"/viajes/{VIAJE}", headers=_sesion(OTRO)),
        404,
    )


# --- reservas (UC-4, RF-06, ADR-0013, ADR-0014, ADR-0015, ADR-0018) -------------------------


def test_ciclo_de_comandos_de_reserva_propaga_version_usuario(
    cliente, alta, contratos
):
    clave = str(uuid4())
    creada = cliente.post(
        "/reservas",
        content=json.dumps(alta),
        headers={
            **_sesion(),
            "Idempotency-Key": clave,
            "Content-Type": TIPO,
        },
    )
    assert creada.status_code == 201
    assert creada.headers["content-type"].startswith(TIPO)
    assert creada.headers["x-version-usuario"] == "2"
    contratos.validar(RESULTADO, creada.json())

    editada = cliente.put(
        f"/reservas/{RESERVA}",
        content=json.dumps({"version": 1}),
        headers={**_sesion(), "Content-Type": TIPO},
    )
    assert editada.status_code == 200
    assert editada.headers["x-version-usuario"] == "3"
    contratos.validar(RESULTADO, editada.json())

    confirmada = cliente.post(
        f"/reservas/{RESERVA}/confirmacion",
        content=json.dumps({"decision": "confirmar"}),
        headers={**_sesion(), "Content-Type": TIPO},
    )
    assert confirmada.status_code == 200
    assert confirmada.headers["x-version-usuario"] == "4"
    contratos.validar(RESULTADO, confirmada.json())

    resuelta = cliente.post(
        f"/reservas/{RESERVA}/conflictos/{CONFLICTO}/resolucion",
        content=json.dumps({"eleccion": "mantenerFijado"}),
        headers={**_sesion(), "Content-Type": TIPO},
    )
    assert resuelta.status_code == 200
    assert resuelta.headers["x-version-usuario"] == "5"
    contratos.validar(RESULTADO, resuelta.json())

    baja = cliente.delete(f"/reservas/{RESERVA}", headers=_sesion())
    assert baja.status_code == 204
    assert baja.headers["x-version-usuario"] == "6"


# --- catálogo público de tipos de segmento (ADR-0011, ADR-0019) -----------------------------


def test_tipos_de_segmento_es_publico_y_cacheable_en_edge(cliente, contratos):
    respuesta = cliente.get("/tipos-de-segmento")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(TIPO)
    assert (
        respuesta.headers["cache-control"]
        == "public, max-age=300, stale-while-revalidate=3600"
    )
    contratos.validar(
        "openapi/bff-web.yaml#/paths/~1tipos-de-segmento/get/responses/200/"
        "content/application~1vnd.trotamundos.v1+json/schema",
        respuesta.json(),
    )


# --- asistente virtual expuesto por bff-web (Opción B, ADR-0005, ADR-0034) ------------------


def test_rutas_del_asistente_virtual_en_bff_web(cliente, contratos):
    abierta = cliente.post(
        "/asistente/sesiones",
        content=json.dumps({"viajeId": str(VIAJE)}),
        headers={
            **_sesion(),
            "Idempotency-Key": str(uuid4()),
            "Content-Type": TIPO,
        },
    )
    assert abierta.status_code == 201
    assert abierta.headers["content-type"].startswith(TIPO)
    contratos.validar(SESION_SCHEMA, abierta.json())

    vista = cliente.get(
        f"/asistente/sesiones/{SESION_ID}", headers=_sesion()
    )
    assert vista.status_code == 200
    assert vista.headers["content-type"].startswith(TIPO)
    assert vista.headers["cache-control"] == "private, no-cache"
    contratos.validar(SESION_SCHEMA, vista.json())

    turno = cliente.post(
        f"/asistente/sesiones/{SESION_ID}/mensajes",
        content=json.dumps({"texto": "¿A qué hora sale mi próximo tramo?"}),
        headers={
            **_sesion(),
            "Idempotency-Key": str(uuid4()),
            "Content-Type": TIPO,
        },
    )
    assert turno.status_code == 200
    assert turno.headers["content-type"].startswith(TIPO)
    contratos.validar(RESPUESTA_SCHEMA, turno.json())

    _problema(
        contratos,
        cliente.get(f"/asistente/sesiones/{uuid4()}", headers=_sesion()),
        404,
    )


# --- autenticación y validación contra contratos (ADR-0007, ADR-0009) -----------------------


@pytest.mark.parametrize(
    "metodo, ruta, cuerpo",
    [
        ("GET", "/panel", None),
        ("GET", "/viajes", None),
        ("GET", f"/viajes/{VIAJE}", None),
        ("DELETE", f"/viajes/{VIAJE}", None),
        ("POST", f"/viajes/{VIAJE}/archivo", None),
        ("PUT", f"/viajes/{VIAJE}/reservas/{RESERVA}", None),
        ("POST", "/reservas", {"segmentos": []}),
        ("PUT", f"/reservas/{RESERVA}", {"version": 1}),
        ("DELETE", f"/reservas/{RESERVA}", None),
        ("POST", f"/reservas/{RESERVA}/confirmacion", {"decision": "confirmar"}),
        (
            "POST",
            f"/reservas/{RESERVA}/conflictos/{CONFLICTO}/resolucion",
            {"eleccion": "mantenerFijado"},
        ),
        ("POST", "/asistente/sesiones", {}),
        ("GET", f"/asistente/sesiones/{SESION_ID}", None),
        ("POST", f"/asistente/sesiones/{SESION_ID}/mensajes", {"texto": "hola"}),
    ],
)
def test_toda_ruta_autenticada_rechaza_peticiones_sin_sesion_o_con_sesion_vencida(
    cliente, contratos, metodo, ruta, cuerpo
):
    cabeceras = {"Idempotency-Key": str(uuid4())}
    _problema(
        contratos,
        cliente.request(metodo, ruta, json=cuerpo, headers=cabeceras),
        401,
    )
    _problema(
        contratos,
        cliente.request(
            metodo,
            ruta,
            json=cuerpo,
            headers={**cabeceras, **_sesion(vencido=True)},
        ),
        401,
    )


@pytest.mark.parametrize(
    "metodo, ruta, cuerpo, params",
    [
        ("GET", "/viajes", None, {"estado": "Inventado"}),
        ("GET", "/viajes", None, {"cursor": "invalido"}),
        ("GET", "/viajes", None, {"limite": 500}),
        ("POST", "/reservas", {"segmentos": []}, None),
        ("PUT", f"/reservas/{RESERVA}", {}, None),
        (
            "POST",
            f"/reservas/{RESERVA}/confirmacion",
            {"decision": "quizas"},
            None,
        ),
        (
            "POST",
            f"/reservas/{RESERVA}/conflictos/{CONFLICTO}/resolucion",
            {"eleccion": "otra"},
            None,
        ),
        ("POST", "/asistente/sesiones", {"viajeId": "no-es-uuid"}, None),
        ("POST", f"/asistente/sesiones/{SESION_ID}/mensajes", {}, None),
    ],
)
def test_solicitudes_que_no_cumplen_el_contrato_responden_400(
    cliente, contratos, metodo, ruta, cuerpo, params
):
    cabeceras = {**_sesion(), "Idempotency-Key": str(uuid4())}
    respuesta = cliente.request(
        metodo, ruta, json=cuerpo, params=params, headers=cabeceras
    )
    _problema(contratos, respuesta, 400)


# --- adaptadores HTTP y traducción de errores aguas abajo -----------------------------------


def test_clientes_http_traducen_errores_y_caidas_de_servicios_aguas_abajo(
    contratos,
):
    remoto = FastAPI()
    instalar_manejadores(remoto)
    estado = {"codigo": 409}

    @remoto.post("/viajes/{_id}/archivo")
    def archivar(_id: UUID):
        if estado["codigo"] == 409:
            raise Problema(409, "Conflicto", "El viaje ya está archivado")
        if estado["codigo"] == 404:
            raise no_encontrado()
        return Response(status_code=500)

    http = TestClient(remoto)
    lector = clientes.LectorDeItinerarioHttp("http://itinerary-lectura", cliente=http)
    escritor = clientes.EscritorDeItinerarioHttp(
        "http://itinerary-escritura", cliente=http
    )
    asistente = clientes.ClienteDeAsistenteHttp(
        "http://virtual-assistant", cliente=http
    )
    bff = TestClient(
        BffWeb(
            contratos=contratos,
            lector=lector,
            escritor=escritor,
            asistente=asistente,
            secreto_jwt=SECRETO_JWT,
        ).app()
    )

    conflicto = _problema(
        contratos, bff.post(f"/viajes/{VIAJE}/archivo", headers=_sesion()), 409
    )
    assert conflicto["detail"] == "El viaje ya está archivado"

    estado["codigo"] = 404
    _problema(
        contratos, bff.post(f"/viajes/{VIAJE}/archivo", headers=_sesion()), 404
    )

    estado["codigo"] = 500
    _problema(
        contratos, bff.post(f"/viajes/{VIAJE}/archivo", headers=_sesion()), 503
    )

    # Error de red (httpx.ConnectError) → 503 Problema.
    def _caido(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    cliente_caido = httpx.Client(transport=httpx.MockTransport(_caido))
    bff_caido = TestClient(
        BffWeb(
            contratos=contratos,
            lector=clientes.LectorDeItinerarioHttp(
                "http://caido", cliente=cliente_caido
            ),
            escritor=clientes.EscritorDeItinerarioHttp(
                "http://caido", cliente=cliente_caido
            ),
            asistente=clientes.ClienteDeAsistenteHttp(
                "http://caido", cliente=cliente_caido
            ),
            secreto_jwt=SECRETO_JWT,
        ).app()
    )
    _problema(contratos, bff_caido.get("/panel", headers=_sesion()), 503)
    _problema(
        contratos,
        bff_caido.delete(f"/reservas/{RESERVA}", headers=_sesion()),
        503,
    )
    _problema(
        contratos,
        bff_caido.get(f"/asistente/sesiones/{SESION_ID}", headers=_sesion()),
        503,
    )


def test_una_divergencia_entre_las_rutas_y_el_contrato_impide_arrancar(
    doble, contratos, monkeypatch
):
    original = contratos.documento

    def sin_panel(relativa: str) -> dict[str, Any]:
        doc = original(relativa)
        if relativa == "openapi/bff-web.yaml":
            doc["paths"].pop("/panel", None)
        return doc

    monkeypatch.setattr(contratos, "documento", sin_panel)
    with pytest.raises(RuntimeError, match="/panel"):
        api.crear_app(
            BffWeb(
                contratos=contratos,
                lector=doble,
                escritor=doble,
                asistente=doble,
                secreto_jwt=SECRETO_JWT,
            ),
            contratos,
            SECRETO_JWT,
        )
