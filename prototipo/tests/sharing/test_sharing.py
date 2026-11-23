"""`sharing` (RF-11, RF-13, QA-12, ADR-0028) contra PostgreSQL; sin él, se saltean.

El circuito ABAC es el real y en el mismo proceso: `sharing` pide el vale a `identity-access`
(`POST /autorizaciones/evaluar`), que le pregunta los atributos de la compartición a `sharing`
(`GET /interno/comparticiones/{cid}`).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from tests.bff_web.test_bff_web import DobleDownstream
from trotamundos.comun.config import Configuracion
from trotamundos.servicios.identity_access.autenticacion_oidc import EnviadorOtpEnMemoria
from trotamundos.servicios.identity_access.consultor_sharing import ConsultorDeSharingHttp
from trotamundos.servicios.identity_access.servicio import IdentityAccess
from trotamundos.servicios.sharing import puertos
from trotamundos.servicios.sharing.servicio import Sharing

SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
SECRETO_VALE = "secreto-vale-de-prueba-de-32-byte"
DUENO = UUID("00000000-0000-4000-8000-0000000000b1")  # el usuario del doble de bff-web
VIAJE = UUID("00000000-0000-4000-8000-0000000000c1")
OTRO = UUID("00000000-0000-4000-8000-0000000000b9")
TIPO = {"Content-Type": "application/vnd.trotamundos.v1+json"}


def token(sub: str, correo: str | None = None, alcances=("usuario",)) -> dict[str, str]:
    datos = {"sub": sub, "alcances": list(alcances),
             "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    if correo:
        datos["email"] = correo
    return {"Authorization": f"Bearer {jwt.encode(datos, SECRETO_JWT, algorithm='HS256')}"}


class Viajes:
    """`itinerary-lectura` en memoria: el viaje del doble de `bff-web`, solo para su dueño."""

    def __init__(self, viaje: dict):
        self.datos = viaje

    def viaje(self, usuario_id, viaje_id):
        if UUID(str(usuario_id)) == DUENO and UUID(str(viaje_id)) == VIAJE:
            return copy.deepcopy(self.datos)
        return None


@pytest.fixture
def armado(dsn, esquema, contratos, observacion):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    viaje = DobleDownstream(observacion).viaje
    viaje["hasta"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace(
        "+00:00", "Z")
    sharing = Sharing(configuracion, esquema=esquema, contratos=contratos, lector=Viajes(viaje),
                      secreto_jwt=SECRETO_JWT, secreto_vale=SECRETO_VALE)
    sharing.crear_esquema()
    cliente_sharing = TestClient(sharing.app())

    otro_esquema = f"{esquema}_ia"
    enviador = EnviadorOtpEnMemoria()
    consultor = ConsultorDeSharingHttp("http://testserver", "AM", cliente=cliente_sharing)
    identidad = IdentityAccess(configuracion, esquema=otro_esquema, contratos=contratos,
                               consultor_designados=consultor, consultor_recursos=consultor,
                               enviador_otp=enviador, secreto_jwt=SECRETO_JWT,
                               secreto_vale=SECRETO_VALE)
    identidad.crear_esquema()
    cliente_identidad = TestClient(identidad.app())
    sharing._autorizador = puertos.AutorizadorHttp("http://testserver", cliente=cliente_identidad)
    try:
        yield cliente_sharing, cliente_identidad, sharing, enviador
    finally:
        with psycopg.connect(dsn, autocommit=True) as conexion:
            conexion.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(otro_esquema)))


def _compartir(cliente, designados=("ana@ejemplo.com",), clave=None, **extra):
    return cliente.post(f"/viajes/{VIAJE}/comparticiones", headers={
        **token(str(DUENO)), **TIPO, "Idempotency-Key": clave or str(uuid4())},
        content=json.dumps({"designados": list(designados), **extra}))


def test_compartir_listar_y_revocar(armado, contratos):
    cliente, _, _, _ = armado
    clave = str(uuid4())
    creada = _compartir(cliente, ("Ana@Ejemplo.com", "beto@ejemplo.com"), clave=clave)
    assert creada.status_code == 201, creada.text
    cuerpo = creada.json()
    contratos.validar("openapi/sharing.yaml#/components/schemas/Comparticion", cuerpo)
    assert cuerpo["designados"] == ["ana@ejemplo.com", "beto@ejemplo.com"]
    assert cuerpo["estado"] == "Activa"
    assert _compartir(cliente, ("Ana@Ejemplo.com", "beto@ejemplo.com"), clave=clave).json() == cuerpo

    lista = cliente.get(f"/viajes/{VIAJE}/comparticiones", headers=token(str(DUENO)))
    assert [c["id"] for c in lista.json()] == [cuerpo["id"]]
    revocar = f"/viajes/{VIAJE}/comparticiones/{cuerpo['id']}"
    assert cliente.delete(revocar, headers=token(str(OTRO))).status_code == 404
    assert cliente.delete(revocar, headers=token(str(DUENO))).status_code == 204
    assert cliente.get(f"/viajes/{VIAJE}/comparticiones",
                       headers=token(str(DUENO))).json()[0]["estado"] == "Revocada"


def test_el_vencimiento_no_pasa_del_fin_del_viaje_mas_30_dias(armado):
    cliente, _, sharing, _ = armado
    lejos = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    vence = datetime.fromisoformat(_compartir(cliente, expiraEn=lejos).json()["expiraEn"])
    hasta = datetime.fromisoformat(sharing._lector.datos["hasta"])
    assert vence == hasta + timedelta(days=30)
    pasado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _compartir(cliente, expiraEn=pasado).status_code == 400


def test_solo_el_dueno_comparte_su_viaje(armado):
    cliente, _, _, _ = armado
    ajeno = cliente.post(f"/viajes/{VIAJE}/comparticiones", headers={
        **token(str(OTRO)), **TIPO, "Idempotency-Key": str(uuid4())},
        content=json.dumps({"designados": ["ana@ejemplo.com"]}))
    assert ajeno.status_code == 404
    assert cliente.get(f"/viajes/{VIAJE}/comparticiones").status_code == 401


def test_el_designado_ve_el_viaje_y_los_demas_el_mismo_404(armado):
    cliente, _, _, _ = armado
    cid = _compartir(cliente).json()["id"]
    designado = cliente.get(f"/comparticiones/{cid}", headers=token(str(uuid4()), "ana@ejemplo.com"))
    assert designado.status_code == 200, designado.text
    assert designado.json()["id"] == str(VIAJE)
    assert designado.headers["cache-control"] == "private, no-store"

    respuestas = [
        cliente.get(f"/comparticiones/{cid}", headers=token(str(uuid4()), "intruso@ejemplo.com")),
        cliente.get(f"/comparticiones/{uuid4()}", headers=token(str(uuid4()), "ana@ejemplo.com")),
    ]
    assert {r.status_code for r in respuestas} == {404}
    assert len({r.content for r in respuestas}) == 1  # idénticas: cero fugas de existencia
    assert cliente.get(f"/comparticiones/{cid}").status_code == 401

    cliente.delete(f"/viajes/{VIAJE}/comparticiones/{cid}", headers=token(str(DUENO)))
    assert cliente.get(f"/comparticiones/{cid}",
                       headers=token(str(uuid4()), "ana@ejemplo.com")).status_code == 404


def test_un_invitado_sin_cuenta_entra_con_el_codigo_de_un_solo_uso(armado):
    cliente, identidad, _, enviador = armado
    cid = _compartir(cliente).json()["id"]
    pedido = {"comparticionId": cid, "correo": "ana@ejemplo.com"}
    assert identidad.post("/sesiones/invitado/codigo", json=pedido).status_code == 202
    assert identidad.post("/sesiones/invitado/codigo", json={
        **pedido, "correo": "intruso@ejemplo.com"}).status_code == 202  # mismo mensaje neutro
    assert (UUID(cid), "intruso@ejemplo.com") not in enviador.enviados
    codigo = enviador.enviados[(UUID(cid), "ana@ejemplo.com")]
    sesion = identidad.post("/sesiones/invitado/verificacion", json={**pedido, "codigo": codigo})
    assert sesion.status_code == 201, sesion.text

    invitado = {"Authorization": f"Bearer {sesion.json()['tokenAcceso']}"}
    assert cliente.get(f"/comparticiones/{cid}", headers=invitado).status_code == 200
    otra = _compartir(cliente, ("carla@ejemplo.com",)).json()["id"]
    assert cliente.get(f"/comparticiones/{otra}", headers=invitado).status_code == 404


def test_previsualizar_y_publicar_solo_la_lista_blanca(armado, contratos):
    cliente, _, sharing, _ = armado
    resumen = cliente.get(f"/viajes/{VIAJE}/publicaciones/previsualizacion",
                          headers=token(str(DUENO)))
    assert resumen.status_code == 200
    contratos.validar("openapi/sharing.yaml#/components/schemas/ResumenPublicable", resumen.json())
    assert resumen.json()["tiposTransporte"] == ["vuelo"]
    assert "ABC123" not in resumen.text and "1402" not in resumen.text  # sin localizador ni vuelo

    cuerpo = {"red": "instagram", "resumen": resumen.json(), "confirmado": True}
    clave = str(uuid4())
    for _ in range(2):  # idempotente
        assert cliente.post(f"/viajes/{VIAJE}/publicaciones", content=json.dumps(cuerpo), headers={
            **token(str(DUENO)), **TIPO, "Idempotency-Key": clave}).status_code == 202
    assert sharing.redes.publicadas == [("instagram", resumen.json())]
    con_localizador = {**cuerpo, "resumen": {**resumen.json(), "localizador": "ABC123"}}
    sin_confirmar = {**cuerpo, "confirmado": False}
    for invalido in (con_localizador, sin_confirmar):
        assert cliente.post(f"/viajes/{VIAJE}/publicaciones", content=json.dumps(invalido), headers={
            **token(str(DUENO)), **TIPO, "Idempotency-Key": str(uuid4())}).status_code == 400


def test_la_orden_de_borrado_se_lleva_las_comparticiones(armado):
    cliente, _, _, _ = armado
    cid = _compartir(cliente).json()["id"]
    assert cliente.delete(f"/interno/usuarios/{DUENO}").status_code == 204
    assert cliente.get(f"/interno/comparticiones/{cid}").status_code == 404
