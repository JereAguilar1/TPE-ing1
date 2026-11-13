"""Repositorio PostgreSQL de `Viaje` (ADR-0012, iteración 2 §5.8). Sin PostgreSQL se saltean."""

import itertools
from uuid import UUID

import psycopg
import pytest

from ayudas import USUARIO
from test_viajes import dia, hotel, ida
from trotamundos.comun.eventos import Causa
from trotamundos.comun.persistencia import crear_esquema, transaccion
from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.itinerary.viajes import Viaje
from trotamundos.servicios.itinerary.viajes import operaciones as op
from trotamundos.servicios.itinerary.viajes.repositorio import DDL, RepositorioDeViajesPostgres


@pytest.fixture
def bd(dsn, esquema):
    crear_esquema(dsn, esquema, DDL)
    return dsn, esquema


_IDS = (UUID(int=500 + i) for i in itertools.count())


def _operar(bd, operacion, *args, ahora=dia(1, 0)):
    with transaccion(*bd) as conexion:
        repositorio = RepositorioDeViajesPostgres(conexion, registro_por_omision())
        sesion = op.Sesion(repositorio, registro_por_omision(), USUARIO, ahora, Causa(),
                           lambda: next(_IDS))
        resultado = operacion(sesion, *args)
        sesion.cerrar()
        return resultado


def _leer(bd, viaje_id) -> Viaje:
    with transaccion(*bd) as conexion:
        return RepositorioDeViajesPostgres(conexion, registro_por_omision()).obtener(USUARIO, viaje_id)


def test_guardar_y_leer_devuelve_el_mismo_viaje(bd):
    viaje = _operar(bd, op.aplicar_reserva, ida())
    _operar(bd, op.aplicar_reserva, hotel())
    guardado = _operar(bd, op.archivar, viaje.id)  # el viaje en memoria, tal como se guardó

    leido = _leer(bd, viaje.id)

    assert leido.estado.value == "Archivado" and leido.version == guardado.version == 3
    assert leido.datos_publicos() == guardado.datos_publicos()
    assert {r: (m.resumen, m.fijada) for r, m in leido.miembros.items()} == {
        r: (m.resumen, m.fijada) for r, m in guardado.miembros.items()}
    assert (leido.archivado_en, leido.motivo_de_archivo, leido.creado_en) == (
        guardado.archivado_en, guardado.motivo_de_archivo, guardado.creado_en)


def test_una_reserva_esta_en_un_solo_viaje(bd):
    # `guardar` saca a propósito la reserva del viaje anterior al moverla; la restricción es la
    # red de seguridad de la base para cualquier otra escritura (ADR-0012).
    _operar(bd, op.aplicar_reserva, ida())
    otro = _operar(bd, op.aplicar_reserva, hotel(2, desde=20, hasta=22))
    with pytest.raises(psycopg.errors.UniqueViolation), transaccion(*bd) as conexion:
        conexion.execute("""INSERT INTO viaje_reserva (usuario_id, viaje_id, reserva_id, fijada, resumen)
                            VALUES (%s, %s, %s, false, '{}')""", (str(USUARIO), str(otro.id), str(UUID(int=1))))


def test_mover_se_guarda_aunque_el_destino_se_guarde_primero(bd):
    uno = _operar(bd, op.aplicar_reserva, ida())
    otro = _operar(bd, op.aplicar_reserva, hotel(2, desde=20, hasta=22))

    with transaccion(*bd) as conexion:
        repositorio = RepositorioDeViajesPostgres(conexion, registro_por_omision())
        destino, origen = repositorio.obtener(USUARIO, uno.id), repositorio.obtener(USUARIO, otro.id)
        destino.incorporar(origen.quitar(UUID(int=2)).resumen, fijada=True)
        for viaje in (destino, origen):  # el destino primero
            viaje.refrescar(dia(1), registro_por_omision())
            repositorio.guardar(viaje)

    assert set(_leer(bd, uno.id).miembros) == {UUID(int=1), UUID(int=2)}
    assert _leer(bd, uno.id).miembros[UUID(int=2)].fijada
    assert _leer(bd, otro.id).miembros == {}
