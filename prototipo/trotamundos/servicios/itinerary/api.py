"""Módulo `api` (vista N2): la API REST interna de `itinerary` (`contratos/openapi/itinerary.yaml`).

Es uno de los dos puntos de entrada del elemento (regla I2): los comandos van a `gestion_manual`
y las lecturas a `proyeccion_panel`, a través del puerto `Itinerario`, que implementa el armado
del elemento (`servicio`). Los cuerpos se validan contra los esquemas del contrato, sin
redefinirlos (ADR-0036), y todo error sale como `Problema` (`comun.errores`).

Expone las operaciones del contrato: panel, viajes, reservas y tipos de segmento. Según el modo
de despliegue (ADR-0021) registra solo las de lectura (`itinerary-lectura`), solo los comandos
(`itinerary-escritura`) o todas; cada ruta se clasifica por su etiqueta en el contrato. El vale
interno (ADR-0028) y `X-Deadline-Ms` (ADR-0020) llegan con los pasos que implementan esas
decisiones (ver el plan en el README del prototipo).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol, TypeVar
from uuid import UUID

from fastapi import Body, FastAPI, Header, Query
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse, Response

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores, no_encontrado
from trotamundos.servicios.itinerary.gestion_manual import ErrorDeComando, NoEncontrada

_CONTRATO = "openapi/itinerary.yaml"
_COMUN = "openapi/comun.yaml#/components/schemas/"
# Modos de despliegue (ADR-0021, iteración 3 §5.4): qué etiquetas del contrato atiende cada uno.
MODOS = {"completo": frozenset({"lectura", "comando"}), "lectura": frozenset({"lectura"}),
         "escritura": frozenset({"comando"})}
_CUERPO = "openapi/itinerary.yaml#/paths/{ruta}/post/requestBody/content/application~1json/schema"
CUERPO_CONFIRMACION = _CUERPO.format(ruta="~1reservas~1{id}~1confirmacion")
CUERPO_RESOLUCION = _CUERPO.format(ruta="~1reservas~1{id}~1conflictos~1{cid}~1resolucion")

T = TypeVar("T")


class Itinerario(Protocol):
    """Lo que la API necesita del elemento. Cada método es una transacción."""

    def crear_reserva(self, usuario_id: UUID, clave: UUID, cuerpo: Mapping[str, Any], *,
                      traceparent: str | None = None) -> tuple[int, dict[str, Any]]: ...

    def editar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                       traceparent: str | None = None) -> dict[str, Any]: ...

    def eliminar_reserva(self, usuario_id: UUID, reserva_id: UUID, *,
                         traceparent: str | None = None) -> None: ...

    def confirmar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                          traceparent: str | None = None) -> dict[str, Any]: ...

    def resolver_conflicto(self, usuario_id: UUID, reserva_id: UUID, conflicto_id: UUID,
                           cuerpo: Mapping[str, Any], *,
                           traceparent: str | None = None) -> dict[str, Any]: ...

    def mover_reserva(self, usuario_id: UUID, viaje_id: UUID, reserva_id: UUID, *,
                      traceparent: str | None = None) -> None: ...

    def archivar_viaje(self, usuario_id: UUID, viaje_id: UUID, *,
                       traceparent: str | None = None) -> None: ...

    def eliminar_viaje(self, usuario_id: UUID, viaje_id: UUID, *,
                       traceparent: str | None = None) -> None: ...

    def leer_panel(self, usuario_id: UUID) -> dict[str, Any]: ...

    def leer_viajes(self, usuario_id: UUID, *, estado: str | None = None,
                    cursor: str | None = None, limite: int = 20) -> dict[str, Any]: ...

    def leer_viaje(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None: ...

    def leer_instantanea(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None: ...

    def leer_reserva(self, usuario_id: UUID, reserva_id: UUID) -> dict[str, Any] | None: ...

    def tipos_de_segmento(self) -> list[dict[str, Any]]: ...


def crear_app(itinerario: Itinerario, contratos: Contratos,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager] | None = None,
              modo: str = "completo") -> FastAPI:
    """La API con las rutas del modo indicado (`completo`, `lectura` o `escritura`)."""
    if modo not in MODOS:
        raise ValueError(f"Modo de despliegue desconocido: {modo!r}")
    # El contrato es `contratos/openapi/itinerary.yaml`: no se publica otro generado.
    app = FastAPI(title="itinerary", openapi_url=None, docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    instalar_manejadores(app)

    def validar(referencia: str, cuerpo: Any) -> None:
        errores = contratos.errores(referencia, cuerpo)
        if errores:
            raise Problema(400, "Solicitud inválida", errores=[_error(e) for e in errores])

    # Las rutas son síncronas: FastAPI las corre en su pool de hilos y la base no bloquea el
    # bucle de eventos.

    @app.post("/reservas", status_code=201)
    def crear_reserva(cuerpo: dict[str, Any] = Body(...),
                      usuario_id: UUID = Header(alias="X-Usuario-Id"),
                      clave: UUID = Header(alias="Idempotency-Key"),
                      traceparent: str | None = Header(default=None)) -> JSONResponse:
        validar(_COMUN + "ReservaNueva", cuerpo)
        estado, respuesta = _ejecutar(lambda: itinerario.crear_reserva(
            usuario_id, clave, cuerpo, traceparent=traceparent))
        return JSONResponse(respuesta, status_code=estado)

    @app.get("/reservas/{id}")
    def leer_reserva(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id")) -> JSONResponse:
        return JSONResponse(_o_404(itinerario.leer_reserva(usuario_id, id)))

    @app.put("/reservas/{id}")
    def editar_reserva(id: UUID, cuerpo: dict[str, Any] = Body(...),
                       usuario_id: UUID = Header(alias="X-Usuario-Id"),
                       traceparent: str | None = Header(default=None)) -> JSONResponse:
        validar(_COMUN + "EdicionReserva", cuerpo)
        return JSONResponse(_ejecutar(lambda: itinerario.editar_reserva(
            usuario_id, id, cuerpo, traceparent=traceparent)))

    @app.delete("/reservas/{id}", status_code=204)
    def eliminar_reserva(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id"),
                         traceparent: str | None = Header(default=None)) -> Response:
        _ejecutar(lambda: itinerario.eliminar_reserva(usuario_id, id, traceparent=traceparent))
        return Response(status_code=204)

    @app.post("/reservas/{id}/confirmacion")
    def confirmar_reserva(id: UUID, cuerpo: dict[str, Any] = Body(...),
                          usuario_id: UUID = Header(alias="X-Usuario-Id"),
                          traceparent: str | None = Header(default=None)) -> JSONResponse:
        validar(CUERPO_CONFIRMACION, cuerpo)
        return JSONResponse(_ejecutar(lambda: itinerario.confirmar_reserva(
            usuario_id, id, cuerpo, traceparent=traceparent)))

    @app.post("/reservas/{id}/conflictos/{cid}/resolucion")
    def resolver_conflicto(id: UUID, cid: UUID, cuerpo: dict[str, Any] = Body(...),
                           usuario_id: UUID = Header(alias="X-Usuario-Id"),
                           traceparent: str | None = Header(default=None)) -> JSONResponse:
        validar(CUERPO_RESOLUCION, cuerpo)
        return JSONResponse(_ejecutar(lambda: itinerario.resolver_conflicto(
            usuario_id, id, cid, cuerpo, traceparent=traceparent)))

    # --- panel y viajes -----------------------------------------------------------------

    @app.get("/panel")
    def leer_panel(usuario_id: UUID = Header(alias="X-Usuario-Id"),
                   min_version: int | None = Header(default=None, alias="X-Min-Version", ge=0)
                   ) -> JSONResponse:
        # La proyección se actualiza en la misma transacción que cada cambio, así que nunca
        # está detrás de una versión que el usuario ya vio: `X-Min-Version` siempre se cumple
        # en una sola región (ADR-0018).
        return JSONResponse(itinerario.leer_panel(usuario_id))

    @app.get("/viajes")
    def leer_viajes(usuario_id: UUID = Header(alias="X-Usuario-Id"),
                    estado: str | None = Query(default=None),
                    cursor: str | None = Query(default=None),
                    limite: int = Query(default=20, ge=1, le=100)) -> JSONResponse:
        if estado is not None:
            validar(_COMUN + "EstadoViaje", estado)
        try:
            return JSONResponse(itinerario.leer_viajes(usuario_id, estado=estado, cursor=cursor,
                                                       limite=limite))
        except ValueError as error:  # cursor que no emitimos nosotros
            raise Problema(400, "Solicitud inválida", errores=[
                {"campo": "cursor", "mensaje": str(error)}]) from error

    @app.get("/viajes/{id}")
    def leer_viaje(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id")) -> JSONResponse:
        return JSONResponse(_o_404(itinerario.leer_viaje(usuario_id, id)))

    @app.delete("/viajes/{id}", status_code=204)
    def eliminar_viaje(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id"),
                       traceparent: str | None = Header(default=None)) -> Response:
        _ejecutar(lambda: itinerario.eliminar_viaje(usuario_id, id, traceparent=traceparent))
        return Response(status_code=204)

    @app.get("/viajes/{id}/instantanea")
    def leer_instantanea(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id")) -> JSONResponse:
        return JSONResponse(_o_404(itinerario.leer_instantanea(usuario_id, id)))

    @app.post("/viajes/{id}/archivo", status_code=204)
    def archivar_viaje(id: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id"),
                       traceparent: str | None = Header(default=None)) -> Response:
        _ejecutar(lambda: itinerario.archivar_viaje(usuario_id, id, traceparent=traceparent))
        return Response(status_code=204)

    @app.put("/viajes/{vid}/reservas/{rid}", status_code=204)
    def mover_reserva(vid: UUID, rid: UUID, usuario_id: UUID = Header(alias="X-Usuario-Id"),
                      traceparent: str | None = Header(default=None)) -> Response:
        _ejecutar(lambda: itinerario.mover_reserva(usuario_id, vid, rid, traceparent=traceparent))
        return Response(status_code=204)

    @app.get("/tipos-de-segmento")
    def leer_tipos_de_segmento() -> JSONResponse:
        return JSONResponse(itinerario.tipos_de_segmento())

    _quedarse_con(app, _etiquetas(contratos), MODOS[modo])
    return app


def _etiquetas(contratos: Contratos) -> dict[tuple[str, str], str]:
    """(método, ruta) → etiqueta (`lectura` o `comando`) de cada operación del contrato."""
    return {(metodo.upper(), ruta): operacion["tags"][0]
            for ruta, operaciones in contratos.documento(_CONTRATO)["paths"].items()
            for metodo, operacion in operaciones.items()
            if isinstance(operacion, dict) and "tags" in operacion}


def _quedarse_con(app: FastAPI, etiquetas: dict[tuple[str, str], str], activas: frozenset) -> None:
    """Deja solo las rutas del modo. Una ruta que no está en el contrato es un error: el código
    no puede exponer nada que el contrato no declare (ADR-0009)."""
    propias = [r for r in app.router.routes if isinstance(r, APIRoute)]
    ajenas = sorted(f"{m} {r.path}" for r in propias for m in r.methods if (m, r.path) not in etiquetas)
    if ajenas:
        raise RuntimeError(f"Rutas que no están en {_CONTRATO}: {', '.join(ajenas)}")
    app.router.routes = [r for r in app.router.routes if not isinstance(r, APIRoute)
                         or any(etiquetas[(m, r.path)] in activas for m in r.methods)]


def _o_404(recurso: T | None) -> T:
    if recurso is None:
        raise no_encontrado()
    return recurso


def _ejecutar(comando: Callable[[], T]) -> T:
    """Traduce los errores de los comandos a `Problema` con su código del contrato."""
    try:
        return comando()
    except NoEncontrada as error:
        # Una reserva inexistente o ajena responde igual y sin detalle (ADR-0028); el detalle
        # solo aparece cuando falta otra cosa, como un conflicto de una reserva propia.
        problema = no_encontrado()
        if error.detalle:
            problema.detail = error.detalle
        raise problema from error
    except ErrorDeComando as error:
        raise Problema(error.status, error.titulo, error.detalle, errores=error.errores) from error


def _error(texto: str) -> dict[str, str]:
    campo, _, mensaje = texto.partition(": ")
    return {"campo": campo.removeprefix("$.").removeprefix("$"), "mensaje": mensaje}
