"""QA-11: corpus sintético, bandas, invariantes y métricas sin datos personales."""
import copy
import json
from pathlib import Path
from uuid import uuid4
import pytest
from trotamundos.comun.catalogo_extractores import entradas
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.servicios.booking_extraction.evaluador_de_confianza import evaluar
from trotamundos.servicios.booking_extraction.observabilidad_de_calidad import Calidad, huella
from trotamundos.servicios.booking_extraction.registro_de_extractores import MotorExtraccion

CORPUS = json.loads((Path(__file__).parent / 'corpus/reserva_simulada.json').read_text())


def carga(mensaje=None):
    return {'buzonId': str(uuid4()), 'idDeMensaje': 'correo-1',
            'mensaje': copy.deepcopy(mensaje or CORPUS[0]['mensaje'])}


def test_corpus_cero_errores_en_alta_y_al_menos_95_por_ciento(contratos):
    motor = MotorExtraccion(contratos)
    aciertos = 0
    for caso in CORPUS:
        [(tipo, resultado)] = motor.procesar(carga(caso['mensaje']))
        contratos.validar(contratos.referencia_carga(tipo), resultado)
        assert tipo == 'ReservaExtraida' and resultado['banda'] == 'alta'
        obs, esperado = resultado['observacion'], caso['esperado']
        s = obs['segmentos'][0]
        obtenido = {'localizador': obs['identificadores'][0]['codigo'],
                    'emisor': obs['identificadores'][0]['emisor'],
                    'operador': s['operador'], 'numero': s['detalle']['numeroDeVuelo'],
                    'origen': s['inicio']['lugar']['codigo'], 'destino': s['fin']['lugar']['codigo'],
                    'salida': s['inicio']['instante'], 'llegada': s['fin']['instante'],
                    'emitido': obs['versionDeFuente']}
        assert obtenido == esperado
        aciertos += obtenido == esperado
    assert aciertos / len(CORPUS) >= .95


@pytest.mark.parametrize('rotulo,tipo,banda', [
    ('Localizador', 'ReservaExtraida', 'alta'),
    ('Localizador tentativo', 'ReservaExtraida', 'media'),
    ('Localizador dudoso', 'ExtraccionNoReconocida', None)])
def test_bandas_del_extractor(rotulo, tipo, banda):
    entrada = carga()
    entrada['mensaje']['cuerpoTexto'] = entrada['mensaje']['cuerpoTexto'].replace('Localizador:', rotulo + ':')
    [(nombre, salida)] = MotorExtraccion().procesar(entrada)
    assert nombre == tipo and salida.get('banda') == banda
    if banda is None:
        assert salida['motivo'] == 'bandaBaja' and 'borradorSugerido' in salida


@pytest.mark.parametrize('puntaje,banda', [(0, 'baja'), (.599, 'baja'), (.6, 'media'),
                                           (.899, 'media'), (.9, 'alta'), (1, 'alta')])
def test_limites_y_minimo_no_promedio(puntaje, banda):
    obtenida, confianza = evaluar({'global': 1, 'porCampo': {'a': 1, 'b': puntaje}},
                                  {'a', 'b'}, {'alto': .9, 'bajo': .6})
    assert obtenida == banda and confianza['global'] == puntaje


def test_falta_confianza_obligatoria():
    with pytest.raises(ValueError):
        evaluar({'global': 1, 'porCampo': {'a': 1}}, {'a', 'b'}, {'alto': .9, 'bajo': .6})


@pytest.mark.parametrize('antes,despues', [
    ('Llegada: 2026-12-01T15:00:00Z', 'Llegada: 2026-12-01T12:00:00Z'),
    ('Llegada: 2026-12-01T15:00:00Z', 'Llegada: 2026-12-01T13:00:00Z'),
    ('Salida: 2026-12-01T13:00:00Z', 'Salida: 2026-12-01T13:00:00'),
    ('Origen: AEP', 'Origen: XYZ'), ('Localizador: ABC000', 'Localizador: ?'),
    ('Numero: 1400', 'Numero: truncado'), ('Emitido: 2026-11-18T10:00:00Z', ''),
    ('Destino: MDZ', ''), ('Reserva aérea simulada v1', 'Plantilla inédita')])
def test_degradados_no_emiten_reserva(antes, despues):
    entrada = carga()
    entrada['mensaje']['cuerpoTexto'] = entrada['mensaje']['cuerpoTexto'].replace(antes, despues)
    [(tipo, salida)] = MotorExtraccion().procesar(entrada)
    assert tipo == 'ExtraccionNoReconocida'
    assert salida['motivo'] in {'validacionFallida', 'bandaBaja', 'formatoDesconocido'}
    assert 'cuerpoTexto' not in json.dumps(salida)


def test_remitente_ajeno_no_aplica():
    entrada = carga()
    entrada['mensaje']['remitente'] = 'otro@example.org'
    assert MotorExtraccion().procesar(entrada)[0][1]['motivo'] == 'formatoDesconocido'


def test_corpus_degradado_abre_disyuntor_y_fuerza_confirmacion():
    motor = MotorExtraccion()
    for caso in CORPUS:
        entrada = carga(caso['mensaje'])
        entrada['mensaje']['cuerpoTexto'] = entrada['mensaje']['cuerpoTexto'].replace('Origen: AEP', 'Origen: XYZ')
        assert motor.procesar(entrada)[0][0] == 'ExtraccionNoReconocida'
    assert motor.calidad.solo_confirmacion('extractor-reserva-simulada')
    [(tipo, salida)] = motor.procesar(carga())
    assert tipo == 'ReservaExtraida' and salida['banda'] == 'media'


def test_huella_ignora_texto_atributos_y_valores_de_cabeceras():
    a = {'remitente': 'ana@example.org', 'cuerpoTexto': 'Nombre Ana',
         'cuerpoHtml': '<p id="Ana"><b>Pasaporte privado</b></p>', 'cabeceras': {'Subject': 'Ana'}}
    b = {'remitente': 'luis@example.org', 'cuerpoTexto': 'Nombre Luis',
         'cuerpoHtml': '<p id="Luis"><b>Otro pasaporte</b></p>', 'cabeceras': {'Subject': 'Luis'}}
    assert huella(a) == huella(b)
    calidad = Calidad()
    calidad.desconocido(a)
    calidad.desconocido(b)
    assert list(calidad.huellas) == [('example.org', huella(a))]
    assert calidad.huellas[('example.org', huella(a))] == 2
    assert 'Ana' not in str(vars(calidad))


@pytest.mark.parametrize('campo,valor', [('apiContrato', '2.0'), ('version', 'sin-version')])
def test_rechaza_complemento_incompatible(campo, valor):
    config = entradas()
    config[0]['manifiesto'][campo] = valor
    with pytest.raises((ValueError, ErrorDeContrato)):
        MotorExtraccion(entradas=config)


def test_identidad_de_fuente_estable_y_distinta_entre_buzones():
    motor = MotorExtraccion()
    entrada = carga()
    primero = motor.procesar(entrada)[0][1]['observacion']
    assert motor.procesar(entrada)[0][1]['observacion'] == primero
    entrada['buzonId'] = str(uuid4())
    assert motor.procesar(entrada)[0][1]['observacion']['idDeFuente'] != primero['idDeFuente']
