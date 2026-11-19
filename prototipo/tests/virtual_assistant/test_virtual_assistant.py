"""`virtual-assistant` contra PostgreSQL (RF-B1, RF-B2, `virtual-assistant.yaml`). Sin base, se
saltean.

`itinerary` y `support-liaison` son dobles en memoria (`datos.py`) que validan lo que reciben contra
sus contratos. Cada prueba nombra la confirmación de ADR que verifica.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.virtual_assistant.datos import (
    AHORA,
    MADRID,
    CONFLICTO,
    HOTEL,
    OTRO,
    SECRETO_JWT,
    TREN,
    USUARIO,
    VIAJE,
    VUELO,
    ItinerarioEnMemoria,
    SoporteEnMemoria,
    _extremo,
    _lugar,
    _reserva,
    sesion_http,
)
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.virtual_assistant.servicio import VirtualAssistant

RESPUESTA = "openapi/virtual-assistant.yaml#/components/schemas/Respuesta"
SESION = "openapi/virtual-assistant.yaml#/components/schemas/Sesion"


@pytest.fixture
def asistente(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    reloj = {"ahora": AHORA}
    itinerario, soporte = ItinerarioEnMemoria(), SoporteEnMemoria()
    servicio = VirtualAssistant(configuracion, esquema=esquema, contratos=contratos,
                                lector=itinerario, escritor=itinerario, abridor=soporte,
                                secreto_jwt=SECRETO_JWT, reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.bd, servicio.reloj, servicio.contratos = (dsn, esquema), reloj, contratos
    servicio.itinerario, servicio.soporte = itinerario, soporte
    servicio.cliente = TestClient(servicio.app())
    return servicio


def _filas(asistente, consulta: str, *parametros) -> list[dict]:
    with conectar(*asistente.bd) as conexion:
        return conexion.execute(consulta, parametros).fetchall()


def _abrir(asistente, cuerpo: dict | None = None, usuario=USUARIO, clave: str | None = None):
    return asistente.cliente.post(
        "/asistente/sesiones", content=json.dumps(cuerpo) if cuerpo is not None else None,
        headers={**sesion_http(usuario), "Idempotency-Key": clave or str(uuid4()),
                 **({"Content-Type": "application/json"} if cuerpo is not None else {})})


def _sesion(asistente) -> str:
    respuesta = _abrir(asistente)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def _enviar(asistente, sid: str, cuerpo: dict, usuario=USUARIO, clave: str | None = None):
    return asistente.cliente.post(
        f"/asistente/sesiones/{sid}/mensajes", content=json.dumps(cuerpo),
        headers={**sesion_http(usuario), "Idempotency-Key": clave or str(uuid4()),
                 "Content-Type": "application/json"})


def _decir(asistente, sid: str, texto: str) -> dict:
    respuesta = _enviar(asistente, sid, {"texto": texto})
    assert respuesta.status_code == 200, respuesta.text
    asistente.contratos.validar(RESPUESTA, respuesta.json())
    return respuesta.json()


def _confirmar(asistente, sid: str, accion_id: str, decision: str = "confirmar"):
    return _enviar(asistente, sid, {"confirmacion": {"accionId": accion_id, "decision": decision}})


def _disrupcion(severidad: str = "alta", reservas=(VUELO,)) -> Evento:
    """Lo que publicaría `provider-sync` (en el prototipo lo inyectan las pruebas y la demo)."""
    return Evento.nuevo("DisrupcionDetectada", {
        "disrupcionId": "disr-AR1402-cancelado", "proveedor": "Aerolíneas Argentinas",
        "severidad": severidad, "descripcion": "Vuelo AR1402 cancelado",
        "afectados": [{"usuarioId": str(USUARIO), "reservaIds": list(reservas)}]},
        productor="provider-sync", usuario_id=str(USUARIO), region="AM")


# --- sesiones (ADR-0040) -------------------------------------------------------------------------

def test_abrir_una_sesion_trae_el_saludo(asistente):
    respuesta = _abrir(asistente, {"viajeId": VIAJE})
    assert respuesta.status_code == 201
    sesion = respuesta.json()
    asistente.contratos.validar(SESION, sesion)
    assert sesion["viajeId"] == VIAJE
    assert [t["autor"] for t in sesion["turnos"]] == ["asistente"]
    assert sesion["turnos"][0]["intencion"] == "saludo"


def test_abrir_es_idempotente_y_sin_cuerpo_tambien_vale(asistente):
    clave = str(uuid4())
    primera, segunda = _abrir(asistente, clave=clave), _abrir(asistente, clave=clave)
    assert primera.json() == segunda.json()
    assert len(_filas(asistente, "SELECT 1 FROM sesion")) == 1
    assert _abrir(asistente, {"viajeId": VIAJE}, clave=clave).status_code == 400


def test_un_viaje_ajeno_responde_404(asistente):
    assert _abrir(asistente, {"viajeId": str(uuid4())}).status_code == 404
    sid = _sesion(asistente)
    assert _enviar(asistente, sid, {"texto": "hola", "viajeId": str(uuid4())}).status_code == 404


def test_una_sesion_de_otro_usuario_responde_404(asistente):
    """ADR-0040: una sesión de otro usuario responde `404`."""
    sid = _sesion(asistente)
    ajena = asistente.cliente.get(f"/asistente/sesiones/{sid}", headers=sesion_http(OTRO))
    assert ajena.status_code == 404
    assert _enviar(asistente, sid, {"texto": "hola"}, usuario=OTRO).status_code == 404
    propia = asistente.cliente.get(f"/asistente/sesiones/{sid}", headers=sesion_http())
    assert propia.status_code == 200
    # un id que ni siquiera es un UUID tampoco existe: 404, como declara el contrato
    invalida = asistente.cliente.get("/asistente/sesiones/no-es-un-id", headers=sesion_http())
    assert invalida.status_code == 404


def test_sin_sesion_oidc_responde_401_y_un_cuerpo_invalido_400(asistente):
    sid = _sesion(asistente)
    sin_token = asistente.cliente.post(f"/asistente/sesiones/{sid}/mensajes",
                                       json={"texto": "hola"},
                                       headers={"Idempotency-Key": str(uuid4())})
    assert sin_token.status_code == 401
    assert _enviar(asistente, sid, {"viajeId": VIAJE}).status_code == 400  # ni texto ni confirmación
    assert _enviar(asistente, sid, {"texto": ""}).status_code == 400


def test_la_sesion_guarda_los_turnos(asistente):
    sid = _sesion(asistente)
    _decir(asistente, sid, "¿A qué hora sale mi vuelo?")
    sesion = asistente.cliente.get(f"/asistente/sesiones/{sid}", headers=sesion_http()).json()
    asistente.contratos.validar(SESION, sesion)
    assert [(t["autor"], t.get("intencion")) for t in sesion["turnos"]] == [
        ("asistente", "saludo"), ("viajero", "proximoTramo"), ("asistente", "proximoTramo")]
    assert sesion["viajeId"] == VIAJE


def test_dos_mensajes_a_la_vez_no_se_pisan_el_estado(asistente):
    """Mientras se atiende un saludo, otro mensaje de la misma sesión propone una corrección: al
    terminar, el saludo no borra esa propuesta (cada turno escribe solo lo que cambió)."""
    sid = _sesion(asistente)
    original, otra = asistente._dialogo.atender, {}

    def con_otro_mensaje_en_el_medio(*argumentos, **nombrados):
        if not otra:  # el otro mensaje entra directo al servicio (no por HTTP, que está ocupado)
            otra["propuesta"] = None  # marca antes de llamar: el otro mensaje pasa por acá también
            otra["propuesta"] = asistente.enviar_mensaje(
                USUARIO, sesion_http()["Authorization"], UUID(sid), uuid4(),
                {"texto": "me pasaron el vuelo AR1402 al sábado a las 18:30"})["accionPropuesta"]
        return original(*argumentos, **nombrados)

    asistente._dialogo.atender = con_otro_mensaje_en_el_medio
    try:
        _decir(asistente, sid, "hola")
    finally:
        asistente._dialogo.atender = original
    sesion = asistente.cliente.get(f"/asistente/sesiones/{sid}", headers=sesion_http()).json()
    assert sesion["accionPendiente"]["id"] == otra["propuesta"]["id"]
    assert _confirmar(asistente, sid, otra["propuesta"]["id"]).status_code == 200


def test_el_mismo_mensaje_reintentado_no_duplica_turnos(asistente):
    sid, clave = _sesion(asistente), str(uuid4())
    primera = _enviar(asistente, sid, {"texto": "hola"}, clave=clave)
    segunda = _enviar(asistente, sid, {"texto": "hola"}, clave=clave)
    assert primera.json() == segunda.json()
    assert len(_filas(asistente, "SELECT 1 FROM turno")) == 3


def test_el_trabajo_periodico_borra_las_sesiones_de_mas_de_30_dias(asistente):
    """ADR-0040: retención de 30 días desde el último turno."""
    vieja = _sesion(asistente)
    asistente.reloj["ahora"] = AHORA + timedelta(days=20)
    reciente = _sesion(asistente)
    asistente.reloj["ahora"] = AHORA + timedelta(days=31)
    asistente.tareas_periodicas()
    quedan = {str(f["sesion_id"]) for f in _filas(asistente, "SELECT sesion_id FROM sesion")}
    assert quedan == {reciente}
    assert _filas(asistente, "SELECT 1 FROM turno WHERE sesion_id = %s", vieja) == []


# --- consultas (ADR-0038) ------------------------------------------------------------------------

def test_consulta_del_proximo_tramo_en_la_hora_del_lugar(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "¿A qué hora sale mi vuelo?")
    assert respuesta["intencion"] == "proximoTramo"
    assert respuesta["mensajes"] == [
        "Tu vuelo AR1402 sale el jueves 3/12 a las 10:00 (hora de Buenos Aires)."]
    assert "accionPropuesta" not in respuesta and respuesta["viajeId"] == VIAJE


def test_consulta_del_estado_del_viaje(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "¿Cómo viene mi viaje?")
    assert respuesta["mensajes"] == [
        "Tu viaje «Viaje a Madrid» (planificado) va del jueves 3/12 al martes 8/12 y tiene "
        "2 reservas.",
        "Además, tenés 1 reserva por confirmar.",
        "Hay 1 dato en conflicto entre lo que cargaste y lo que informó un proveedor."]


def test_cada_tipo_de_tramo_empieza_a_su_manera(asistente):
    sid = _sesion(asistente)
    assert _decir(asistente, sid, "¿cuándo es el hotel?")["mensajes"] == [
        "Tu hotel HTL778 tiene el ingreso el viernes 4/12 a las 14:00 (hora de Madrid)."]


def test_un_tipo_que_el_catalogo_no_conoce_se_atiende_por_su_codigo(asistente):
    """QA-15: con un tipo nuevo (solo su descriptor), el asistente lo encuentra por su código y lo
    nombra «reserva». Para nombrarlo y reconocerlo por su nombre se agrega a sus catálogos, que son
    recursos de presentación (ADR-0032)."""
    madrid = _lugar("Puerto de Barcelona", "ES", MADRID)
    barco = _reserva("00000000-0000-4000-8000-0000000000c4", "barco", "BAL220",
                     _extremo("2026-12-07T10:00:00Z", madrid), _extremo("2026-12-07T20:00:00Z", madrid))
    asistente.itinerario.datos["viajes"][0]["reservas"].append(barco)
    sid = _sesion(asistente)
    assert _decir(asistente, sid, "¿cuándo sale el BAL220?")["mensajes"] == [
        "Tu reserva BAL220 empieza el lunes 7/12 a las 11:00 (hora de Madrid)."]


def test_un_viaje_en_foco_que_ya_no_esta_deja_de_estar_en_foco(asistente):
    sid = _sesion(asistente)
    _decir(asistente, sid, "¿cómo viene mi viaje?")
    asistente.itinerario.datos["viajes"][0]["id"] = str(uuid4())  # el viaje se archivó y hay otro
    nuevo = asistente.itinerario.datos["viajes"][0]["id"]
    respuesta = _decir(asistente, sid, "¿cómo viene mi viaje?")
    assert respuesta["viajeId"] == nuevo and respuesta["mensajes"][0].startswith("Tu viaje")
    assert _decir(asistente, sid, "quiero hablar con mi agencia")["accionPropuesta"]["viajeId"] == nuevo


def test_si_itinerary_no_responde_lo_dice_y_no_adivina(asistente):
    sid = _sesion(asistente)
    asistente.itinerario.disponible = False
    respuesta = _decir(asistente, sid, "¿A qué hora sale mi vuelo?")
    assert respuesta["mensajes"] == ["Ahora no puedo leer tu itinerario. Probá de nuevo en un rato."]
    assert _decir(asistente, sid, "hola")["intencion"] == "saludo"


def test_preguntar_por_el_caso_no_abre_otro(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "¿Mi agencia ya recibió el caso?")
    assert "accionPropuesta" not in respuesta
    assert respuesta["mensajes"][0].startswith("Una vez que le paso un caso a tu agencia")


def test_preguntar_si_se_cancelo_es_una_consulta(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "¿Se canceló mi vuelo?")
    assert respuesta["intencion"] == "proximoTramo" and "accionPropuesta" not in respuesta


def test_saludo_ayuda_y_un_si_sin_nada_pendiente(asistente):
    sid = _sesion(asistente)
    assert _decir(asistente, sid, "hola")["intencion"] == "saludo"
    assert _decir(asistente, sid, "¿qué podés hacer?")["intencion"] == "ayuda"
    si = _decir(asistente, sid, "sí")
    assert si["intencion"] == "confirmacion" and "accionPropuesta" not in si


# --- corrección confirmada (ADR-0038) ------------------------------------------------------------

def _proponer_correccion(asistente, sid: str) -> dict:
    respuesta = _decir(asistente, sid, "me pasaron el vuelo AR1402 al sábado a las 18:30")
    assert respuesta["intencion"] == "corregirHorario"
    return respuesta["accionPropuesta"]


def test_sin_confirmacion_no_se_cambia_el_itinerario(asistente):
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    assert propuesta["tipo"] == "corregirReserva" and propuesta["reservaId"] == VUELO
    assert datetime.fromisoformat(propuesta["venceEn"]) == AHORA + timedelta(minutes=10)
    assert asistente.itinerario.escrituras == []
    _decir(asistente, sid, "¿cómo viene mi viaje?")  # otro turno no la ejecuta
    assert asistente.itinerario.escrituras == []


def test_la_propuesta_pendiente_no_guarda_una_copia_del_itinerario(asistente):
    """ADR-0040: la sesión guarda qué tramo, a qué hora y la versión vista, no los tramos."""
    sid = _sesion(asistente)
    _proponer_correccion(asistente, sid)
    (fila,) = _filas(asistente, "SELECT accion FROM sesion")
    guardado = json.dumps(fila["accion"])
    assert "segmentos" not in guardado and "edicion" not in guardado
    assert fila["accion"]["datos"]["version"] == 3


def test_corregir_con_confirmacion_corre_inicio_y_fin(asistente):
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    assert propuesta["resumen"] == ("Cambio tu vuelo AR1402 del jueves 3/12 10:00 al sábado 5/12 "
                                    "18:30 (hora de Buenos Aires). ¿Confirmás?")
    respuesta = _confirmar(asistente, sid, propuesta["id"])
    assert respuesta.status_code == 200, respuesta.text
    asistente.contratos.validar(RESPUESTA, respuesta.json())
    assert respuesta.json()["accionRealizada"] == {"tipo": "corregirReserva", "reservaId": VUELO}
    (_, reserva_id, cuerpo), = asistente.itinerario.escrituras
    assert reserva_id == VUELO and cuerpo["version"] == 3
    segmento = cuerpo["segmentos"][0]
    # sábado 5/12 18:30 en Buenos Aires = 21:30 UTC; el fin se corre lo mismo (+2 d 8 h 30 min)
    assert segmento["inicio"]["instante"] == "2026-12-05T21:30:00Z"
    assert segmento["fin"]["instante"] == "2026-12-06T13:30:00Z"
    sesion = asistente.cliente.get(f"/asistente/sesiones/{sid}", headers=sesion_http()).json()
    assert "accionPendiente" not in sesion
    assert sesion["turnos"][-2] == {**sesion["turnos"][-2], "autor": "viajero", "texto": "Confirmo."}


def test_una_confirmacion_vencida_o_de_otra_accion_responde_409(asistente):
    """ADR-0038: una confirmación vencida o de otra acción responde `409`."""
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    assert _confirmar(asistente, sid, str(uuid4())).status_code == 409
    asistente.reloj["ahora"] = AHORA + timedelta(minutes=11)
    vencida = _confirmar(asistente, sid, propuesta["id"])
    assert vencida.status_code == 409 and vencida.headers["content-type"].startswith(
        "application/problem+json")
    assert asistente.itinerario.escrituras == []


def test_confirmar_dos_veces_ejecuta_una_sola(asistente):
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    assert _confirmar(asistente, sid, propuesta["id"]).status_code == 200
    assert _confirmar(asistente, sid, propuesta["id"]).status_code == 409
    assert len(asistente.itinerario.escrituras) == 1


def test_rechazar_no_cambia_nada(asistente):
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    respuesta = _confirmar(asistente, sid, propuesta["id"], "rechazar")
    assert respuesta.json()["mensajes"] == ["Listo, no hago nada."]
    assert asistente.itinerario.escrituras == []
    assert _confirmar(asistente, sid, propuesta["id"]).status_code == 409


def test_un_409_de_itinerary_lleva_a_una_propuesta_nueva(asistente):
    """ADR-0038: un `409` de `itinerary` lleva a una propuesta nueva con la versión releída."""
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    asistente.itinerario.reserva(VUELO)["version"] = 4  # otro cambio entró mientras tanto
    respuesta = _confirmar(asistente, sid, propuesta["id"]).json()
    asistente.contratos.validar(RESPUESTA, respuesta)
    assert "accionRealizada" not in respuesta
    nueva = respuesta["accionPropuesta"]
    assert nueva["id"] != propuesta["id"] and nueva["tipo"] == "corregirReserva"
    assert respuesta["mensajes"][0].startswith("Tu reserva cambió mientras tanto")
    assert asistente.itinerario.escrituras == []
    assert _confirmar(asistente, sid, nueva["id"]).status_code == 200
    assert asistente.itinerario.escrituras[0][2]["version"] == 4


def test_si_itinerary_no_responde_la_propuesta_sigue_pendiente(asistente):
    sid = _sesion(asistente)
    propuesta = _proponer_correccion(asistente, sid)
    asistente.itinerario.disponible = False
    respuesta = _confirmar(asistente, sid, propuesta["id"]).json()
    assert "accionRealizada" not in respuesta
    asistente.itinerario.disponible = True
    assert _confirmar(asistente, sid, propuesta["id"]).json()["accionRealizada"]["tipo"] == \
        "corregirReserva"


def test_sin_fecha_ni_hora_repregunta(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "me cambiaron el horario del AR1402")
    assert "accionPropuesta" not in respuesta
    assert respuesta["mensajes"][0].startswith("¿A qué día y hora")


# --- problemas menores (ADR-0038) ----------------------------------------------------------------

@pytest.mark.parametrize("texto, tipo, decision", [
    ("confirmá la reserva IRYO6020", "confirmarReserva", "confirmar"),
    ("descartá la reserva IRYO6020", "descartarReserva", "descartar"),
])
def test_reserva_por_confirmar(asistente, texto, tipo, decision):
    sid = _sesion(asistente)
    mostrar = _decir(asistente, sid, "¿tengo reservas por confirmar?")
    assert "accionPropuesta" not in mostrar and "IRYO6020" in mostrar["mensajes"][0]
    propuesta = _decir(asistente, sid, texto)["accionPropuesta"]
    assert (propuesta["tipo"], propuesta["reservaId"]) == (tipo, TREN)
    assert asistente.itinerario.escrituras == []
    realizada = _confirmar(asistente, sid, propuesta["id"]).json()["accionRealizada"]
    assert realizada == {"tipo": tipo, "reservaId": TREN}
    assert asistente.itinerario.escrituras == [("confirmar", TREN, decision)]


@pytest.mark.parametrize("texto, eleccion", [
    ("mantené el mío en el conflicto", "mantenerFijado"),
    ("aceptá el del proveedor en el conflicto", "aceptarFuente"),
])
def test_resolver_un_conflicto_en_los_dos_sentidos(asistente, texto, eleccion):
    sid = _sesion(asistente)
    mostrar = _decir(asistente, sid, "tengo un conflicto")
    assert mostrar["mensajes"] == [
        "En tu hotel HTL778 cargaste viernes 4/12 14:00, pero el proveedor informa viernes 4/12 "
        "13:00. ¿Mantengo el tuyo o acepto el que informa el proveedor?"]
    propuesta = _decir(asistente, sid, texto)["accionPropuesta"]
    assert (propuesta["tipo"], propuesta["reservaId"]) == ("resolverConflicto", HOTEL)
    assert asistente.itinerario.escrituras == []
    assert _confirmar(asistente, sid, propuesta["id"]).status_code == 200
    (_, reserva_id, conflicto_id, cuerpo), = asistente.itinerario.escrituras
    assert (reserva_id, conflicto_id, cuerpo["eleccion"]) == (HOTEL, CONFLICTO, eleccion)
    assert cuerpo.get("fuente") == ("proveedor" if eleccion == "aceptarFuente" else None)


# --- derivación (ADR-0039) -----------------------------------------------------------------------

def test_cambio_ante_el_proveedor_no_ejecuta_nada_y_propone_derivar(asistente):
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "quiero cancelar el vuelo AR1402")
    propuesta = respuesta["accionPropuesta"]
    assert respuesta["intencion"] == "cambioAnteProveedor"
    assert propuesta["tipo"] == "derivarALaAgencia" and propuesta["viajeId"] == VIAJE
    assert asistente.itinerario.escrituras == [] and asistente.soporte.pedidos == []
    realizada = _confirmar(asistente, sid, propuesta["id"]).json()["accionRealizada"]
    assert realizada["tipo"] == "derivarALaAgencia" and realizada["agencia"] == "Agencia del Sur"
    (clave, cuerpo), = asistente.soporte.pedidos
    assert clave == propuesta["id"]
    assert (cuerpo["motivo"], cuerpo["viajeId"], cuerpo["reservaId"]) == (
        "cancelacion", VIAJE, VUELO)
    assert "idDeCausa" not in cuerpo and "AR1402" in cuerpo["descripcion"]


def test_el_viajero_pide_la_agencia(asistente):
    sid = _sesion(asistente)
    propuesta = _decir(asistente, sid, "quiero hablar con mi agencia")["accionPropuesta"]
    assert propuesta["tipo"] == "derivarALaAgencia"
    _confirmar(asistente, sid, propuesta["id"])
    (_, cuerpo), = asistente.soporte.pedidos
    assert cuerpo["motivo"] == "otro" and "reservaId" not in cuerpo


def test_dos_no_entendidos_seguidos_proponen_derivar(asistente):
    sid = _sesion(asistente)
    primero = _decir(asistente, sid, "asdf qwerty")
    assert primero["intencion"] == "noEntendido" and "accionPropuesta" not in primero
    segundo = _decir(asistente, sid, "zxcv")
    assert segundo["accionPropuesta"]["tipo"] == "derivarALaAgencia"
    _confirmar(asistente, sid, segundo["accionPropuesta"]["id"])
    (_, cuerpo), = asistente.soporte.pedidos
    assert cuerpo["motivo"] == "otro"
    assert "«asdf qwerty»" in cuerpo["descripcion"] and "«zxcv»" in cuerpo["descripcion"]
    no_entendidos = _filas(asistente, "SELECT no_entendidos FROM sesion")[0]["no_entendidos"]
    assert no_entendidos == 0  # después de derivar, el contador vuelve a cero


def test_un_no_entendido_entre_entendidos_no_deriva(asistente):
    sid = _sesion(asistente)
    _decir(asistente, sid, "asdf")
    _decir(asistente, sid, "hola")
    assert "accionPropuesta" not in _decir(asistente, sid, "qwerty")


def test_disrupcion_repetida_no_duplica_la_proyeccion(asistente):
    """ADR-0040: `DisrupcionDetectada` repetido no duplica la proyección."""
    evento = _disrupcion()
    asistente.consumir(evento)
    asistente.consumir(evento)
    asistente.consumir(_disrupcion())  # otro evento con la misma disrupción
    assert len(_filas(asistente, "SELECT 1 FROM disrupcion_conocida")) == 1


def test_disrupcion_alta_menciona_y_propone_derivar_con_su_causa(asistente):
    """ADR-0039, disparador de disrupción; ADR-0040, el asistente la menciona."""
    asistente.consumir(_disrupcion())
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "¿Qué pasa con mi vuelo?")
    assert "informó un problema con esta reserva: Vuelo AR1402 cancelado" in respuesta["mensajes"][1]
    propuesta = respuesta["accionPropuesta"]
    assert propuesta["tipo"] == "derivarALaAgencia" and asistente.soporte.pedidos == []
    _confirmar(asistente, sid, propuesta["id"])
    (_, cuerpo), = asistente.soporte.pedidos
    assert (cuerpo["motivo"], cuerpo["idDeCausa"], cuerpo["reservaId"]) == (
        "otro", "disr-AR1402-cancelado", VUELO)
    assert "Vuelo AR1402 cancelado" in cuerpo["descripcion"]


def test_una_disrupcion_ya_derivada_no_abre_otro_caso(asistente):
    asistente.consumir(_disrupcion())
    sid = _sesion(asistente)
    propuesta = _decir(asistente, sid, "¿Qué pasa con mi vuelo?")["accionPropuesta"]
    assert _confirmar(asistente, sid, propuesta["id"]).status_code == 200
    otra_vez = _decir(asistente, sid, "¿Qué pasa con mi vuelo?")
    assert "accionPropuesta" not in otra_vez
    assert otra_vez["mensajes"][-1].startswith("Ya le pasé este caso a tu agencia")
    assert len(asistente.soporte.casos) == 1
    # el viajero igual puede pedir la agencia por otro motivo
    assert _decir(asistente, sid, "quiero hablar con mi agencia")["accionPropuesta"]


def test_una_consulta_sin_disrupcion_alta_nunca_deriva(asistente):
    """ADR-0039: una consulta de estado nunca termina en derivación (sin disrupción alta)."""
    asistente.consumir(_disrupcion("media"))
    sid = _sesion(asistente)
    proximo = _decir(asistente, sid, "¿Qué pasa con mi vuelo?")
    assert "accionPropuesta" not in proximo and len(proximo["mensajes"]) == 2
    estado = _decir(asistente, sid, "¿Cómo viene mi viaje?")
    assert "accionPropuesta" not in estado


def test_confirmar_dos_veces_la_derivacion_abre_un_solo_caso(asistente):
    """ADR-0039: confirmar dos veces (o un reintento de red) abre un caso."""
    sid = _sesion(asistente)
    propuesta = _decir(asistente, sid, "quiero hablar con mi agencia")["accionPropuesta"]
    clave = str(uuid4())
    confirmacion = {"confirmacion": {"accionId": propuesta["id"], "decision": "confirmar"}}
    primera = _enviar(asistente, sid, confirmacion, clave=clave)
    reintento = _enviar(asistente, sid, confirmacion, clave=clave)
    assert primera.json() == reintento.json()
    assert _enviar(asistente, sid, confirmacion).status_code == 409
    assert len(asistente.soporte.casos) == 1


def test_sin_agencia_preferida_explica_como_configurarla(asistente):
    """ADR-0039: ante `422`, el asistente explica y no insiste."""
    asistente.soporte.con_agencia = False
    sid = _sesion(asistente)
    propuesta = _decir(asistente, sid, "quiero hablar con mi agencia")["accionPropuesta"]
    respuesta = _confirmar(asistente, sid, propuesta["id"]).json()
    assert "accionRealizada" not in respuesta and "accionPropuesta" not in respuesta
    assert respuesta["mensajes"][0].startswith("No tenés una agencia preferida")


def test_sin_viajes_no_propone_derivar_y_lo_explica(asistente):
    """ADR-0039: sin ningún viaje, no propone derivar."""
    asistente.itinerario.datos["viajes"] = []
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "quiero hablar con mi agencia")
    assert "accionPropuesta" not in respuesta
    assert respuesta["mensajes"] == ["Para pasarle un caso a tu agencia tiene que ser sobre un "
                                     "viaje, y no tenés ninguno activo."]


def test_con_varios_viajes_pregunta_cual(asistente):
    otro = {**asistente.itinerario.datos["viajes"][0], "id": str(uuid4()),
            "titulo": "Escapada a Mendoza", "reservas": []}
    asistente.itinerario.datos["viajes"].append(otro)
    sid = _sesion(asistente)
    respuesta = _decir(asistente, sid, "quiero hablar con mi agencia")
    assert "accionPropuesta" not in respuesta and "«Escapada a Mendoza»" in respuesta["mensajes"][0]
    elegido = _enviar(asistente, sid, {"texto": "quiero hablar con mi agencia",
                                       "viajeId": otro["id"]}).json()
    assert elegido["accionPropuesta"]["viajeId"] == otro["id"]
