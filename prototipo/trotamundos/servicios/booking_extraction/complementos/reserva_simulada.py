"""Plantilla sintética de la aerolínea de ejemplo; nunca interpreta correos reales.

La primera línea identifica v1; el resto son `Campo: valor`. `Localizador tentativo` vale 0,75,
`Localizador dudoso` vale 0,50 y el rótulo exacto vale 0,99. Una ausencia vale 0 y no se completa.
La tabla de aeropuertos y el patrón del emisor resuelven la estructura antes de puntuar.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from trotamundos.servicios.booking_extraction.interfaz_de_extractor import (
    FormatoNoSoportado, MensajeCorrupto,
)

CABECERA = 'Reserva aérea simulada v1'
REMITENTE = 'reservas@aerolinea.example'
_AEROPUERTOS = {
    'EZE': ('Ministro Pistarini', 'AR', 'America/Argentina/Buenos_Aires'),
    'AEP': ('Aeroparque', 'AR', 'America/Argentina/Buenos_Aires'),
    'MDZ': ('El Plumerillo', 'AR', 'America/Argentina/Mendoza'),
    'MAD': ('Adolfo Suárez Madrid-Barajas', 'ES', 'Europe/Madrid'),
}
_CAMPOS = ('Localizador', 'Aerolinea', 'Numero', 'Origen', 'Destino', 'Salida', 'Llegada', 'Emitido')


def _instante(valor):
    instante = datetime.fromisoformat(valor)
    if instante.tzinfo is None:
        raise ValueError('Fecha sin zona')
    return instante.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _extremo(codigo, instante):
    nombre, pais, zona = _AEROPUERTOS[codigo]
    return {'instante': _instante(instante), 'precision': 'instante', 'zonaHoraria': zona,
            'lugar': {'nombre': nombre, 'pais': pais, 'zonaHoraria': zona,
                      'codigo': codigo, 'esquemaDeCodigo': 'IATA'}}


def _puntajes(datos, prefijo, puntaje):
    if isinstance(datos, dict):
        return {clave: valor for campo, contenido in datos.items()
                for clave, valor in _puntajes(contenido, f'{prefijo}.{campo}', puntaje).items()}
    if isinstance(datos, list):
        return {clave: valor for i, contenido in enumerate(datos)
                for clave, valor in _puntajes(contenido, f'{prefijo}[{i}]', puntaje).items()}
    return {prefijo: puntaje}


class ExtractorSimulado:
    def reconoce(self, mensaje):
        lineas = mensaje.get('cuerpoTexto', '').splitlines()
        return {'aplica': mensaje['remitente'].lower() == REMITENTE and bool(lineas)
                          and lineas[0] == CABECERA}

    def extrae(self, mensaje, *, buzon_id, id_de_mensaje):
        if not self.reconoce(mensaje)['aplica']:
            raise FormatoNoSoportado()
        campos, confianza_localizador = {}, 0.99
        for linea in mensaje['cuerpoTexto'].splitlines()[1:]:
            if not linea.strip():
                continue
            clave, separador, valor = linea.partition(':')
            if not separador:
                raise MensajeCorrupto('Renglón sin separador')
            if clave in ('Localizador tentativo', 'Localizador dudoso'):
                confianza_localizador = 0.75 if clave.endswith('tentativo') else 0.5
                clave = 'Localizador'
            if clave not in _CAMPOS or clave in campos:
                raise MensajeCorrupto('Campo duplicado o desconocido')
            campos[clave] = valor.strip()
        if any(not campos.get(campo) for campo in _CAMPOS):
            return {'observaciones': [], 'confianza': {'global': 0, 'porCampo': {
                campo: 0.99 if campos.get(campo) else 0 for campo in _CAMPOS}}}
        try:
            if not re.fullmatch(r'[A-Z0-9]{6}', campos['Localizador']):
                raise ValueError('Localizador inválido')
            if not re.fullmatch(r'[A-Z0-9]{2}', campos['Aerolinea']):
                raise ValueError('Código del emisor inválido')
            if not re.fullmatch(r'[0-9]{1,4}', campos['Numero']):
                raise ValueError('Número inválido')
            observacion = {
                'fuente': 'correo',
                'idDeFuente': hashlib.sha256(json.dumps([buzon_id, id_de_mensaje]).encode()).hexdigest(),
                'versionDeFuente': _instante(campos['Emitido']),
                'identificadores': [{'emisor': 'aerolinea:' + campos['Aerolinea'],
                                     'codigo': campos['Localizador']}],
                'segmentos': [{'tipo': 'vuelo', 'versionTipo': 1,
                              'inicio': _extremo(campos['Origen'], campos['Salida']),
                              'fin': _extremo(campos['Destino'], campos['Llegada']),
                              'operador': campos['Aerolinea'],
                              'referencia': campos['Aerolinea'] + campos['Numero'],
                              'detalle': {'aerolinea': campos['Aerolinea'],
                                          'numeroDeVuelo': campos['Numero']}}],
            }
        except (ValueError, KeyError, OverflowError) as error:
            raise MensajeCorrupto('Campos estructurales inválidos') from error
        por_campo = _puntajes(observacion, 'observaciones[0]', 0.99)
        por_campo['observaciones[0].identificadores[0].codigo'] = confianza_localizador
        return {'observaciones': [observacion], 'confianza': {
            'global': min(por_campo.values()), 'porCampo': por_campo}}


def crear_extractor():
    return ExtractorSimulado()
