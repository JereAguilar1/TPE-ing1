"""El extractor de reservas de hotel (paso 9, «Para completar el 100 %»).

Otro remitente y otro tipo de segmento llegan por correo agregando un complemento y su entrada en
el catálogo: `booking-extraction` no cambia. Verifica el umbral de QA-11 sobre su propio corpus
sintético, las bandas de confianza, los mensajes corruptos y que el tramo cumple `hotel.v1`.
"""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from trotamundos.comun.catalogo_extractores import remitentes
from trotamundos.servicios.booking_extraction.registro_de_extractores import MotorExtraccion

CORPUS = json.loads((Path(__file__).parent / "corpus/reserva_hotel_simulada.json").read_text())
_DETALLE = ("habitaciones", "huespedes", "tipoDeHabitacion", "regimen", "politicaDeCancelacion")


def _carga(mensaje):
    return {"buzonId": str(uuid4()), "idDeMensaje": "hotel-1", "mensaje": copy.deepcopy(mensaje)}


def _obtenido(observacion):
    s = observacion["segmentos"][0]
    assert s["inicio"]["lugar"] == s["fin"]["lugar"]  # el hotel no se mueve
    datos = {"localizador": observacion["identificadores"][0]["codigo"],
             "emisor": observacion["identificadores"][0]["emisor"], "operador": s["operador"],
             "ciudad": s["inicio"]["lugar"]["codigo"], "ingreso": s["inicio"]["instante"],
             "salida": s["fin"]["instante"], "emitido": observacion["versionDeFuente"]}
    datos.update({k: v for k, v in s["detalle"].items() if k in _DETALLE})
    return datos


def test_corpus_cero_errores_en_alta_y_al_menos_95_por_ciento(contratos):
    motor = MotorExtraccion(contratos)
    aciertos = 0
    for caso in CORPUS:
        [(tipo, resultado)] = motor.procesar(_carga(caso["mensaje"]))
        contratos.validar(contratos.referencia_carga(tipo), resultado)
        assert tipo == "ReservaExtraida" and resultado["banda"] == "alta"
        assert resultado["extractor"]["id"] == "extractor-reserva-hotel-simulada"
        assert resultado["observacion"]["segmentos"][0]["tipo"] == "hotel"
        aciertos += _obtenido(resultado["observacion"]) == caso["esperado"]
    assert aciertos == len(CORPUS)  # cero errores en la banda alta (≥ 95 % de QA-11)


@pytest.mark.parametrize("rotulo, tipo, banda", [
    ("Localizador", "ReservaExtraida", "alta"),
    ("Localizador tentativo", "ReservaExtraida", "media"),
    ("Localizador dudoso", "ExtraccionNoReconocida", None)])
def test_bandas_de_confianza(contratos, rotulo, tipo, banda):
    mensaje = copy.deepcopy(CORPUS[0]["mensaje"])
    mensaje["cuerpoTexto"] = mensaje["cuerpoTexto"].replace("Localizador:", f"{rotulo}:")
    [(obtenido, resultado)] = MotorExtraccion(contratos).procesar(_carga(mensaje))
    assert obtenido == tipo and resultado.get("banda") == banda


@pytest.mark.parametrize("cambio", [
    ("Huespedes: 1", "Huespedes: 0"),            # el descriptor pide al menos uno
    ("Ciudad: BUE", "Ciudad: XXX"),              # ciudad desconocida
    ("Cadena: HX", "Cadena: hx"),                # código inválido
    ("Habitaciones: 1", "Habitaciones: una"),    # no es un número
])
def test_un_mensaje_corrupto_no_llega_a_itinerary(contratos, cambio):
    mensaje = copy.deepcopy(CORPUS[0]["mensaje"])
    assert cambio[0] in mensaje["cuerpoTexto"]
    mensaje["cuerpoTexto"] = mensaje["cuerpoTexto"].replace(*cambio)
    [(tipo, _)] = MotorExtraccion(contratos).procesar(_carga(mensaje))
    assert tipo == "ExtraccionNoReconocida"


def test_sin_un_campo_obligatorio_no_se_reconoce(contratos):
    mensaje = copy.deepcopy(CORPUS[0]["mensaje"])
    mensaje["cuerpoTexto"] = "\n".join(l for l in mensaje["cuerpoTexto"].splitlines()
                                       if not l.startswith("Salida:"))
    [(tipo, _)] = MotorExtraccion(contratos).procesar(_carga(mensaje))
    assert tipo == "ExtraccionNoReconocida"


def test_el_remitente_entra_solo_al_catalogo_de_remitentes():
    assert {"patron": "reservas@hotel.example",
            "extractorId": "extractor-reserva-hotel-simulada"} in remitentes()
