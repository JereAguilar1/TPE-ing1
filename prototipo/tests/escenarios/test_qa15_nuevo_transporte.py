"""Escenario QA-15: incorporar un medio de transporte nuevo sin tocar los servicios de dominio.

Sigue la [guía de extensión de la iteración 4](../../../docs/02-proceso-add/iteracion-4/guias-de-extension.md)
con `tren`: lo único propio del tren es su descriptor (`contratos/tipos-de-segmento/tren.v1.yaml`).
Un viaje con vuelo, hotel y tren recorre `itinerary` por su API y el asistente lo lee por HTTP, sin
una línea que diga «tren» fuera de los complementos y los catálogos (la regla de
`tests/test_arquitectura.py`). Para mostrar que no es un caso preparado, un tipo que el repositorio no
conoce (`barco`) hace el mismo recorrido agregando solo su descriptor a una copia de los contratos, y
los datos históricos siguen consultables cuando el tipo cambia de versión.

Sin PostgreSQL se saltean.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from psycopg import sql

from tests.virtual_assistant.datos import SECRETO_JWT, SoporteEnMemoria, sesion_http
from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import Contratos
from trotamundos.comun.eventos import Evento
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.virtual_assistant.acciones import EscritorDeItinerarioHttp
from trotamundos.servicios.virtual_assistant.contexto import LectorDeItinerarioHttp
from trotamundos.servicios.virtual_assistant.servicio import VirtualAssistant

USUARIO = UUID("00000000-0000-4000-8000-0000000000a1")  # el de `tests/virtual_assistant/datos.py`
AHORA_ISO = "2026-11-20T12:00:00+00:00"
MADRID = "Europe/Madrid"


def _lugar(nombre: str, pais: str, zona: str, lat: float, lon: float) -> dict:
    return {"nombre": nombre, "pais": pais, "zonaHoraria": zona,
            "coordenadas": {"lat": lat, "lon": lon}}


AEROPARQUE = _lugar("Aeroparque", "AR", "America/Argentina/Buenos_Aires", -34.5592, -58.4156)
BARAJAS = _lugar("Barajas", "ES", MADRID, 40.4983, -3.5676)
HOTEL = _lugar("Hotel Prado", "ES", MADRID, 40.4153, -3.6844)
ATOCHA = _lugar("Atocha", "ES", MADRID, 40.4066, -3.6892)
SANTS = _lugar("Sants", "ES", MADRID, 41.3793, 2.1404)


def _extremo(instante: str, lugar: dict, precision: str = "instante") -> dict:
    return {"instante": instante, "precision": precision, "zonaHoraria": lugar["zonaHoraria"],
            "lugar": lugar}


def _alta(tipo: str, inicio: dict, fin: dict, operador: str, referencia: str,
          detalle: dict) -> dict:
    return {"segmentos": [{"tipo": tipo, "inicio": inicio, "fin": fin, "operador": operador,
                           "referencia": referencia, "detalle": detalle}]}


VUELO = _alta("vuelo", _extremo("2026-12-03T13:00:00Z", AEROPARQUE),
              _extremo("2026-12-04T05:00:00Z", BARAJAS), "Aerolíneas Argentinas", "AR1402",
              {"aerolinea": "AR", "numeroDeVuelo": "1402"})
ESTADIA = _alta("hotel", _extremo("2026-12-04T13:00:00Z", HOTEL),
                _extremo("2026-12-06T09:00:00Z", HOTEL), "Hotel Prado", "HTL778",
                {"habitaciones": 1, "huespedes": 2})
# 08:30 en Madrid; el detalle es el del descriptor `tren.v1` (numeroDeTren obligatorio, andén)
TREN = _alta("tren", _extremo("2026-12-06T07:30:00Z", ATOCHA),
             _extremo("2026-12-06T10:30:00Z", SANTS), "Renfe", "AVE03071",
             {"numeroDeTren": "03071", "coche": "5", "asiento": "12A", "anden": "7"})


def _itinerary(dsn: str, esquema: str, contratos: Contratos,
               registro: RegistroDeTipos | None = None) -> Itinerary:
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    servicio = Itinerary(configuracion, esquema=esquema, contratos=contratos, registro=registro,
                         reloj=lambda: datetime.fromisoformat(AHORA_ISO))
    servicio.crear_esquema()
    return servicio


def _dar_de_alta(cliente: TestClient, alta: dict) -> dict:
    respuesta = cliente.post("/reservas", content=json.dumps(alta),
                             headers={"X-Usuario-Id": str(USUARIO), "Idempotency-Key": str(uuid4()),
                                      "Content-Type": "application/json"})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


@pytest.fixture
def itinerario(dsn, esquema, contratos):
    with TestClient(_itinerary(dsn, esquema, contratos).app()) as cliente:
        yield cliente


def test_un_viaje_con_tren_se_arma_como_cualquier_otro(itinerario, contratos):
    """El tren se agrupa por su rol (`traslado`) y la continuidad de lugar, no por su tipo."""
    altas = [_dar_de_alta(itinerario, alta) for alta in (VUELO, ESTADIA, TREN)]
    assert len({a["viajeId"] for a in altas}) == 1

    viaje = itinerario.get(f"/viajes/{altas[0]['viajeId']}",
                           headers={"X-Usuario-Id": str(USUARIO)}).json()
    contratos.validar("openapi/comun.yaml#/components/schemas/Viaje", viaje)
    por_tipo = {r["segmentos"][0]["tipo"]: r for r in viaje["reservas"]}
    assert set(por_tipo) == {"vuelo", "hotel", "tren"}
    tren = por_tipo["tren"]["segmentos"][0]
    assert tren["versionTipo"] == 1 and tren["detalle"]["anden"] == "7"
    assert viaje["hasta"] == "2026-12-06T10:30:00Z"  # el viaje termina con el tren


def test_el_detalle_del_tren_se_valida_con_su_descriptor(itinerario):
    sin_numero = json.loads(json.dumps(TREN))
    sin_numero["segmentos"][0]["detalle"] = {"anden": "7"}
    respuesta = itinerario.post("/reservas", content=json.dumps(sin_numero),
                                headers={"X-Usuario-Id": str(USUARIO),
                                         "Idempotency-Key": str(uuid4()),
                                         "Content-Type": "application/json"})
    assert respuesta.status_code == 400
    assert "numeroDeTren" in respuesta.text


def test_los_clientes_reciben_la_presentacion_del_tren(itinerario):
    """El panel muestra el tren con su ícono y sus filas, dirigido por datos (guía, paso 2)."""
    tipos = {t["tipo"]: t for t in itinerario.get("/tipos-de-segmento").json()}
    assert tipos["tren"]["presentacion"] == {"icono": "tren", "titulo": "{operador} {referencia}",
                                             "filas": ["coche", "asiento", "clase"]}


def test_el_asistente_atiende_el_tren_leyendo_el_itinerario_real(itinerario, dsn, contratos):
    """El asistente usa sus adaptadores HTTP contra la API de `itinerary`: consulta el tren y lo
    corrige con confirmación, sin conocer el tipo (el nombre y el verbo salen del catálogo)."""
    for alta in (VUELO, ESTADIA, TREN):
        _dar_de_alta(itinerario, alta)
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    esquema_asistente = f"prueba_{uuid4().hex[:12]}"
    asistente = VirtualAssistant(
        configuracion, esquema=esquema_asistente, contratos=contratos,
        lector=LectorDeItinerarioHttp("http://itinerary", cliente=itinerario),
        escritor=EscritorDeItinerarioHttp("http://itinerary", cliente=itinerario),
        abridor=SoporteEnMemoria(), secreto_jwt=SECRETO_JWT,
        reloj=lambda: datetime.fromisoformat(AHORA_ISO))
    try:
        with TestClient(asistente.app()) as cliente:
            def decir(cuerpo: dict) -> dict:
                respuesta = cliente.post(
                    f"/asistente/sesiones/{sid}/mensajes", content=json.dumps(cuerpo),
                    headers={**sesion_http(), "Idempotency-Key": str(uuid4()),
                             "Content-Type": "application/json"})
                assert respuesta.status_code == 200, respuesta.text
                return respuesta.json()

            sid = cliente.post("/asistente/sesiones",
                               headers={**sesion_http(), "Idempotency-Key": str(uuid4())}).json()["id"]
            assert decir({"texto": "¿Cuándo sale mi tren?"})["mensajes"] == [
                "Tu tren AVE03071 sale el domingo 6/12 a las 08:30 (hora de Madrid)."]
            propuesta = decir({"texto": "me pasaron el tren AVE03071 a las 10:15"})["accionPropuesta"]
            assert propuesta["resumen"] == ("Cambio tu tren AVE03071 del domingo 6/12 08:30 al "
                                            "domingo 6/12 10:15 (hora de Madrid). ¿Confirmás?")
            hecha = decir({"confirmacion": {"accionId": propuesta["id"], "decision": "confirmar"}})
            assert hecha["accionRealizada"]["tipo"] == "corregirReserva"
    finally:
        _borrar_esquema(dsn, esquema_asistente)

    reserva = itinerario.get(f"/reservas/{hecha['accionRealizada']['reservaId']}",
                             headers={"X-Usuario-Id": str(USUARIO)}).json()
    tramo = reserva["segmentos"][0]
    assert (tramo["inicio"]["instante"], tramo["fin"]["instante"]) == (
        "2026-12-06T09:15:00Z", "2026-12-06T12:15:00Z")
    assert tramo["detalle"]["anden"] == "7" and "manual" in reserva["fuentes"]


def _borrar_esquema(dsn: str, esquema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conexion:
        conexion.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(esquema)))


# --- un tipo que el código no conoce -----------------------------------------------------------

def _descriptor_de_barco() -> dict:
    return {
        "tipo": "barco", "version": 1, "rolEnViaje": "traslado",
        "esquemaDeDetalle": {"type": "object", "required": ["camarote"], "additionalProperties": False,
                             "properties": {"camarote": {"type": "string"}}},
        "camposRelevantes": [{"campo": "inicio.instante", "severidad": "critica",
                              "umbralMinutos": 30}],
        "presentacion": {"icono": "barco", "titulo": "{operador} {referencia}", "filas": ["camarote"]},
        "dimension": {"atributos": ["operador"]},
    }


def _escribir(contratos: Path, nombre: str, descriptor: dict) -> None:
    (contratos / "tipos-de-segmento" / nombre).write_text(yaml.safe_dump(descriptor),
                                                          encoding="utf-8")


def test_un_tipo_que_el_codigo_no_conoce_recorre_itinerary_con_solo_su_descriptor(
        dsn, esquema, copia_de_contratos):
    _escribir(copia_de_contratos, "barco.v1.yaml", _descriptor_de_barco())
    contratos = Contratos(copia_de_contratos)
    registro = RegistroDeTipos.desde_contratos(contratos)
    barco = _alta("barco", _extremo("2026-12-06T07:30:00Z", ATOCHA),
                  _extremo("2026-12-06T18:00:00Z", SANTS), "Baleària", "BAL220",
                  {"camarote": "214"})
    with TestClient(_itinerary(dsn, esquema, contratos, registro).app()) as cliente:
        ids = {_dar_de_alta(cliente, alta)["viajeId"] for alta in (VUELO, ESTADIA, barco)}
        panel = cliente.get("/panel", headers={"X-Usuario-Id": str(USUARIO)}).json()
        assert "barco" in {t["tipo"] for t in cliente.get("/tipos-de-segmento").json()}
    assert len(ids) == 1
    tipos = {r["segmentos"][0]["tipo"] for r in panel["viajesActivos"][0]["reservas"]}
    assert tipos == {"vuelo", "hotel", "barco"}


def test_un_proveedor_que_informa_un_tipo_nuevo_entra_por_la_ingesta(dsn, esquema,
                                                                   copia_de_contratos):
    """El mismo tipo desconocido, llegado de un adaptador por `ReservaObservada` (guía, paso 3)."""
    _escribir(copia_de_contratos, "barco.v1.yaml", _descriptor_de_barco())
    contratos = Contratos(copia_de_contratos)
    itinerary = _itinerary(dsn, esquema, contratos, RegistroDeTipos.desde_contratos(contratos))
    tramo = {"tipo": "barco", "versionTipo": 1, "inicio": _extremo("2026-12-06T07:30:00Z", ATOCHA),
             "fin": _extremo("2026-12-06T18:00:00Z", SANTS), "operador": "Baleària",
             "referencia": "BAL220", "detalle": {"camarote": "214"}}
    evento = Evento.nuevo("ReservaObservada", {
        "adaptador": {"id": "naviera-simulada", "version": "1.0"},
        "observacion": {"fuente": "proveedor", "idDeFuente": "BAL/220",
                        "versionDeFuente": "2026-11-20T10:00:00Z",
                        "identificadores": [{"emisor": "naviera:BAL", "codigo": "BAL220"}],
                        "segmentos": [tramo]}},
        productor="provider-sync", usuario_id=str(USUARIO))
    publicados = itinerary.consumir(evento)
    assert "ReservaActualizada" in {e.tipo for e in publicados}
    viajes = itinerary.leer_panel(USUARIO)["viajesActivos"]
    assert [r["segmentos"][0]["tipo"] for v in viajes for r in v["reservas"]] == ["barco"]


def test_los_datos_historicos_siguen_consultables_con_una_version_nueva_del_tipo(
        dsn, esquema, copia_de_contratos):
    """QA-15: un tren dado de alta con `tren.v1` se sigue leyendo y editando cuando llega `tren.v2`,
    que exige un campo nuevo; cada tramo se valida con la versión con que se creó (ADR-0027)."""
    contratos = Contratos(copia_de_contratos)
    with TestClient(_itinerary(dsn, esquema, contratos).app()) as cliente:
        reserva_id = _dar_de_alta(cliente, TREN)["reserva"]["id"]

    tren_v1 = yaml.safe_load((copia_de_contratos / "tipos-de-segmento/tren.v1.yaml").read_text())
    tren_v2 = {**tren_v1, "version": 2, "esquemaDeDetalle": {
        **tren_v1["esquemaDeDetalle"], "required": ["numeroDeTren", "plataforma"],
        "properties": {**tren_v1["esquemaDeDetalle"]["properties"],
                       "plataforma": {"type": "string"}}}}
    _escribir(copia_de_contratos, "tren.v2.yaml", tren_v2)
    contratos = Contratos(copia_de_contratos)
    registro = RegistroDeTipos.desde_contratos(contratos)
    with TestClient(_itinerary(dsn, esquema, contratos, registro).app()) as cliente:
        cabeceras = {"X-Usuario-Id": str(USUARIO)}
        reserva = cliente.get(f"/reservas/{reserva_id}", headers=cabeceras).json()
        assert reserva["segmentos"][0]["versionTipo"] == 1
        tramo = reserva["segmentos"][0]
        edicion = {"version": reserva["version"], "segmentos": [{
            **{k: tramo[k] for k in ("id", "tipo", "inicio", "fin", "operador", "referencia")},
            "detalle": {**tramo["detalle"], "anden": "9"}}]}
        respuesta = cliente.put(f"/reservas/{reserva_id}", content=json.dumps(edicion),
                                headers={**cabeceras, "Content-Type": "application/json"})
        assert respuesta.status_code == 200, respuesta.text
        editado = respuesta.json()["reserva"]["segmentos"][0]
        assert editado["detalle"]["anden"] == "9"
        assert editado["versionTipo"] == 1  # editar no lo pasa a la versión nueva
        assert registro.obtener("tren").version == 2
