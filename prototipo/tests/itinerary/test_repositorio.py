"""Repositorio PostgreSQL de `Reserva` (ADR-0012, iteración 2 §5.8).

Usan el PostgreSQL de `docker-compose.yml`; sin él se saltean.
"""

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ayudas import CREADA_EN, USUARIO, instante
from test_propiedades_fusion import fijados, observaciones
from trotamundos.comun.modelo import Fuente, Identificador
from trotamundos.comun.persistencia import conectar, crear_esquema, transaccion
from trotamundos.servicios.itinerary.fusion.consolidacion import reconsolidar
from trotamundos.servicios.itinerary.fusion.identidad import ingerir, persistir
from trotamundos.servicios.itinerary.reservas import Fijado, Reserva
from trotamundos.servicios.itinerary.reservas.repositorio import DDL, RepositorioDeReservasPostgres

PUERTA = "segmentos[0].detalle.puerta"


@pytest.fixture
def bd(dsn, esquema):
    crear_esquema(dsn, esquema, DDL)
    return dsn, esquema


def _consolidada(entradas, fijos=(), usuario=USUARIO, reserva_id=None) -> Reserva:
    reserva = Reserva(reserva_id or uuid4(), usuario, CREADA_EN)
    for fijado in fijos:
        reserva.fijar(fijado)
    for observacion in entradas:
        reserva.registrar(observacion)
    reconsolidar(reserva)
    return reserva


def _guardar(bd, *reservas: Reserva) -> None:
    with transaccion(*bd) as conexion:
        repositorio = RepositorioDeReservasPostgres(conexion)
        for reserva in reservas:
            repositorio.guardar(reserva)


def _leer(bd, usuario, reserva_id) -> Reserva | None:
    with transaccion(*bd) as conexion:
        return RepositorioDeReservasPostgres(conexion).obtener(usuario, reserva_id)


def _todo(reserva: Reserva) -> tuple:
    return (reserva.a_dict(), reserva.vista, reserva.observaciones, reserva.fijados,
            reserva.identificadores, reserva.estado, reserva.version, reserva.creada_en)


# --- ida y vuelta --------------------------------------------------------------------------

@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(observaciones(), min_size=1, max_size=5), fijados, st.booleans())
def test_guardar_y_leer_devuelve_la_misma_reserva(bd, entradas, fijos, confirmar):
    usuario = uuid4()  # el esquema se comparte entre ejemplos
    reserva = _consolidada(entradas, fijos, usuario=usuario)
    reserva.agregar_identificadores({Identificador("aerolinea:AR", "ABC123")})
    if confirmar and reserva.estado.value == "PorConfirmar":
        reserva.confirmar()
    reconsolidar(reserva)
    _guardar(bd, reserva)

    leida = _leer(bd, usuario, reserva.id)

    assert _todo(leida) == _todo(reserva)
    resultado = reconsolidar(leida)  # releída, no hay nada que cambiar
    assert resultado.cambios == () and resultado.conflictos_nuevos == ()
    assert leida.version == reserva.version


def test_volver_a_guardar_actualiza_y_marca_los_conflictos_resueltos(bd, registrada):
    reserva = _consolidada([registrada(fuente="proveedor", version=instante(12),
                                       cambios={"detalle.puerta": "15"})],
                           [Fijado(PUERTA, "12", instante(11))])
    _guardar(bd, reserva)
    [conflicto] = reserva.vista.conflictos

    leida = _leer(bd, USUARIO, reserva.id)
    leida.resolver_conflicto(conflicto.id, aceptar=Fuente.PROVEEDOR, ahora=instante(13))
    reconsolidar(leida)
    _guardar(bd, leida)

    assert _todo(_leer(bd, USUARIO, reserva.id)) == _todo(leida)
    with conectar(*bd) as conexion:
        fila = conexion.execute("SELECT estado, resuelto_en FROM conflicto").fetchone()
    assert fila["estado"] == "Resuelto" and fila["resuelto_en"] is not None


def test_un_conflicto_que_cambia_o_se_reabre_se_relee_igual(bd, registrada):
    # El id del conflicto sale del campo y del fijado: si la fuente cambia el valor en disputa, o
    # deja de discrepar y vuelve a hacerlo, es el mismo conflicto con otros valores.
    reserva = _consolidada([registrada(fuente="proveedor", version=instante(12),
                                       cambios={"detalle.puerta": "15"})],
                           [Fijado(PUERTA, "12", instante(11))])
    _guardar(bd, reserva)
    for hora, puerta in ((13, "16"), (14, "12"), (15, "18")):  # cambia, se cierra, se reabre
        leida = _leer(bd, USUARIO, reserva.id)
        leida.registrar(registrada(fuente="proveedor", version=instante(hora),
                                   cambios={"detalle.puerta": puerta}))
        reconsolidar(leida)
        _guardar(bd, leida)

        assert _todo(_leer(bd, USUARIO, reserva.id)) == _todo(leida), puerta


