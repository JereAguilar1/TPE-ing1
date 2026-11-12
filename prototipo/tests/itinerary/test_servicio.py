"""El elemento itinerary de punta a punta contra PostgreSQL (ADR-0012, ADR-0014, ADR-0018).

Cada comando y cada evento consumido es una transacción: el cambio, la outbox, la lectura y
`versionUsuario` se confirman juntos o no queda nada. Sin PostgreSQL se saltean.
"""

import copy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ayudas import USUARIO, instante
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.itinerary import gestion_manual, publicacion
from trotamundos.servicios.itinerary.servicio import Itinerary


@pytest.fixture
def itinerary(dsn, esquema, contratos):
    configuracion = Configuracion.desde_entorno()
    servicio = Itinerary(configuracion, esquema=esquema, contratos=contratos,
                         reloj=lambda: instante(20))
    servicio.crear_esquema()
    servicio.bd = (configuracion.dsn_postgres, esquema)
    return servicio


def _filas(itinerary, consulta: str) -> list[dict]:
    with conectar(*itinerary.bd) as conexion:
        return conexion.execute(consulta).fetchall()


def _extraida(observacion: dict, banda: str = "alta", **sobre) -> Evento:
    return Evento.nuevo("ReservaExtraida", {
        "buzonId": str(uuid4()), "idDeMensaje": "mensaje-42",
        "extractor": {"id": "aerolinea-ar", "version": "1.0"}, "banda": banda,
        "confianza": {"global": 0.95, "porCampo": {}}, "observacion": observacion,
    }, productor="booking-extraction", usuario_id=str(USUARIO), **sobre)


def _observada(observacion: dict, **sobre) -> Evento:
    datos = {**copy.deepcopy(observacion), "fuente": "proveedor", "idDeFuente": "AR/ABC123"}
    return Evento.nuevo("ReservaObservada", {"adaptador": {"id": "ar", "version": "1.0"},
                                             "observacion": datos},
                        productor="provider-sync", usuario_id=str(USUARIO), **sobre)


# --- ingesta (UC-1, UC-2) ------------------------------------------------------------------

def test_un_evento_consumido_deja_la_reserva_la_outbox_y_la_lectura(itinerary, observacion, contratos):
    eventos = itinerary.consumir(_extraida(observacion, traceparent="00-t-s-01"))

    [actualizada] = eventos
    reserva_id = actualizada.carga["reserva"]["id"]
    [salida] = _filas(itinerary, "SELECT * FROM bandeja_salida")
    assert (salida["tipo"], salida["sobre"]["traceparent"]) == ("ReservaActualizada", "00-t-s-01")
    assert itinerary.leer_reserva(USUARIO, reserva_id) == actualizada.carga["reserva"]
    assert _filas(itinerary, "SELECT version FROM usuario_version") == [{"version": 1}]


def test_un_evento_repetido_no_produce_un_segundo_efecto(itinerary, observacion):
    evento = _extraida(observacion)
    itinerary.consumir(evento)

    assert itinerary.consumir(evento) == []
    assert len(_filas(itinerary, "SELECT * FROM bandeja_salida")) == 1
    assert _filas(itinerary, "SELECT version FROM usuario_version") == [{"version": 1}]


def test_la_cancelacion_del_proveedor_se_publica_con_su_causa(itinerary, observacion):
    itinerary.consumir(_extraida(observacion))
    cancelacion = _observada({**observacion, "versionDeFuente": "2026-11-11T00:00:00Z",
                              "cancelada": True}, id_de_causa="disrupcion-7")

    eventos = itinerary.consumir(cancelacion)

    assert [e.tipo for e in eventos] == ["ReservaActualizada", "ReservaCancelada"]
    assert {e.sobre["idDeCausa"] for e in eventos} == {"disrupcion-7"}
    assert eventos[1].carga["fuente"] == "proveedor"


@pytest.mark.parametrize("estropear", [
    lambda o: o["segmentos"][0]["detalle"].pop("numeroDeVuelo"),  # no valida contra el tipo
    lambda o: o.update(fuente="proveedor"),  # ReservaExtraida trae solo correo
])
def test_un_evento_invalido_no_deja_nada_escrito(itinerary, observacion, estropear):
    estropear(observacion)
    with pytest.raises(ErrorDeContrato):
        itinerary.consumir(_extraida(observacion))

    for tabla in ("bandeja_entrada", "bandeja_salida", "reserva", "usuario_version"):
        assert _filas(itinerary, f"SELECT * FROM {tabla}") == [], tabla


