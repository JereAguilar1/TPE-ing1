"""El elemento itinerary de punta a punta contra PostgreSQL (ADR-0012, ADR-0014, ADR-0018).

Cada comando y cada evento consumido es una transacción: el cambio, la outbox, la lectura y
`versionUsuario` se confirman juntos o no queda nada. Sin PostgreSQL se saltean.
"""

import copy
import dataclasses
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ayudas import USUARIO, instante
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.itinerary import gestion_manual, publicacion
from trotamundos.servicios.itinerary.viajes import operaciones as viajes
from trotamundos.servicios.itinerary.servicio import Itinerary


@pytest.fixture
def itinerary(dsn, esquema, contratos):
    # Sin broker ni trabajo periódico: estas pruebas los llaman directamente.
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), intervalo_tareas_s=0, broker="")
    reloj = {"ahora": instante(20)}
    servicio = Itinerary(configuracion, esquema=esquema, contratos=contratos,
                         reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.bd, servicio.reloj = (configuracion.dsn_postgres, esquema), reloj
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

    # La reserva en una transacción y su viaje en otra (ADR-0010), los dos en la outbox.
    actualizada, armado = eventos
    assert (actualizada.tipo, armado.tipo) == ("ReservaActualizada", "ViajeArmado")
    reserva_id = actualizada.carga["reserva"]["id"]
    salidas = _filas(itinerary, "SELECT tipo, sobre FROM bandeja_salida ORDER BY creado_en")
    assert [s["tipo"] for s in salidas] == ["ReservaActualizada", "ViajeArmado"]
    assert {s["sobre"]["traceparent"] for s in salidas} == {"00-t-s-01"}
    assert itinerary.leer_reserva(USUARIO, reserva_id) == {
        **actualizada.carga["reserva"], "viajeId": armado.carga["viajeId"]}
    assert _filas(itinerary, "SELECT version FROM usuario_version") == [{"version": 2}]


def test_un_evento_repetido_no_produce_un_segundo_efecto(itinerary, observacion):
    evento = _extraida(observacion)
    itinerary.consumir(evento)

    assert itinerary.consumir(evento) == []
    assert len(_filas(itinerary, "SELECT * FROM bandeja_salida")) == 2  # la reserva y su viaje
    assert _filas(itinerary, "SELECT version FROM usuario_version") == [{"version": 2}]


def test_la_cancelacion_del_proveedor_se_publica_con_su_causa(itinerary, observacion):
    itinerary.consumir(_extraida(observacion))
    cancelacion = _observada({**observacion, "versionDeFuente": "2026-11-11T00:00:00Z",
                              "cancelada": True}, id_de_causa="disrupcion-7")

    eventos = itinerary.consumir(cancelacion)

    assert [e.tipo for e in eventos] == ["ReservaActualizada", "ReservaCancelada", "ViajeArmado"]
    assert {e.sobre["idDeCausa"] for e in eventos} == {"disrupcion-7"}  # también el del viaje
    assert eventos[1].carga["fuente"] == "proveedor"
    assert eventos[2].carga["estado"] == "Cancelado"  # todas sus reservas están canceladas


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
    assert "viajeId" in primera[1]  # la respuesta guardada incluye el viaje
    assert len(_filas(itinerary, "SELECT * FROM reserva")) == 1
    assert len(_filas(itinerary, "SELECT * FROM bandeja_salida")) == 2

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

    assert 0 < creada["versionUsuario"] < editada["versionUsuario"]
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


# --- viajes: la reserva y su viaje en dos transacciones (ADR-0010) -------------------------

COMUN = "openapi/comun.yaml#/components/schemas/"


def _alta_el(alta: dict, dia: int, codigo: str) -> dict:
    """El mismo vuelo, otro día y con otro localizador (otra reserva)."""
    alta = copy.deepcopy(alta)
    alta["identificadores"] = [{"emisor": "aerolinea:AR", "codigo": codigo}]
    for extremo, hora in (("inicio", 13), ("fin", 15)):
        alta["segmentos"][0][extremo]["instante"] = f"2026-12-{dia:02d}T{hora}:00:00Z"
    return alta


def test_el_alta_queda_en_un_viaje_y_en_el_panel(itinerary, alta, contratos):
    _, respuesta = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    viaje_id = respuesta["viajeId"]

    assert respuesta["reserva"]["viajeId"] == viaje_id
    viaje = itinerary.leer_viaje(USUARIO, viaje_id)
    contratos.validar(COMUN + "Viaje", viaje)
    assert [r["id"] for r in viaje["reservas"]] == [respuesta["reserva"]["id"]]
    panel = itinerary.leer_panel(USUARIO)
    contratos.validar(COMUN + "Panel", panel)
    assert [v["id"] for v in panel["viajesActivos"]] == [viaje_id]
    assert panel["versionUsuario"] == respuesta["versionUsuario"]


def test_el_alta_con_viaje_queda_fijada_en_ese_viaje(itinerary, alta):
    _, primera = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    lejana = _alta_el(alta, 20, "LEJOS1")  # sola iría a otro viaje

    _, segunda = itinerary.crear_reserva(USUARIO, uuid4(), {**lejana, "viajeId": primera["viajeId"]})

    assert segunda["viajeId"] == primera["viajeId"]
    assert _filas(itinerary, "SELECT fijada FROM viaje_reserva ORDER BY fijada") == [
        {"fijada": False}, {"fijada": True}]
    with pytest.raises(gestion_manual.SolicitudInvalida):
        itinerary.crear_reserva(USUARIO, uuid4(), {**_alta_el(alta, 25, "OTRO1"), "viajeId": str(uuid4())})


def test_mover_archivar_y_eliminar_viajes(itinerary, alta):
    _, una = itinerary.crear_reserva(USUARIO, uuid4(), alta)
    _, otra = itinerary.crear_reserva(USUARIO, uuid4(), _alta_el(alta, 20, "LEJOS1"))
    assert una["viajeId"] != otra["viajeId"]

    itinerary.mover_reserva(USUARIO, UUID(una["viajeId"]), UUID(otra["reserva"]["id"]))
    assert itinerary.leer_viaje(USUARIO, otra["viajeId"]) is None  # quedó vacío: eliminado
    assert len(itinerary.leer_viaje(USUARIO, una["viajeId"])["reservas"]) == 2

    itinerary.archivar_viaje(USUARIO, UUID(una["viajeId"]))
    assert itinerary.leer_panel(USUARIO)["viajesActivos"] == []
    archivados = itinerary.leer_viajes(USUARIO, estado="Archivado")["viajes"]
    assert [v["id"] for v in archivados] == [una["viajeId"]]
    with pytest.raises(gestion_manual.ConflictoDeComando):
        itinerary.archivar_viaje(USUARIO, UUID(una["viajeId"]))

    itinerary.eliminar_viaje(USUARIO, UUID(una["viajeId"]))
    assert itinerary.leer_viaje(USUARIO, una["viajeId"]) is None
    with pytest.raises(gestion_manual.NoEncontrada):
        itinerary.eliminar_viaje(USUARIO, UUID(una["viajeId"]))


def test_si_falla_la_transaccion_del_viaje_la_reserva_queda_y_se_recupera(itinerary, alta, monkeypatch):
    original = viajes.aplicar_reserva

    def falla(*args, **kwargs):
        raise RuntimeError("falla en viajes")

    monkeypatch.setattr(viajes, "aplicar_reserva", falla)
    with pytest.raises(RuntimeError):
        itinerary.crear_reserva(USUARIO, uuid4(), alta)

    # Ninguna transacción escribe en reserva y viaje a la vez: la reserva quedó, el viaje no.
    assert len(_filas(itinerary, "SELECT * FROM reserva")) == 1
    assert _filas(itinerary, "SELECT * FROM viaje") == []
    assert len(_filas(itinerary, "SELECT * FROM evento_interno")) == 1

    monkeypatch.setattr(viajes, "aplicar_reserva", original)
    itinerary.tareas_periodicas()

    assert len(_filas(itinerary, "SELECT * FROM viaje")) == 1
    assert _filas(itinerary, "SELECT * FROM evento_interno") == []


def test_el_trabajo_periodico_avanza_el_ciclo_de_vida(itinerary, alta):
    _, creada = itinerary.crear_reserva(USUARIO, uuid4(), alta)  # vuela el 1/12 de 13 a 15 h
    viaje_id = creada["viajeId"]

    def estado_el(momento):
        itinerary.reloj["ahora"] = momento
        itinerary.tareas_periodicas()
        return itinerary.leer_viajes(USUARIO)["viajes"][0]["estado"]

    assert estado_el(datetime(2026, 12, 1, 14, tzinfo=timezone.utc)) == "EnCurso"
    assert estado_el(datetime(2026, 12, 2, 15, tzinfo=timezone.utc)) == "Completado"
    assert itinerary.leer_panel(USUARIO)["viajesActivos"] == []  # sale de la vista principal
    assert estado_el(datetime(2026, 12, 5, 15, tzinfo=timezone.utc)) == "Archivado"
    tipos = [f["tipo"] for f in _filas(itinerary, "SELECT tipo FROM bandeja_salida ORDER BY creado_en")]
    assert tipos[-2:] == ["ViajeArmado", "ViajeArchivado"] and "ViajeCompletado" in tipos
    assert itinerary.leer_viaje(USUARIO, viaje_id)["estado"] == "Archivado"


def test_la_lista_de_viajes_se_pagina_con_un_cursor(itinerary, alta, contratos):
    for dia, codigo in ((1, "A1"), (10, "B2"), (20, "C3")):
        itinerary.crear_reserva(USUARIO, uuid4(), _alta_el(alta, dia, codigo))

    primera = itinerary.leer_viajes(USUARIO, limite=2)
    segunda = itinerary.leer_viajes(USUARIO, limite=2, cursor=primera["siguienteCursor"])

    for pagina in (primera, segunda):
        for resumen in pagina["viajes"]:
            contratos.validar(COMUN + "ViajeResumen", resumen)
    desdes = [v["desde"] for v in primera["viajes"] + segunda["viajes"]]
    assert desdes == sorted(desdes, reverse=True) and len(desdes) == 3
    assert segunda["siguienteCursor"] is None
    assert primera["viajes"][0]["proximoSegmento"]["inicio"]["instante"] == "2026-12-20T13:00:00Z"
    with pytest.raises(ValueError):
        itinerary.leer_viajes(USUARIO, cursor="no-es-un-cursor")


def test_recorrido_http_de_viajes_y_panel(itinerary, alta, contratos):
    itinerario = "openapi/itinerary.yaml#/paths/"
    cabeceras = {"X-Usuario-Id": str(USUARIO)}
    with TestClient(itinerary.app()) as cliente:
        creada = cliente.post("/reservas", json=alta,
                              headers={**cabeceras, "Idempotency-Key": str(uuid4())}).json()
        viaje = f"/viajes/{creada['viajeId']}"

        panel = cliente.get("/panel", headers={**cabeceras, "X-Min-Version": "1"})
        contratos.validar(COMUN + "Panel", panel.json())
        lista = cliente.get("/viajes", params={"limite": 5}, headers=cabeceras)
        contratos.validar(itinerario + "~1viajes/get/responses/200/content/application~1json/schema",
                          lista.json())
        contratos.validar(COMUN + "Viaje", cliente.get(viaje, headers=cabeceras).json())
        foto = cliente.get(f"{viaje}/instantanea", headers=cabeceras)
        assert foto.json()["tomadaEn"] and foto.json()["viaje"]["id"] == creada["viajeId"]

        mover = cliente.put(f"{viaje}/reservas/{creada['reserva']['id']}", headers=cabeceras)
        assert mover.status_code == 204
        assert cliente.post(f"{viaje}/archivo", headers=cabeceras).status_code == 204
        assert cliente.post(f"{viaje}/archivo", headers=cabeceras).status_code == 409
        assert cliente.delete(viaje, headers=cabeceras).status_code == 204
        assert cliente.get(viaje, headers=cabeceras).status_code == 404
        assert cliente.get("/viajes", params={"estado": "Inventado"}, headers=cabeceras).status_code == 400
        assert cliente.get("/viajes", params={"cursor": "x"}, headers=cabeceras).status_code == 400
