"""Plantilla sintética del ferrocarril de ejemplo; nunca interpreta correos reales (QA-15, paso 4).

Es el extractor de la guía de extensión de la iteración 4: incorporar trenes agrega este complemento
y su entrada en `comun/catalogo_extractores.yaml`, sin tocar `booking-extraction` ni el dominio.

La primera línea identifica v1; el resto son `Campo: valor`. `Localizador tentativo` vale 0,75,
`Localizador dudoso` vale 0,50 y el rótulo exacto vale 0,99. Un boleto con `Fecha` en lugar de
`Salida` y `Llegada` es un boleto abierto: vale todo ese día (`precision: dia`, ADR-0011).
`Coche`, `Asiento` y `Anden` son opcionales. La tabla de estaciones resuelve los lugares, con sus
coordenadas para que `itinerary` reconozca la misma ciudad que un hotel o un vuelo.
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone

from trotamundos.servicios.booking_extraction.interfaz_de_extractor import (
    FormatoNoSoportado, MensajeCorrupto,
)

CABECERA = 'Boleto de tren simulado v1'
REMITENTE = 'boletos@ferrocarril.example'
_ESTACIONES = {
    'RET': ('Retiro', 'AR', 'America/Argentina/Buenos_Aires', -34.5915, -58.3746),
    'CON': ('Constitución', 'AR', 'America/Argentina/Buenos_Aires', -34.6276, -58.3812),
    'MDQ': ('Mar del Plata', 'AR', 'America/Argentina/Buenos_Aires', -37.9926, -57.5848),
    'ROS': ('Rosario Norte', 'AR', 'America/Argentina/Cordoba', -32.9324, -60.6516),
    'ATO': ('Madrid Atocha', 'ES', 'Europe/Madrid', 40.4066, -3.6892),
    'BCN': ('Barcelona Sants', 'ES', 'Europe/Madrid', 41.3793, 2.1404),
}
# La ciudad de cada estación, para el título del viaje (comun.yaml 1.1.0).
_CIUDADES = {'RET': 'Buenos Aires', 'CON': 'Buenos Aires', 'MDQ': 'Mar del Plata',
             'ROS': 'Rosario', 'ATO': 'Madrid', 'BCN': 'Barcelona'}
_OBLIGATORIOS = ('Localizador', 'Operador', 'Tren', 'Origen', 'Destino', 'Emitido')
_OPCIONALES = ('Salida', 'Llegada', 'Fecha', 'Coche', 'Asiento', 'Anden')
_DETALLE = {'Coche': 'coche', 'Asiento': 'asiento', 'Anden': 'anden'}


def _instante(valor):
    instante = datetime.fromisoformat(valor)
    if instante.tzinfo is None:
        raise ValueError('Fecha sin zona')
    return instante.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _lugar(codigo):
    nombre, pais, zona, lat, lon = _ESTACIONES[codigo]
    return zona, {'nombre': nombre, 'ciudad': _CIUDADES[codigo], 'pais': pais,
                  'zonaHoraria': zona, 'codigo': codigo,
                  'esquemaDeCodigo': 'interno', 'coordenadas': {'lat': lat, 'lon': lon}}


def _extremo(codigo, instante):
    zona, lugar = _lugar(codigo)
    return {'instante': _instante(instante), 'precision': 'instante', 'zonaHoraria': zona,
            'lugar': lugar}


def _extremo_del_dia(codigo, dia):
    """Un boleto abierto vale «ese día»: medianoche UTC del día, como el resto del prototipo."""
    zona, lugar = _lugar(codigo)
    return {'instante': f'{date.fromisoformat(dia).isoformat()}T00:00:00Z', 'precision': 'dia',
            'zonaHoraria': zona, 'lugar': lugar}


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


class ExtractorBoletoTren:
    def reconoce(self, mensaje):
        lineas = mensaje.get('cuerpoTexto', '').splitlines()
        return {'aplica': mensaje['remitente'].lower() == REMITENTE and bool(lineas)
                          and lineas[0] == CABECERA}

    def extrae(self, mensaje, *, buzon_id, id_de_mensaje):
        if not self.reconoce(mensaje)['aplica']:
            raise FormatoNoSoportado()
        campos, confianza_localizador = _campos(mensaje['cuerpoTexto'])
        abierto = 'Fecha' in campos
        horario = ('Fecha',) if abierto else ('Salida', 'Llegada')
        if any(not campos.get(campo) for campo in _OBLIGATORIOS + horario):
            return {'observaciones': [], 'confianza': {'global': 0, 'porCampo': {
                campo: 0.99 if campos.get(campo) else 0 for campo in _OBLIGATORIOS + horario}}}
        try:
            if not re.fullmatch(r'[A-Z0-9]{6}', campos['Localizador']):
                raise ValueError('Localizador inválido')
            if not re.fullmatch(r'[A-Z]{2,4}', campos['Operador']):
                raise ValueError('Código del operador inválido')
            if not re.fullmatch(r'[A-Z0-9-]{1,8}', campos['Tren']):
                raise ValueError('Número de tren inválido')
            if abierto:
                inicio = _extremo_del_dia(campos['Origen'], campos['Fecha'])
                fin = _extremo_del_dia(campos['Destino'], campos['Fecha'])
            else:
                inicio = _extremo(campos['Origen'], campos['Salida'])
                fin = _extremo(campos['Destino'], campos['Llegada'])
            detalle = {'numeroDeTren': campos['Tren'],
                       **{nombre: campos[clave] for clave, nombre in _DETALLE.items()
                          if campos.get(clave)}}
            observacion = {
                'fuente': 'correo',
                'idDeFuente': hashlib.sha256(json.dumps([buzon_id, id_de_mensaje]).encode()).hexdigest(),
                'versionDeFuente': _instante(campos['Emitido']),
                'identificadores': [{'emisor': 'ferrocarril:' + campos['Operador'],
                                     'codigo': campos['Localizador']}],
                'segmentos': [{'tipo': 'tren', 'versionTipo': 1, 'inicio': inicio, 'fin': fin,
                               'operador': campos['Operador'],
                               'referencia': campos['Operador'] + campos['Tren'],
                               'detalle': detalle}],
            }
        except (ValueError, KeyError, OverflowError) as error:
            raise MensajeCorrupto('Campos estructurales inválidos') from error
        por_campo = _puntajes(observacion, 'observaciones[0]', 0.99)
        por_campo['observaciones[0].identificadores[0].codigo'] = confianza_localizador
        return {'observaciones': [observacion], 'confianza': {
            'global': min(por_campo.values()), 'porCampo': por_campo}}


def crear_extractor():
    return ExtractorBoletoTren()
