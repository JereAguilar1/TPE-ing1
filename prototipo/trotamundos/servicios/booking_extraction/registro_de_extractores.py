"""Carga por configuración y composición del camino de extracción (vista N2 §2)."""
import importlib
import re
from zoneinfo import ZoneInfoNotFoundError

from trotamundos.comun.catalogo_extractores import entradas as entradas_configuradas
from trotamundos.comun.contratos import ErrorDeContrato, contratos_por_omision
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.booking_extraction.evaluador_de_confianza import evaluar
from trotamundos.servicios.booking_extraction.interfaz_de_extractor import (
    FormatoNoSoportado, MensajeCorrupto,
)
from trotamundos.servicios.booking_extraction.observabilidad_de_calidad import Calidad
from trotamundos.servicios.booking_extraction.validador_canonico import validar


class MotorExtraccion:
    def __init__(self, contratos=None, *, entradas=None, calidad=None):
        self.contratos = contratos or contratos_por_omision()
        self.tipos = RegistroDeTipos.desde_contratos(self.contratos)
        self.calidad = calidad or Calidad()
        self.extractores = []
        ids = set()
        for entrada in entradas if entradas is not None else entradas_configuradas():
            manifiesto = entrada['manifiesto']
            self.contratos.validar('plugins/extractor.yaml#/manifiesto', manifiesto)
            if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', manifiesto['version']):
                raise ValueError('La versión del complemento no es SemVer')
            if manifiesto['umbrales']['bajo'] >= manifiesto['umbrales']['alto']:
                raise ValueError('El umbral bajo debe ser menor que el alto')
            if manifiesto['id'] in ids:
                raise ValueError('Extractor duplicado')
            for tipo in manifiesto['tiposDeSegmento']:
                self.tipos.obtener(tipo)
            ids.add(manifiesto['id'])
            modulo = entrada['modulo']
            if not modulo.startswith('trotamundos.servicios.booking_extraction.complementos.'):
                raise ValueError('El extractor debe vivir en complementos')
            self.extractores.append((manifiesto, importlib.import_module(modulo).crear_extractor()))

    def procesar(self, carga):
        self.contratos.validar(self.contratos.referencia_carga('MensajeDeViajeRecibido'), carga)
        mensaje = carga['mensaje']
        for manifiesto, extractor in self.extractores:
            reconoce = extractor.reconoce(mensaje)
            self.contratos.validar('plugins/extractor.yaml#/operaciones/reconoce/salida', reconoce)
            if not reconoce['aplica']:
                continue
            extractor_id = manifiesto['id']
            try:
                salida = extractor.extrae(mensaje, buzon_id=carga['buzonId'],
                                           id_de_mensaje=carga['idDeMensaje'])
                obligatorios = validar(salida, self.contratos, self.tipos)
                if not obligatorios:
                    self.calidad.registrar(extractor_id, 'baja')
                    return self._desconocida(carga, 'bandaBaja')
                banda, confianza = evaluar(salida['confianza'], obligatorios, manifiesto['umbrales'],
                                           self.calidad.solo_confirmacion(extractor_id))
            except FormatoNoSoportado:
                self.calidad.registrar(extractor_id, 'baja')
                return self._desconocida(carga, 'formatoDesconocido')
            except (MensajeCorrupto, ErrorDeContrato, ValueError, KeyError, ZoneInfoNotFoundError):
                self.calidad.registrar(extractor_id, 'baja')
                return self._desconocida(carga, 'validacionFallida')
            self.calidad.registrar(extractor_id, banda)
            if banda == 'baja':
                return self._desconocida(carga, 'bandaBaja', salida['observaciones'][0])
            return [('ReservaExtraida', {
                'buzonId': carga['buzonId'], 'idDeMensaje': carga['idDeMensaje'],
                'extractor': {'id': extractor_id, 'version': manifiesto['version']},
                'banda': banda, 'confianza': confianza, 'observacion': observacion,
            }) for observacion in salida['observaciones']]
        return self._desconocida(carga, 'formatoDesconocido')

    def _desconocida(self, carga, motivo, candidato=None):
        mensaje = carga['mensaje']
        datos = {'buzonId': carga['buzonId'], 'idDeMensaje': carga['idDeMensaje'],
                 'motivo': motivo, 'remitente': mensaje['remitente'],
                 'fechaCorreo': mensaje['recibidoEn'], 'asuntoTruncado': mensaje['asunto'][:80],
                 'huellaDeFormato': self.calidad.desconocido(mensaje)}
        if candidato is not None:
            datos['borradorSugerido'] = {'identificadores': candidato['identificadores'],
                                         'segmentos': candidato['segmentos']}
        self.contratos.validar(self.contratos.referencia_carga('ExtraccionNoReconocida'), datos)
        return [('ExtraccionNoReconocida', datos)]