# --- comandos ------------------------------------------------------------------------------

@pytest.fixture
def alta(observacion):
    segmento = copy.deepcopy(observacion["segmentos"][0])
    del segmento["versionTipo"]
    return {"identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
            "segmentos": [segmento]}


def test_el_alta_es_idempotente_por_clave(itinerary, alta):
    clave = uuid4()
    primera = itinerary.crear_reserva(USUARIO, clave, alta)
    segunda = itinerary.crear_reserva(USUARIO, clave, copy.deepcopy(alta))

    assert primera == segunda and primera[0] == 201
    assert len(_filas(itinerary, "SELECT * FROM reserva")) == 1
    assert len(_filas(itinerary, "SELECT * FROM bandeja_salida")) == 1

    alta["segmentos"][0]["operador"] = "Otra"
    with pytest.raises(gestion_manual.SolicitudInvalida):
        itinerary.crear_reserva(USUARIO, clave, alta)


def test_version_usuario_crece_con_cada_cambio(itinerary, alta):
    _, creada = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    reserva = creada["reserva"]
    segmento = {k: v for k, v in reserva["segmentos"][0].items()
                if k not in ("id", "orden", "estado", "versionTipo", "fijados")}
    segmento["detalle"]["puerta"] = "12"

    editada = itinerary.editar_reserva(USUARIO, UUID(reserva["id"]),
                                       {"version": reserva["version"], "segmentos": [segmento]})

    assert (creada["versionUsuario"], editada["versionUsuario"]) == (1, 2)
    assert itinerary.leer_reserva(USUARIO, reserva["id"]) == editada["reserva"]


def test_la_baja_saca_la_reserva_de_la_lectura(itinerary, alta):
    _, creada = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    reserva_id = UUID(creada["reserva"]["id"])

    itinerary.eliminar_reserva(USUARIO, reserva_id)

    assert itinerary.leer_reserva(USUARIO, reserva_id) is None
    assert [f["estado"] for f in _filas(itinerary, "SELECT estado FROM reserva")] == ["Descartada"]


def test_si_falla_la_outbox_no_queda_ni_el_cambio(itinerary, alta, monkeypatch):
    def falla(*args):
        raise RuntimeError("la outbox no se pudo escribir")

    monkeypatch.setattr(publicacion, "registrar", falla)
    with pytest.raises(RuntimeError):
        itinerary.crear_reserva(USUARIO, uuid4(), alta)

    for tabla in ("reserva", "observacion", "comando_idempotente", "usuario_version"):
        assert _filas(itinerary, f"SELECT * FROM {tabla}") == [], tabla


def test_otro_usuario_no_ve_la_reserva(itinerary, alta):
    _, creada = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    assert itinerary.leer_reserva(UUID(int=99), creada["reserva"]["id"]) is None
    with pytest.raises(gestion_manual.NoEncontrada):
        itinerary.eliminar_reserva(UUID(int=99), UUID(creada["reserva"]["id"]))


# --- la API sobre el elemento real ---------------------------------------------------------

def test_recorrido_http_de_una_reserva(itinerary, alta, contratos):
    comun = "openapi/comun.yaml#/components/schemas/"
    cabeceras = {"X-Usuario-Id": str(USUARIO)}
    with TestClient(itinerary.app()) as cliente:
        clave = {"Idempotency-Key": str(uuid4())}
        creada = cliente.post("/reservas", json=alta, headers={**cabeceras, **clave})
        assert creada.status_code == 201
        assert cliente.post("/reservas", json=alta, headers={**cabeceras, **clave}).json() \
            == creada.json()
        contratos.validar(comun + "ResultadoComandoReserva", creada.json())
        reserva = creada.json()["reserva"]
        ruta = f"/reservas/{reserva['id']}"

        leida = cliente.get(ruta, headers=cabeceras)
        assert leida.json() == reserva
        contratos.validar(comun + "Reserva", leida.json())

        vieja = cliente.put(ruta, json={"version": reserva["version"] - 1}, headers=cabeceras)
        assert vieja.status_code == 409

        assert cliente.delete(ruta, headers=cabeceras).status_code == 204
        assert cliente.get(ruta, headers=cabeceras).status_code == 404
        assert cliente.delete(ruta, headers=cabeceras).status_code == 404
