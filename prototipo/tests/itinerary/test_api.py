"""API interna de itinerary (`contratos/openapi/itinerary.yaml`, ADR-0009, ADR-0036) sobre un
puerto falso.

Comprueba lo que es propio del módulo `api`: que los cuerpos se validan contra el contrato, que
los errores de los comandos salen como `Problema` con el código que declara el contrato y que
las respuestas cumplen sus esquemas. El recorrido real contra PostgreSQL está en
`test_servicio.py`.
"""

import copy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.itinerary import gestion_manual as gm
from trotamundos.servicios.itinerary.api import crear_app

USUARIO = "00000000-0000-4000-8000-000000000001"
RESERVA = "00000000-0000-4000-8000-0000000000aa"
PROBLEMA = "openapi/comun.yaml#/components/schemas/Problema"
RESULTADO = "openapi/comun.yaml#/components/schemas/ResultadoComandoReserva"


class ItinerarioFalso:
    """Anota las llamadas y responde lo que se le indique (o lanza `error`)."""

    def __init__(self, reserva: dict):
        self.reserva, self.error, self.llamadas = reserva, None, []

    def _responder(self, nombre, *args, **kwargs):
        self.llamadas.append((nombre, args, kwargs))
        if self.error:
            raise self.error
        return {"reserva": self.reserva, "versionUsuario": 3}

    def crear_reserva(self, *args, **kwargs):
        return 201, self._responder("crear", *args, **kwargs)

    def editar_reserva(self, *args, **kwargs):
        return self._responder("editar", *args, **kwargs)

    def eliminar_reserva(self, *args, **kwargs):
        self._responder("eliminar", *args, **kwargs)

    def confirmar_reserva(self, *args, **kwargs):
        return self._responder("confirmar", *args, **kwargs)

    def resolver_conflicto(self, *args, **kwargs):
        return self._responder("resolver", *args, **kwargs)

    def leer_reserva(self, usuario_id, reserva_id):
        return self.reserva if str(reserva_id) == RESERVA else None

    def tipos_de_segmento(self):
        return registro_por_omision().documentos()


@pytest.fixture
def reserva(observacion):
    segmento = {**copy.deepcopy(observacion["segmentos"][0]), "id": str(uuid4()), "orden": 0,
                "estado": "confirmado"}
    return {"id": RESERVA, "estado": "Confirmada", "version": 1, "fuentes": ["correo"],
            "identificadores": observacion["identificadores"], "segmentos": [segmento]}


@pytest.fixture
def falso(reserva):
    return ItinerarioFalso(reserva)


@pytest.fixture
def cliente(falso, contratos):
    return TestClient(crear_app(falso, contratos))


@pytest.fixture
def alta(observacion):
    segmento = copy.deepcopy(observacion["segmentos"][0])
    del segmento["versionTipo"]
    return {"segmentos": [segmento]}


def _cabeceras(**extra) -> dict:
    return {"X-Usuario-Id": USUARIO, **extra}


def _problema(contratos, respuesta, estado: int) -> dict:
    assert respuesta.status_code == estado, respuesta.text
    assert respuesta.headers["content-type"] == "application/problem+json"
    contratos.validar(PROBLEMA, respuesta.json())
    return respuesta.json()


# --- alta ----------------------------------------------------------------------------------

def test_el_alta_pasa_usuario_clave_y_traza_al_elemento(cliente, falso, alta, contratos):
    clave = str(uuid4())
    respuesta = cliente.post("/reservas", json=alta, headers=_cabeceras(
        **{"Idempotency-Key": clave, "traceparent": "00-t-s-01"}))

    assert respuesta.status_code == 201
    contratos.validar(RESULTADO, respuesta.json())
    [(nombre, args, kwargs)] = falso.llamadas
    assert (nombre, args[:3], kwargs) == ("crear", (UUID(USUARIO), UUID(clave), alta),
                                          {"traceparent": "00-t-s-01"})


@pytest.mark.parametrize("cabeceras", [
    {},                                                      # sin X-Usuario-Id ni clave
    {"X-Usuario-Id": USUARIO},                               # sin Idempotency-Key
    {"X-Usuario-Id": "no-es-uuid", "Idempotency-Key": str(uuid4())},
])
def test_el_alta_exige_sus_cabeceras(cliente, falso, alta, contratos, cabeceras):
    _problema(contratos, cliente.post("/reservas", json=alta, headers=cabeceras), 400)
    assert falso.llamadas == []


def test_un_cuerpo_que_no_cumple_el_contrato_es_400_con_los_errores(cliente, falso, contratos):
    respuesta = cliente.post("/reservas", json={"segmentos": []},
                             headers=_cabeceras(**{"Idempotency-Key": str(uuid4())}))

    problema = _problema(contratos, respuesta, 400)
    assert problema["errores"][0]["campo"] == "segmentos"
    assert falso.llamadas == []


# --- errores de los comandos ---------------------------------------------------------------