# --- consultas de la fusión ----------------------------------------------------------------

def test_busca_por_identificador_y_por_observacion_solo_del_usuario(bd, registrada):
    reserva = _consolidada([registrada()])
    reserva.agregar_identificadores({Identificador("aerolinea:AR", "ABC123")})
    _guardar(bd, reserva)
    otro = UUID(int=99)

    with transaccion(*bd) as conexion:
        repositorio = RepositorioDeReservasPostgres(conexion)
        encontrada = repositorio.por_identificador(USUARIO, Identificador("aerolinea:AR", "ABC123"))
        assert encontrada is repositorio.por_observacion(USUARIO, (Fuente.CORREO, "mensaje-1"))
        assert encontrada.id == reserva.id
        assert repositorio.por_identificador(otro, Identificador("aerolinea:AR", "ABC123")) is None
        assert repositorio.por_observacion(otro, (Fuente.CORREO, "mensaje-1")) is None


def test_candidatas_por_fecha_de_inicio(bd, registrada):
    reserva = _consolidada([registrada()])  # sale el 2026-12-01
    _guardar(bd, reserva)

    with transaccion(*bd) as conexion:
        repositorio = RepositorioDeReservasPostgres(conexion)
        assert [r.id for r in repositorio.candidatas(USUARIO, date(2026, 12, 1), date(2026, 12, 1))] \
            == [reserva.id]
        assert repositorio.candidatas(USUARIO, date(2026, 12, 10), date(2026, 12, 12)) == []


def test_la_unificacion_mueve_los_identificadores_a_la_reserva_que_queda(bd, registrada):
    ids = iter([UUID(int=1), UUID(int=2)])
    entradas = [registrada(id_de_fuente="a", identificadores=(("aerolinea:AR", "A1"),)),
                      registrada(id_de_fuente="b", identificadores=(("agencia:x", "B2"),)),
                      registrada(fuente="proveedor", id_de_fuente="c",
                                 identificadores=(("aerolinea:AR", "A1"), ("agencia:x", "B2")))]
    for minuto, observacion in enumerate(entradas):
        with transaccion(*bd) as conexion:
            repositorio = RepositorioDeReservasPostgres(conexion)
            persistir(repositorio, ingerir(repositorio, USUARIO, observacion,
                                           instante(1, minuto), lambda: next(ids)))

    with conectar(*bd) as conexion:
        reservas = conexion.execute("SELECT reserva_id FROM reserva").fetchall()
        propietarias = conexion.execute("SELECT DISTINCT reserva_id FROM reserva_identificador").fetchall()
    assert [f["reserva_id"] for f in reservas] == [f["reserva_id"] for f in propietarias] == [UUID(int=1)]


# --- revisión del esquema (ADR-0012, «Confirmación») ---------------------------------------

def test_cada_identificador_es_de_una_sola_reserva_del_usuario(bd, registrada):
    una, otra = _consolidada([registrada(id_de_fuente="a")]), _consolidada([registrada(id_de_fuente="b")])
    for reserva in (una, otra):
        reserva.agregar_identificadores({Identificador("aerolinea:AR", "ABC123")})

    with pytest.raises(psycopg.errors.UniqueViolation):
        _guardar(bd, una, otra)


def test_las_tablas_llevan_usuario_id_en_la_clave_y_las_unicidades_existen(bd):
    with conectar(*bd) as conexion:
        claves = conexion.execute(
            """SELECT tc.table_name, tc.constraint_type, array_agg(k.column_name::text) AS columnas
               FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage k USING (constraint_schema, constraint_name)
               WHERE tc.table_schema = current_schema() AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
               GROUP BY tc.table_name, tc.constraint_type, tc.constraint_name""").fetchall()
    primarias = {c["table_name"]: set(c["columnas"]) for c in claves if c["constraint_type"] == "PRIMARY KEY"}
    unicas = [(c["table_name"], set(c["columnas"])) for c in claves]

    for tabla in ("reserva", "reserva_identificador", "observacion", "segmento", "conflicto"):
        assert "usuario_id" in primarias[tabla], tabla
    assert ("reserva_identificador", {"usuario_id", "emisor", "codigo"}) in unicas
    assert ("observacion", {"reserva_id", "fuente", "id_de_fuente"}) in unicas
    assert ("bandeja_entrada", {"consumidor", "evento_id"}) in unicas
