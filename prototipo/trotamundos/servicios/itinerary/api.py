"""Módulo `api` (vista N2): la API REST interna de `itinerary` (`contratos/openapi/itinerary.yaml`).

Es uno de los dos puntos de entrada del elemento (regla I2): los comandos van a `gestion_manual`
y las lecturas a `proyeccion_panel`, a través del puerto `Itinerario`, que implementa el armado
del elemento (`servicio`). Los cuerpos se validan contra los esquemas del contrato, sin
redefinirlos (ADR-0036), y todo error sale como `Problema` (`comun.errores`).

En este paso expone las operaciones de reservas y de tipos de segmento. Las de viajes y panel
llegan con el paso 5; el vale interno (ADR-0028) y `X-Deadline-Ms` (ADR-0020), con los pasos que
implementan esas decisiones (ver el plan en el README del prototipo).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Protocol, TypeVar
from uuid import UUID

from fastapi import Body, FastAPI, Header
from fastapi.responses import JSONResponse, Response

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.errores import Problema, instalar_manejadores, no_encontrado
from trotamundos.servicios.itinerary.gestion_manual import ErrorDeComando, NoEncontrada

_COMUN = "openapi/comun.yaml#/components/schemas/"
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

    def leer_reserva(self, usuario_id: UUID, reserva_id: UUID) -> dict[str, Any] | None: ...

    def tipos_de_segmento(self) -> list[dict[str, Any]]: ...


def crear_app(itinerario: Itinerario, contratos: Contratos,
              lifespan: Callable[[FastAPI], AbstractAsyncContextManager] | None = None) -> FastAPI:
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
        reserva = itinerario.leer_reserva(usuario_id, id)
        if reserva is None:
            raise no_encontrado()
        return JSONResponse(reserva)

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

    @app.get("/tipos-de-segmento")
    def leer_tipos_de_segmento() -> JSONResponse:
        return JSONResponse(itinerario.tipos_de_segmento())

    return app


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
