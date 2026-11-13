"""Agregado `Viaje`: agrupación (RF-07), asignación del usuario y ciclo de vida (RF-08).

Reglas de la iteración 2 §5.1 y parámetros de §5.11 (ADR-0010). Los eventos se validan contra el
contrato AsyncAPI.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ayudas import USUARIO
from trotamundos.comun.eventos import Causa
from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.itinerary.viajes import (
    ACTIVOS,
    EstadoViaje,
    ViajeNoModificable,
    misma_ciudad,
)
from trotamundos.servicios.itinerary.viajes import operaciones as op

ZONA = "America/Argentina/Buenos_Aires"
AEP = {"nombre": "Aeroparque", "codigo": "AEP", "esquemaDeCodigo": "IATA", "pais": "AR",
       "zonaHoraria": ZONA, "coordenadas": {"lat": -34.558, "lon": -58.416}}
MDZ = {"nombre": "El Plumerillo", "codigo": "MDZ", "esquemaDeCodigo": "IATA", "pais": "AR",
       "zonaHoraria": "America/Argentina/Mendoza", "coordenadas": {"lat": -32.832, "lon": -68.793}}
HOTEL_MENDOZA = {"nombre": "Hotel Aconcagua", "pais": "AR", "zonaHoraria": "America/Argentina/Mendoza",
                 "coordenadas": {"lat": -32.889, "lon": -68.845}}
HOTEL_BARILOCHE = {"nombre": "Hotel Llao Llao", "pais": "AR", "zonaHoraria": ZONA,
                   "coordenadas": {"lat": -41.052, "lon": -71.535}}


def dia(n: int, hora: int = 12) -> datetime:
    return datetime(2026, 12, n, hora, tzinfo=timezone.utc)


def _extremo(instante: datetime, lugar: dict, precision: str = "instante") -> dict:
    return {"instante": instante.isoformat().replace("+00:00", "Z"), "precision": precision,
            "zonaHoraria": lugar["zonaHoraria"], "lugar": lugar}


def segmento(tipo: str, inicio: datetime, fin: datetime, desde: dict, hasta: dict,
             estado: str = "confirmado", precision: str = "instante") -> dict:
    return {"tipo": tipo, "versionTipo": 1, "inicio": _extremo(inicio, desde, precision),
            "fin": _extremo(fin, hasta, precision), "estado": estado}


def reserva(n: int, *segmentos: dict, estado: str = "Confirmada") -> dict:
    return {"id": str(UUID(int=n)), "estado": estado, "segmentos": list(segmentos)}


def ida(n=1, dia_=1):
    return reserva(n, segmento("vuelo", dia(dia_, 10), dia(dia_, 12), AEP, MDZ))


def hotel(n=2, desde=1, hasta=4, lugar=HOTEL_MENDOZA):
    return reserva(n, segmento("hotel", dia(desde, 15), dia(hasta, 11), lugar, lugar))


class ViajesEnMemoria:
    def __init__(self):
        self.viajes = {}

    def obtener(self, usuario_id, viaje_id):
        viaje = self.viajes.get(viaje_id)
        return viaje if viaje is not None and viaje.usuario_id == usuario_id else None

    def de_reserva(self, usuario_id, reserva_id):
        return next((v for v in self.viajes.values()
                     if v.usuario_id == usuario_id and reserva_id in v.miembros), None)

    def activos(self, usuario_id):
        return [v for v in self.viajes.values() if v.usuario_id == usuario_id and v.estado in ACTIVOS]

    def guardar(self, viaje):
        self.viajes[viaje.id] = viaje


class Mundo:
    """Un repositorio en memoria y un reloj; cada operación es una sesión que se cierra."""

    def __init__(self, contratos):
        self.repositorio, self.ahora, self.contratos = ViajesEnMemoria(), dia(1, 0) - timedelta(days=30), contratos
        self._ids = iter(UUID(int=1000 + i) for i in range(1000))
        self.eventos = []

    def operar(self, operacion, *args):
        sesion = op.Sesion(self.repositorio, registro_por_omision(), USUARIO, self.ahora,
                           Causa(region="AM"), lambda: next(self._ids))
        resultado = operacion(sesion, *args)
        eventos = sesion.cerrar()
        for evento in eventos:
            evento.validar(self.contratos)
        self.eventos += eventos
        return resultado, eventos

    def aplicar(self, carga):
        return self.operar(op.aplicar_reserva, carga)[0]

    def viajes(self):
        return [v for v in self.repositorio.viajes.values() if v.estado != EstadoViaje.ELIMINADO]


@pytest.fixture
def mundo(contratos):
    return Mundo(contratos)


# --- agrupación (RF-07) --------------------------------------------------------------------

def test_la_primera_reserva_arma_un_viaje_planificado(mundo):
    viaje = mundo.aplicar(ida())

    assert viaje.estado == EstadoViaje.PLANIFICADO and viaje.version == 1
    assert viaje.derivados["titulo"] == "Viaje a El Plumerillo"
    [armado] = mundo.eventos
    assert armado.tipo == "ViajeArmado" and armado.carga["reservaIds"] == [str(UUID(int=1))]


def test_un_alojamiento_en_la_ciudad_de_llegada_se_une(mundo):
    viaje = mundo.aplicar(ida())
    assert mundo.aplicar(hotel()) is viaje  # a 7 km del aeropuerto, dentro del margen
    vuelta = reserva(3, segmento("vuelo", dia(4, 14), dia(4, 16), MDZ, AEP))
    assert mundo.aplicar(vuelta) is viaje  # empieza donde el viaje llegó
    assert viaje.derivados["hasta"] == "2026-12-04T16:00:00Z"


def test_lejos_en_el_tiempo_o_en_otra_ciudad_arma_otro_viaje(mundo):
    viaje = mundo.aplicar(ida())
    lejos = mundo.aplicar(hotel(2, desde=10, hasta=12))  # más de 72 h después
    otra_ciudad = mundo.aplicar(hotel(3, lugar=HOTEL_BARILOCHE))

    assert len({viaje.id, lejos.id, otra_ciudad.id}) == 3


@pytest.mark.parametrize("horas, mismo_viaje", [(71, True), (73, False)])
def test_el_margen_de_agrupacion_es_de_72_horas(mundo, horas, mismo_viaje):
    viaje = mundo.aplicar(ida())  # termina el 1 a las 12 h
    llegada = dia(1, 12) + timedelta(hours=horas)
    estadia = reserva(2, segmento("hotel", llegada, llegada + timedelta(days=1),
                                  HOTEL_MENDOZA, HOTEL_MENDOZA))

    assert (mundo.aplicar(estadia) is viaje) is mismo_viaje


@pytest.mark.parametrize("a, b, esperado", [
    ({"nombre": "Estación Retiro", "pais": "AR", "zonaHoraria": ZONA},
     {"nombre": "estación retiro ", "pais": "AR", "zonaHoraria": ZONA}, True),  # mismo nombre
    ({**MDZ, "coordenadas": None}, {"nombre": "Otro", "codigo": "MDZ", "esquemaDeCodigo": "IATA",
                                    "pais": "AR", "zonaHoraria": ZONA}, True),  # mismo código
    (MDZ, HOTEL_MENDOZA, True),                                                 # 7 km
    (MDZ, HOTEL_BARILOCHE, False),                                              # 900 km
    ({"nombre": "A", "pais": "AR", "zonaHoraria": ZONA},
     {"nombre": "B", "pais": "AR", "zonaHoraria": ZONA}, False),
])
def test_criterio_de_misma_ciudad(a, b, esperado):
    assert misma_ciudad(a, b) is esperado


def test_con_dos_candidatos_elige_el_mas_cercano_en_el_tiempo(mundo):
    primero = mundo.aplicar(ida(1, dia_=1))
    segundo = mundo.aplicar(ida(2, dia_=5))  # a más de 72 h del primero: otro viaje
    assert primero is not segundo

    assert mundo.aplicar(hotel(3, desde=5, hasta=6)) is segundo


def test_un_cambio_de_la_reserva_no_la_cambia_de_viaje(mundo):
    viaje = mundo.aplicar(ida())
    mundo.aplicar(hotel())
    corrido = hotel(2, desde=20, hasta=22)  # el proveedor movió el hotel dos semanas

    assert mundo.aplicar(corrido) is viaje
    assert viaje.derivados["hasta"] == "2026-12-22T11:00:00Z"  # el período sí se recalcula


def test_por_confirmar_no_entra_y_descartada_sale(mundo):
    assert mundo.aplicar(ida() | {"estado": "PorConfirmar"}) is None
    assert mundo.viajes() == []

    viaje = mundo.aplicar(ida())  # el usuario la confirmó
    assert mundo.aplicar(ida() | {"estado": "Descartada"}) is None
    assert viaje.estado == EstadoViaje.ELIMINADO  # sin reservas sale de toda vista
    assert mundo.eventos[-1].carga["estado"] == "Eliminado"


def test_las_absorbidas_por_una_unificacion_salen_de_su_viaje(mundo):
    viaje = mundo.aplicar(hotel(2, desde=20, hasta=22))
    mundo.operar(op.aplicar_reserva, ida(), [str(UUID(int=2))])
    assert viaje.estado == EstadoViaje.ELIMINADO


# --- asignación del usuario ----------------------------------------------------------------

def test_mover_fija_la_reserva_en_el_destino(mundo):
    viaje = mundo.aplicar(ida())
    otro = mundo.aplicar(hotel(2, desde=20, hasta=22))

    mundo.operar(op.mover, UUID(int=2), viaje.id)

    assert viaje.miembros[UUID(int=2)].fijada and otro.estado == EstadoViaje.ELIMINADO
    with pytest.raises(op.ReservaSinViaje):
        mundo.operar(op.mover, UUID(int=99), viaje.id)
    with pytest.raises(op.ViajeInexistente):
        mundo.operar(op.mover, UUID(int=2), otro.id)  # eliminado


def test_archivar_y_eliminar_a_pedido(mundo):
    viaje = mundo.aplicar(ida())
    _, eventos = mundo.operar(op.archivar, viaje.id)
    assert viaje.estado == EstadoViaje.ARCHIVADO
    assert [e.tipo for e in eventos] == ["ViajeArmado", "ViajeArchivado"]
    assert eventos[1].carga["motivo"] == "manual"
    with pytest.raises(ViajeNoModificable):
        mundo.operar(op.archivar, viaje.id)

    mundo.operar(op.eliminar, viaje.id)
    with pytest.raises(op.ViajeInexistente):
        mundo.operar(op.eliminar, viaje.id)


def test_sin_cambios_visibles_no_hay_viaje_armado_ni_version_nueva(mundo):
    viaje = mundo.aplicar(ida())
    _, eventos = mundo.operar(op.aplicar_reserva, ida())
    assert eventos == [] and viaje.version == 1


# --- ciclo de vida (RF-08) -----------------------------------------------------------------

def _avanzar(mundo, viaje, cuando):
    mundo.ahora = cuando
    return [e.tipo for e in mundo.operar(op.avanzar, viaje)[1]]


def test_planificado_en_curso_completado_archivado(mundo):
    viaje = mundo.aplicar(ida())  # del 1, 10 h, al 1, 12 h
    assert viaje.proxima_transicion(registro_por_omision()) == dia(1, 10)

    assert _avanzar(mundo, viaje, dia(1, 11)) == ["ViajeArmado"]
    assert viaje.estado == EstadoViaje.EN_CURSO
    assert _avanzar(mundo, viaje, dia(2, 11)) == []  # todavía no pasaron 24 h del fin
    assert _avanzar(mundo, viaje, dia(2, 12)) == ["ViajeArmado", "ViajeCompletado"]
    assert viaje.estado == EstadoViaje.COMPLETADO
    assert _avanzar(mundo, viaje, dia(5, 11)) == []  # gracia de 3 días
    assert _avanzar(mundo, viaje, dia(5, 12)) == ["ViajeArmado", "ViajeArchivado"]
    assert viaje.estado == EstadoViaje.ARCHIVADO
    assert mundo.eventos[-1].carga["motivo"] == "automatico"
    assert viaje.proxima_transicion(registro_por_omision()) is None


def test_un_boleto_abierto_vale_hasta_el_fin_del_dia_local(mundo):
    # Medianoche UTC del 5 = el 5 en Buenos Aires (convención del README del prototipo).
    tren = reserva(1, segmento("tren", dia(5, 0), dia(5, 0), AEP, MDZ, precision="dia"))
    viaje = mundo.aplicar(tren)

    # El día 5 local termina a las 03 h UTC del 6; se completa 24 h después.
    assert _avanzar(mundo, viaje, dia(7, 2))[-1:] != ["ViajeCompletado"]
    assert _avanzar(mundo, viaje, dia(7, 3))[-1] == "ViajeCompletado"


def test_con_todas_sus_reservas_canceladas_queda_cancelado(mundo):
    viaje = mundo.aplicar(ida())
    mundo.aplicar(ida() | {"estado": "Cancelada"})

    assert viaje.estado == EstadoViaje.CANCELADO
    assert _avanzar(mundo, viaje, dia(9)) == []  # no se completa solo: lo descarta el usuario
