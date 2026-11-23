"""Supresión de fase 1 coordinada (ADR-0030, ADR-0042), contra PostgreSQL; sin él, se saltean.

`identity-access` ordena a `itinerary`, `preferences`, `support-liaison` y `virtual-assistant`
borrar todos los datos del usuario con `DELETE /interno/usuarios/{usuarioId}`; cada uno los borra
con `comun.borrar_usuario`.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql

from tests.identity_access.test_api_identity_access import _armar, _iniciar_sesion
from tests.support_liaison.test_support_liaison import AGENCIA, LectorDePrueba, _preferencias
from tests.support_liaison.test_support_liaison import SECRETO_JWT
from tests.support_liaison.test_support_liaison import USUARIO as USUARIO_SOPORTE
from tests.virtual_assistant.datos import ItinerarioEnMemoria, SoporteEnMemoria, sesion_http
from tests.virtual_assistant.datos import USUARIO as USUARIO_ASISTENTE
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import borrar_usuario, conectar, transaccion
from trotamundos.servicios.identity_access import ordenes_de_borrado
from trotamundos.servicios.itinerary import api as api_itinerary
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.support_liaison.servicio import SupportLiaison
from trotamundos.servicios.virtual_assistant.servicio import VirtualAssistant

A, B = str(uuid4()), str(uuid4())


# --- el borrado genérico ------------------------------------------------------------------------

def test_borrar_usuario_borra_todas_sus_filas_respetando_las_claves_foraneas(dsn, esquema):
    with psycopg.connect(dsn, autocommit=True) as conexion:
        conexion.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(esquema)))
    with transaccion(dsn, esquema) as conexion:
        # «hija» referencia a «madre»: hay que borrar la hija primero, y el orden alfabético no sirve
        conexion.execute("CREATE TABLE madre (usuario_id uuid, id int PRIMARY KEY)")
        conexion.execute("CREATE TABLE hija (usuario_id uuid, madre int REFERENCES madre)")
        conexion.execute("CREATE TABLE sin_usuario (dato int)")
        for usuario, base in ((A, 1), (B, 10)):
            conexion.execute("INSERT INTO madre VALUES (%s, %s)", (usuario, base))
            conexion.execute("INSERT INTO hija VALUES (%s, %s)", (usuario, base))
        conexion.execute("INSERT INTO sin_usuario VALUES (1)")
    with transaccion(dsn, esquema) as conexion:
        assert borrar_usuario(conexion, A) == 2
        assert borrar_usuario(conexion, A) == 0  # idempotente
    with conectar(dsn, esquema) as conexion:
        quedan = {t: conexion.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                  for t in ("madre", "hija", "sin_usuario")}
    assert quedan == {"madre": 1, "hija": 1, "sin_usuario": 1}


# --- la orden en cada servicio ------------------------------------------------------------------

def test_itinerary_borra_los_datos_del_usuario_solo_en_escritura(dsn, esquema, contratos, observacion):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    itinerary = Itinerary(configuracion, esquema=esquema, contratos=contratos)
    itinerary.crear_esquema()
    alta = {"segmentos": [{k: v for k, v in observacion["segmentos"][0].items() if k != "versionTipo"}]}
    for usuario in (A, B):
        itinerary.crear_reserva(UUID(usuario), uuid4(), alta)

    escritura = TestClient(itinerary.app())  # modo completo, como itinerary-escritura
    assert escritura.delete(f"/interno/usuarios/{A}").status_code == 204
    assert escritura.delete(f"/interno/usuarios/{A}").status_code == 204  # idempotente
    assert itinerary.leer_panel(UUID(A))["viajesActivos"] == []
    assert len(itinerary.leer_panel(UUID(B))["viajesActivos"]) == 1
    with conectar(dsn, esquema) as conexion:
        assert conexion.execute("SELECT 1 FROM reserva WHERE usuario_id = %s", (A,)).fetchall() == []

    lectura = TestClient(api_itinerary.crear_app(itinerary, contratos, modo="lectura"))
    assert lectura.delete(f"/interno/usuarios/{B}").status_code in (404, 405)


def test_support_liaison_y_el_asistente_borran_los_datos_del_usuario(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    soporte = SupportLiaison(configuracion, esquema=esquema, contratos=contratos,
                             lector_de_viajes=LectorDePrueba(), secreto_jwt=SECRETO_JWT)
    soporte.crear_esquema()
    _preferencias(soporte, AGENCIA)
    cliente = TestClient(soporte.app())
    assert cliente.delete(f"/interno/usuarios/{USUARIO_SOPORTE}").status_code == 204
    with conectar(dsn, esquema) as conexion:
        assert conexion.execute("SELECT 1 FROM agencia_preferida").fetchall() == []

    otro_esquema = f"{esquema}_va"
    itinerario = ItinerarioEnMemoria()
    asistente = VirtualAssistant(configuracion, esquema=otro_esquema, contratos=contratos,
                                 lector=itinerario, escritor=itinerario, abridor=SoporteEnMemoria(),
                                 secreto_jwt="secreto-jwt-de-prueba-de-32-bytes!")
    try:
        with TestClient(asistente.app()) as cliente_va:
            sid = cliente_va.post("/asistente/sesiones", headers={
                **sesion_http(), "Idempotency-Key": str(uuid4())}).json()["id"]
            assert cliente_va.delete(f"/interno/usuarios/{USUARIO_ASISTENTE}").status_code == 204
            assert cliente_va.get(f"/asistente/sesiones/{sid}",
                                  headers=sesion_http()).status_code == 404
    finally:
        with psycopg.connect(dsn, autocommit=True) as conexion:
            conexion.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(otro_esquema)))


# --- identity-access ordena y reintenta ---------------------------------------------------------

class EjecutorDePrueba:
    servicios = ["itinerary", "preferences", "sharing", "support-liaison", "virtual-assistant"]

    def __init__(self):
        self.caidos: set[str] = set()
        self.recibidas: list[tuple[str, str]] = []

    def borrar(self, servicio, usuario_id):
        if servicio in self.caidos:
            raise ordenes_de_borrado.OrdenNoCumplida(f"{servicio}: no responde")
        self.recibidas.append((servicio, str(usuario_id)))


def test_identity_access_ordena_el_borrado_y_reintenta_lo_que_falla(dsn, esquema, contratos):
    cliente, servicio, _ = _armar(dsn, esquema, contratos)
    ejecutor = EjecutorDePrueba()
    ejecutor.caidos.add("support-liaison")
    servicio._borrado = ejecutor
    reloj = {"ahora": datetime.now(timezone.utc)}
    servicio._reloj = lambda: reloj["ahora"]
    token, usuario = _iniciar_sesion(cliente)

    respuesta = cliente.delete("/privacidad/cuenta", headers={
        "Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())})
    assert respuesta.status_code == 202
    assert sorted(s for s, _ in ejecutor.recibidas) == ["itinerary", "preferences", "sharing",
                                                         "virtual-assistant"]
    with conectar(dsn, esquema) as conexion:
        (pendiente,) = conexion.execute("SELECT * FROM orden_de_borrado").fetchall()
    assert (pendiente["servicio"], pendiente["usuario_id"], pendiente["intentos"]) == (
        "support-liaison", usuario, 1)

    assert servicio.cumplir_ordenes_de_borrado() == 0  # antes de la espera, no insiste
    ejecutor.caidos.clear()
    reloj["ahora"] += timedelta(seconds=6)
    assert servicio.cumplir_ordenes_de_borrado() == 1
    with conectar(dsn, esquema) as conexion:
        assert conexion.execute("SELECT 1 FROM orden_de_borrado").fetchall() == []
    assert ("support-liaison", str(usuario)) in ejecutor.recibidas
