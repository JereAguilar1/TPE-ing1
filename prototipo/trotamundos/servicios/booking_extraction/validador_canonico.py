"""Salida contractual, detalles registrados e invariantes de ADR-0035."""
from zoneinfo import ZoneInfo

from trotamundos.comun.modelo import limites_del_extremo
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos


def _campos(esquema: dict, datos, raiz: dict, ruta: str) -> set[str]:
    while '$ref' in esquema:
        referencia = esquema['$ref']
        if not referencia.startswith('#/'):
            raise ValueError('Referencia no local en el núcleo canónico')
        esquema = raiz
        for parte in referencia[2:].split('/'):
            esquema = esquema[parte]
    if esquema.get('type') == 'object' and esquema.get('required'):
        return set().union(*(_campos(esquema['properties'][clave], datos[clave], raiz,
                                    f'{ruta}.{clave}' if ruta else clave)
                             for clave in esquema['required']))
    if esquema.get('type') == 'array':
        return set().union(*(_campos(esquema['items'], valor, raiz, f'{ruta}[{i}]')
                             for i, valor in enumerate(datos)))
    return {ruta}


def validar(salida: dict, contratos, registro: RegistroDeTipos) -> set[str]:
    contratos.validar('plugins/extractor.yaml#/operaciones/extrae/salida', salida)
    if not salida['observaciones']:
        return set()
    raiz = contratos.documento('openapi/comun.yaml')
    requeridos = set()
    for i, observacion in enumerate(salida['observaciones']):
        registro.validar_observacion(observacion)
        if observacion['fuente'] != 'correo' or not observacion['identificadores']:
            raise ValueError('La observación debe provenir de correo y tener identificadores')
        prefijo = f'observaciones[{i}]'
        campos = _campos(raiz['components']['schemas']['ObservacionCanonica'],
                         observacion, raiz, prefijo)
        for j, segmento in enumerate(observacion['segmentos']):
            inicio, fin = segmento['inicio'], segmento['fin']
            # Con los límites del modelo: un boleto abierto (`precision: dia`) cubre el día local
            # entero, así que empieza y termina el mismo día sin ser un tramo vacío (ADR-0011).
            desde, hasta = limites_del_extremo(inicio)[0], limites_del_extremo(fin)[1]
            if hasta <= desde:
                raise ValueError('El fin debe ser posterior al inicio')
            for extremo in (inicio, fin):
                ZoneInfo(extremo['zonaHoraria'])
                ZoneInfo(extremo['lugar']['zonaHoraria'])
                if not extremo['lugar']['nombre'].strip():
                    raise ValueError('Lugar no resoluble')
            detalle = registro.documento(segmento['tipo'], segmento['versionTipo'])['esquemaDeDetalle']
            ruta = f'{prefijo}.segmentos[{j}].detalle'
            campos.discard(ruta)
            campos.update(_campos(detalle, segmento['detalle'], detalle, ruta))
        requeridos.update(campos)
    return requeridos
