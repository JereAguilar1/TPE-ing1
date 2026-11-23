"""El extractor de boletos de tren (QA-15, guía de extensión de la iteración 4, paso 4).

Un medio de transporte nuevo llega por correo agregando un complemento y su entrada en el catálogo
de extractores: `booking-extraction` no cambia. Verifica el mismo umbral de QA-11 que el extractor
de vuelos sobre su propio corpus sintético, las bandas de confianza y los boletos abiertos.
"""
import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from trotamundos.comun.catalogo_extractores import entradas, remitentes
from trotamundos.servicios.booking_extraction.registro_de_extractores import MotorExtraccion

CORPUS = json.loads((Path(__file__).parent / "corpus/boleto_tren_simulado.json").read_text())


def _carga(mensaje):
    return {"buzonId": str(uuid4()), "idDeMensaje": "boleto-1", "mensaje": copy.deepcopy(mensaje)}


def _obtenido(observacion):
    s = observacion["segmentos"][0]
    datos = {"localizador": observacion["identificadores"][0]["codigo"],
             "emisor": observacion["identificadores"][0]["emisor"], "operador": s["operador"],
             "tren": s["detalle"]["numeroDeTren"], "origen": s["inicio"]["lugar"]["codigo"],
             "destino": s["fin"]["lugar"]["codigo"], "salida": s["inicio"]["instante"],
             "llegada": s["fin"]["instante"], "precision": s["inicio"]["precision"],
             "emitido": observacion["versionDeFuente"]}
    datos.update({k: v for k, v in s["detalle"].items() if k in ("coche", "asiento", "anden")})
    return datos


def test_corpus_cero_errores_en_alta_y_al_menos_95_por_ciento(contratos):
    motor = MotorExtraccion(contratos)
    aciertos = 0
    for caso in CORPUS:
        [(tipo, resultado)] = motor.procesar(_carga(caso["mensaje"]))
        contratos.validar(contratos.referencia_carga(tipo), resultado)
        assert tipo == "ReservaExtraida" and resultado["banda"] == "alta"
        assert resultado["extractor"]["id"] == "extractor-boleto-tren-simulado"
        assert resultado["observacion"]["segmentos"][0]["tipo"] == "tren"
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


def test_un_boleto_abierto_vale_todo_el_dia(contratos):
    abierto = next(c for c in CORPUS if c["esperado"]["precision"] == "dia")
    [(_, resultado)] = MotorExtraccion(contratos).procesar(_carga(abierto["mensaje"]))
    segmento = resultado["observacion"]["segmentos"][0]
    assert segmento["inicio"]["precision"] == segmento["fin"]["precision"] == "dia"


def test_cada_extractor_atiende_solo_su_plantilla(contratos):
    """El de vuelos no lee boletos de tren y el de tren no lee confirmaciones de vuelo."""
    motor = MotorExtraccion(contratos)
    vuelo = json.loads((Path(__file__).parent / "corpus/reserva_simulada.json").read_text())[0]
    [(_, resultado)] = motor.procesar(_carga(vuelo["mensaje"]))
    assert resultado["extractor"]["id"] == "extractor-reserva-simulada"
    ajeno = copy.deepcopy(CORPUS[0]["mensaje"]) | {"remitente": "otro@ferrocarril.example"}
    [(tipo, _)] = motor.procesar(_carga(ajeno))
    assert tipo == "ExtraccionNoReconocida"


def test_el_remitente_entra_solo_al_catalogo_de_remitentes():
    """RF-04: la lista de remitentes reconocidos que ve `mail-ingest` sale del catálogo."""
    assert {"patron": "boletos@ferrocarril.example",
            "extractorId": "extractor-boleto-tren-simulado"} in remitentes()
    assert [e["manifiesto"]["tiposDeSegmento"] for e in entradas()] == [["vuelo"], ["tren"], ["hotel"]]