@pytest.mark.parametrize("error, estado", [
    (gm.NoEncontrada(), 404),
    (gm.ConflictoDeComando("versión vieja"), 409),
    (gm.SolicitudInvalida("detalle inválido", [{"campo": "segmentos[0].detalle", "mensaje": "x"}]), 400),
])
def test_los_errores_de_los_comandos_salen_como_problema(cliente, falso, contratos, error, estado):
    falso.error = error

    respuesta = cliente.put(f"/reservas/{RESERVA}", json={"version": 1}, headers=_cabeceras())

    problema = _problema(contratos, respuesta, estado)
    if estado == 404:
        assert "detail" not in problema  # no revela si existe (ADR-0028)


def test_editar_confirmar_y_resolver_validan_su_cuerpo(cliente, falso, contratos):
    base = f"/reservas/{RESERVA}"
    for ruta, metodo, cuerpo in [
        (base, "put", {}),                                           # falta version
        (f"{base}/confirmacion", "post", {"decision": "quizas"}),
        (f"{base}/conflictos/{uuid4()}/resolucion", "post", {"eleccion": "otra"}),
    ]:
        _problema(contratos, cliente.request(metodo, ruta, json=cuerpo, headers=_cabeceras()), 400)
    assert falso.llamadas == []


def test_confirmar_y_resolver_responden_el_resultado(cliente, falso, contratos):
    base = f"/reservas/{RESERVA}"
    for ruta, cuerpo in [(f"{base}/confirmacion", {"decision": "confirmar"}),
                         (f"{base}/conflictos/{uuid4()}/resolucion", {"eleccion": "mantenerFijado"})]:
        respuesta = cliente.post(ruta, json=cuerpo, headers=_cabeceras())
        assert respuesta.status_code == 200
        contratos.validar(RESULTADO, respuesta.json())
    assert [n for n, *_ in falso.llamadas] == ["confirmar", "resolver"]


# --- lecturas y baja -----------------------------------------------------------------------

def test_leer_una_reserva(cliente, contratos):
    respuesta = cliente.get(f"/reservas/{RESERVA}", headers=_cabeceras())
    assert respuesta.status_code == 200
    contratos.validar("openapi/comun.yaml#/components/schemas/Reserva", respuesta.json())

    _problema(contratos, cliente.get(f"/reservas/{uuid4()}", headers=_cabeceras()), 404)


def test_la_baja_responde_204_sin_cuerpo(cliente, falso):
    respuesta = cliente.delete(f"/reservas/{RESERVA}", headers=_cabeceras())
    assert (respuesta.status_code, respuesta.content) == (204, b"")
    assert falso.llamadas[0][0] == "eliminar"


def test_tipos_de_segmento_sin_usuario(cliente, contratos):
    respuesta = cliente.get("/tipos-de-segmento")
    assert respuesta.status_code == 200
    contratos.validar("openapi/itinerary.yaml#/paths/~1tipos-de-segmento/get/responses/200"
                      "/content/application~1json/schema", respuesta.json())


def test_no_publica_un_openapi_propio(cliente, contratos):
    # El contrato es contratos/openapi/itinerary.yaml; una ruta inexistente es un Problema.
    _problema(contratos, cliente.get("/openapi.json"), 404)


# --- modos de despliegue (ADR-0021) --------------------------------------------------------

def _rutas(app) -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute
    return {(m, r.path) for r in app.router.routes if isinstance(r, APIRoute) for m in r.methods}


def test_cada_modo_expone_solo_sus_rutas_segun_el_contrato(falso, contratos):
    completo = _rutas(crear_app(falso, contratos))
    lectura = _rutas(crear_app(falso, contratos, modo="lectura"))
    escritura = _rutas(crear_app(falso, contratos, modo="escritura"))

    assert lectura | escritura == completo and not lectura & escritura
    assert ("GET", "/panel") in lectura and ("POST", "/reservas") in escritura
    assert {m for m, _ in lectura} == {"GET"}  # en este contrato, leer es GET


def test_itinerary_lectura_no_atiende_comandos(falso, contratos, alta):
    cliente = TestClient(crear_app(falso, contratos, modo="lectura"))
    respuesta = cliente.post("/reservas", json=alta,
                             headers=_cabeceras(**{"Idempotency-Key": str(uuid4())}))

    _problema(contratos, respuesta, 404)  # `/reservas` solo tiene POST: en lectura no existe
    assert falso.llamadas == []
    assert cliente.get(f"/reservas/{RESERVA}", headers=_cabeceras()).status_code == 200


def test_itinerary_escritura_no_atiende_lecturas(falso, contratos):
    cliente = TestClient(crear_app(falso, contratos, modo="escritura"))
    assert cliente.get("/panel", headers=_cabeceras()).status_code == 404
    assert cliente.delete(f"/reservas/{RESERVA}", headers=_cabeceras()).status_code == 204


def test_un_modo_desconocido_o_una_ruta_fuera_del_contrato_no_arrancan(falso, contratos, monkeypatch):
    with pytest.raises(ValueError):
        crear_app(falso, contratos, modo="mixto")

    from trotamundos.servicios.itinerary import api
    original = api._etiquetas
    monkeypatch.setattr(api, "_etiquetas", lambda c: {k: v for k, v in original(c).items()
                                                      if k != ("GET", "/panel")})
    with pytest.raises(RuntimeError, match="GET /panel"):
        crear_app(falso, contratos)
