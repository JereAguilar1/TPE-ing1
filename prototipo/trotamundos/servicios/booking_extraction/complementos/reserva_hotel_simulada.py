"""Plantilla sintética de la cadena hotelera de ejemplo; nunca interpreta correos reales (paso 9).

Un extractor más, como el del tren: agrega este complemento y su entrada en
`comun/catalogo_extractores.yaml`, sin tocar `booking-extraction` ni el dominio. Produce un tramo
`hotel` (descriptor `hotel.v1`): el inicio es el ingreso y el fin, la salida, en el mismo lugar.

La primera línea identifica v1; el resto son `Campo: valor`. `Localizador tentativo` vale 0,75,
`Localizador dudoso` vale 0,50 y el rótulo exacto vale 0,99. `Habitacion`, `Regimen` y
`Cancelacion` son opcionales. La tabla de ciudades da el lugar con sus coordenadas, para que
`itinerary` agrupe el hotel con el vuelo o el tren que llega a la misma ciudad.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from trotamundos.servicios.booking_extraction.interfaz_de_extractor import (
    FormatoNoSoportado, MensajeCorrupto,
)

CABECERA = 'Reserva de hotel simulada v1'
REMITENTE = 'reservas@hotel.example'
_CIUDADES = {
    'BUE': ('Buenos Aires', 'AR', 'America/Argentina/Buenos_Aires', -34.6037, -58.3816),
    'MDZ': ('Mendoza', 'AR', 'America/Argentina/Mendoza', -32.8895, -68.8458),
    'MDQ': ('Mar del Plata', 'AR', 'America/Argentina/Buenos_Aires', -38.0055, -57.5426),
    'MAD': ('Madrid', 'ES', 'Europe/Madrid', 40.4168, -3.7038),
    'BCN': ('Barcelona', 'ES', 'Europe/Madrid', 41.3874, 2.1686),
}
_REGIMENES = {'Solo alojamiento': 'soloAlojamiento', 'Desayuno': 'desayuno',
              'Media pension': 'mediaPension', 'Pension completa': 'pensionCompleta',
              'Todo incluido': 'todoIncluido'}
_OBLIGATORIOS = ('Localizador', 'Cadena', 'Hotel', 'Ciudad', 'Ingreso', 'Salida', 'Habitaciones',
                 'Huespedes', 'Emitido')
_OPCIONALES = ('Habitacion', 'Regimen', 'Cancelacion')


def _instante(valor):
    instante = datetime.fromisoformat(valor)
    if instante.tzinfo is None:
        raise ValueError('Fecha sin zona')
    return instante.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _extremo(ciudad, instante):
    nombre, pais, zona, lat, lon = _CIUDADES[ciudad]
    return {'instante': _instante(instante), 'precision': 'instante', 'zonaHoraria': zona,
            'lugar': {'nombre': nombre, 'pais': pais, 'zonaHoraria': zona, 'codigo': ciudad,
                      'esquemaDeCodigo': 'interno', 'coordenadas': {'lat': lat, 'lon': lon}}}


def _puntajes(datos, prefijo, puntaje):
    if isinstance(datos, dict):
        return {clave: valor for campo, contenido in datos.items()
                for clave, valor in _puntajes(contenido, f'{prefijo}.{campo}', puntaje).items()}
    if isinstance(datos, list):
        return {clave: valor for i, contenido in enumerate(datos)
                for clave, valor in _puntajes(contenido, f'{prefijo}[{i}]', puntaje).items()}
    return {prefijo: puntaje}


def _campos(cuerpo):
    campos, confianza_localizador = {}, 0.99
    for linea in cuerpo.splitlines()[1:]:
        if not linea.strip():
            continue
        clave, separador, valor = linea.partition(':')
        if not separador:
            raise MensajeCorrupto('Renglón sin separador')
        if clave in ('Localizador tentativo', 'Localizador dudoso'):
            confianza_localizador = 0.75 if clave.endswith('tentativo') else 0.5
            clave = 'Localizador'
        if clave not in _OBLIGATORIOS + _OPCIONALES or clave in campos:
            raise MensajeCorrupto('Campo duplicado o desconocido')
        campos[clave] = valor.strip()
    return campos, confianza_localizador


def _detalle(campos):
    detalle = {'habitaciones': int(campos['Habitaciones']), 'huespedes': int(campos['Huespedes'])}
    if detalle['habitaciones'] < 1 or detalle['huespedes'] < 1:
        raise ValueError('Habitaciones o huéspedes inválidos')
    if campos.get('Habitacion'):
        detalle['tipoDeHabitacion'] = campos['Habitacion']
    if campos.get('Regimen'):
        detalle['regimen'] = _REGIMENES[campos['Regimen']]
    if campos.get('Cancelacion'):
        detalle['politicaDeCancelacion'] = campos['Cancelacion']
    return detalle


class ExtractorReservaHotel:
    def reconoce(self, mensaje):
        lineas = mensaje.get('cuerpoTexto', '').splitlines()
        return {'aplica': mensaje['remitente'].lower() == REMITENTE and bool(lineas)
                          and lineas[0] == CABECERA}

    def extrae(self, mensaje, *, buzon_id, id_de_mensaje):
        if not self.reconoce(mensaje)['aplica']:
            raise FormatoNoSoportado()
        campos, confianza_localizador = _campos(mensaje['cuerpoTexto'])
        if any(not campos.get(campo) for campo in _OBLIGATORIOS):
            return {'observaciones': [], 'confianza': {'global': 0, 'porCampo': {
                campo: 0.99 if campos.get(campo) else 0 for campo in _OBLIGATORIOS}}}
        try:
            if not re.fullmatch(r'[A-Z0-9]{6}', campos['Localizador']):
                raise ValueError('Localizador inválido')
            if not re.fullmatch(r'[A-Z]{2,4}', campos['Cadena']):
                raise ValueError('Código de la cadena inválido')
            observacion = {
                'fuente': 'correo',
                'idDeFuente': hashlib.sha256(json.dumps([buzon_id, id_de_mensaje]).encode()).hexdigest(),
                'versionDeFuente': _instante(campos['Emitido']),
                'identificadores': [{'emisor': 'hotel:' + campos['Cadena'],
                                     'codigo': campos['Localizador']}],
                'segmentos': [{'tipo': 'hotel', 'versionTipo': 1,
                               'inicio': _extremo(campos['Ciudad'], campos['Ingreso']),
                               'fin': _extremo(campos['Ciudad'], campos['Salida']),
                               'operador': campos['Hotel'], 'referencia': campos['Localizador'],
                               'detalle': _detalle(campos)}],
            }
        except (ValueError, KeyError, OverflowError) as error:
            raise MensajeCorrupto('Campos estructurales inválidos') from error
        por_campo = _puntajes(observacion, 'observaciones[0]', 0.99)
        por_campo['observaciones[0].identificadores[0].codigo'] = confianza_localizador
        return {'observaciones': [observacion], 'confianza': {
            'global': min(por_campo.values()), 'porCampo': por_campo}}


def crear_extractor():
    return ExtractorReservaHotel()
