"""Persistencia compartida (ADR-0012, ADR-0014): outbox, bandeja de entrada e Idempotency-Key.

Usan el PostgreSQL de `docker-compose.yml`; sin él se saltean.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    conectar,
    crear_esquema,
    escribir_en_outbox,
    guardar_respuesta,
    huella_de_solicitud,
    purgar,
    registrar_en_bandeja_de_entrada,
    respuesta_guardada,
    transaccion,
)

USUARIO = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def bd(dsn, esquema):
    crear_esquema(dsn, esquema, ())
    return dsn, esquema


def _conflicto(reserva_id: str = "00000000-0000-4000-8000-0000000000aa") -> Evento:
    return Evento.nuevo(
        "ConflictoDeFuentesDetectado",
        {"reservaId": reserva_id, "conflicto": {
            "id": str(uuid4()), "campo": "segmentos[0].detalle.puerta", "estado": "Abierto",
            "valores": [{"fuente": "manual", "valor": "12"}, {"fuente": "proveedor", "valor": "15"}]}},
        productor="itinerary", usuario_id=USUARIO, region="AM")


def _filas(bd, tabla: str) -> list[dict]:
    with conectar(*bd) as conexion:
        return conexion.execute(f"SELECT * FROM {tabla}").fetchall()


# --- outbox (ADR-0012) ---------------------------------------------------------------------

def test_el_evento_se_escribe_con_su_topico_y_su_clave_de_particion(bd, contratos):
    evento = _conflicto()
    with transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, [evento], contratos)

    [fila] = _filas(bd, "bandeja_salida")
    assert str(fila["evento_id"]) == evento.id
    assert fila["topico"] == "dominio.conflicto-de-fuentes-detectado"
    assert fila["clave_de_particion"] == USUARIO and fila["publicado_en"] is None
    assert (fila["sobre"], fila["carga"]) == (evento.sobre, evento.carga)


def test_un_evento_que_no_cumple_el_contrato_no_entra_a_la_outbox(bd, contratos):
    invalido = Evento.nuevo("ConflictoDeFuentesDetectado", {"reservaId": "no-es-uuid"},
                            productor="itinerary", usuario_id=USUARIO)
    with pytest.raises(ErrorDeContrato), transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, [_conflicto(), invalido], contratos)

    assert _filas(bd, "bandeja_salida") == []


def test_si_el_cambio_falla_el_evento_tampoco_queda(bd, contratos):
    with pytest.raises(RuntimeError), transaccion(*bd) as conexion:
        escribir_en_outbox(conexion, [_conflicto()], contratos)
        raise RuntimeError("falla del cambio después de escribir el evento")

    assert _filas(bd, "bandeja_salida") == []


# --- bandeja de entrada (ADR-0014) ---------------------------------------------------------

def test_un_evento_repetido_se_reconoce_por_consumidor(bd):
    evento = _conflicto()
    with transaccion(*bd) as conexion:
        assert registrar_en_bandeja_de_entrada(conexion, "notification", evento) is True
        assert registrar_en_bandeja_de_entrada(conexion, "notification", evento) is False
        assert registrar_en_bandeja_de_entrada(conexion, "event-pipeline", evento) is True


def test_si_el_procesamiento_falla_el_evento_se_puede_volver_a_procesar(bd):
    evento = _conflicto()
    with pytest.raises(RuntimeError), transaccion(*bd) as conexion:
        registrar_en_bandeja_de_entrada(conexion, "itinerary", evento)
        raise RuntimeError("falla al procesar")

    with transaccion(*bd) as conexion:
        assert registrar_en_bandeja_de_entrada(conexion, "itinerary", evento) is True


# --- Idempotency-Key -----------------------------------------------------------------------

def test_la_respuesta_de_un_comando_se_guarda_por_usuario_y_clave(bd):
    clave = uuid4()
    respuesta = RespuestaGuardada("crearReserva", huella_de_solicitud({"a": 1}), 201, {"ok": True})
    with transaccion(*bd) as conexion:
        assert respuesta_guardada(conexion, USUARIO, clave) is None
        guardar_respuesta(conexion, USUARIO, clave, respuesta)

    with transaccion(*bd) as conexion:
        assert respuesta_guardada(conexion, USUARIO, clave) == respuesta
        assert respuesta_guardada(conexion, "00000000-0000-4000-8000-000000000002", clave) is None


def test_la_huella_no_depende_del_orden_de_las_claves():
    assert huella_de_solicitud({"a": 1, "b": [1, 2]}) == huella_de_solicitud({"b": [1, 2], "a": 1})
    assert huella_de_solicitud({"a": 1}) != huella_de_solicitud({"a": 2})


# --- retención y bloqueo -------------------------------------------------------------------

def test_purgar_borra_solo_lo_que_supera_la_retencion(bd):
    ahora = datetime.now(timezone.utc)
    with transaccion(*bd) as conexion:
        registrar_en_bandeja_de_entrada(conexion, "itinerary", _conflicto())
        registrar_en_bandeja_de_entrada(conexion, "itinerary", _conflicto())
        conexion.execute("UPDATE bandeja_entrada SET recibido_en = %s WHERE ctid IN "
                         "(SELECT ctid FROM bandeja_entrada LIMIT 1)", (ahora - timedelta(days=15),))
        assert purgar(conexion, ahora) == 1

    assert len(_filas(bd, "bandeja_entrada")) == 1


def test_el_bloqueo_por_usuario_dura_hasta_el_fin_de_la_transaccion(bd):
    with transaccion(*bd) as primera:
        bloquear_usuario(primera, USUARIO)
        with conectar(*bd) as segunda:
            segunda.execute("SET lock_timeout = '200ms'")
            otro = segunda.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS ok",
                                   ("00000000-0000-4000-8000-000000000002",)).fetchone()
            mismo = segunda.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS ok",
                                    (USUARIO,)).fetchone()
    assert otro["ok"] is True and mismo["ok"] is False


def test_el_esquema_debe_tener_un_nombre_valido(dsn):
    with pytest.raises(ValueError):
        conectar(dsn, "itinerary; DROP TABLE x")
