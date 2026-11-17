"""Pruebas de integración de `identity-access` contra PostgreSQL y contratos (paso 7)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient

from trotamundos.comun.config import Configuracion
from trotamundos.servicios.identity_access import api
from trotamundos.servicios.identity_access.auditoria_y_revocacion import (
    DetectorDeAnomalias,
    bucket_de_usuario,
)
from trotamundos.servicios.identity_access.autenticacion_oidc import EnviadorOtpEnMemoria
from trotamundos.servicios.identity_access.motor_autorizacion_abac import (
    AtributosRecurso,
    verificar_vale,
)
from trotamundos.servicios.identity_access.servicio import IdentityAccess


class _ConsultorPrueba:
    def __init__(self, comparticiones: dict[UUID, tuple[UUID, frozenset[str], str]]):
        self._comparticiones = comparticiones

    def esta_designado(self, comparticion_id: UUID, correo: str) -> tuple[bool, str]:
        dato = self._comparticiones.get(comparticion_id)
        if dato is None:
            return False, "AM"
        _, designados, region = dato
        return correo.lower() in designados, region

    def atributos(self, tipo: str, recurso_id: UUID) -> AtributosRecurso | None:
        if tipo == "comparticion" and recurso_id in self._comparticiones:
            propietario, designados, _ = self._comparticiones[recurso_id]
            return AtributosRecurso(propietario_id=propietario, designados=designados)
        return None


def _armar(
    dsn: str,
    esquema: str,
    contratos,
    *,
    comparticiones: dict[UUID, tuple[UUID, frozenset[str], str]] | None = None,
    p99_base: int = 20,
):
    cfg = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="")
    consultor = _ConsultorPrueba(comparticiones or {})
    enviador = EnviadorOtpEnMemoria()
    servicio = IdentityAccess(
        cfg,
        esquema=esquema,
        contratos=contratos,
        consultor_designados=consultor,
        enviador_otp=enviador,
        consultor_recursos=consultor,
        detector_anomalias=DetectorDeAnomalias(p99_base_por_minuto=p99_base),
        secreto_jwt="secreto-jwt-pruebas-32-bytes-min",
        secreto_vale="secreto-vale-pruebas-32-bytes-mi",
    )
    servicio.crear_esquema()
    app = api.crear_app(servicio, contratos, servicio._secreto_jwt)
    return TestClient(app), servicio, enviador


def _iniciar_sesion(cliente: TestClient, codigo: str = "oidc:viajero@test.app:AM") -> tuple[str, UUID]:
    resp = cliente.post(
        "/sesiones",
        json={
            "codigo": codigo,
            "verificadorPkce": "pkce-1234",
            "uriRedireccion": "https://app.trotamundos.app/cb",
        },
    )
    assert resp.status_code == 201
    cuerpo = resp.json()
    token = cuerpo["tokenAcceso"]
    sub = UUID(jwt.decode(token, options={"verify_signature": False})["sub"])
    return token, sub


def test_ciclo_de_vida_buzones_boveda_y_token_efimero(dsn, esquema, contratos):
    cliente, servicio, _ = _armar(dsn, esquema, contratos)
    token, uid = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}

    # 1. Conectar buzón OAuth -> Solicitado + urlAutorizacion (idempotente).
    clave = str(uuid4())
    r1 = cliente.post(
        "/buzones",
        headers={**auth, "Idempotency-Key": clave},
        json={"via": "oauth", "proveedor": "gmail"},
    )
    assert r1.status_code == 201
    buzon = r1.json()
    assert buzon["estado"] == "Solicitado"
    assert "urlAutorizacion" in buzon

    r1_rep = cliente.post(
        "/buzones",
        headers={**auth, "Idempotency-Key": clave},
        json={"via": "oauth", "proveedor": "gmail"},
    )
    assert r1_rep.status_code == 201
    assert r1_rep.json() == buzon

    # Antes de autorizar, pedir token efímero da 409 Conflict.
    r_conf = cliente.post(
        f"/buzones/{buzon['id']}/token-efimero",
        headers={"X-Servicio-Cliente": "mail-ingest"},
    )
    assert r_conf.status_code == 409

    # 2. Completar consentimiento OAuth -> Activo.
    r_aut = cliente.post(
        f"/buzones/{buzon['id']}/autorizacion",
        headers=auth,
        json={"codigo": "oauth-code-ok", "direccion": "viajero@gmail.com"},
    )
    assert r_aut.status_code == 200
    assert r_aut.json()["estado"] == "Activo"

    # 3. Otro servicio distinto de mail-ingest recibe 403 (Regla R5 / QA-13).
    r_forb = cliente.post(
        f"/buzones/{buzon['id']}/token-efimero",
        headers={"X-Servicio-Cliente": "itinerary"},
    )
    assert r_forb.status_code == 403

    # 4. mail-ingest dentro de su bucket arrendado recibe token efímero (TTL <= 15 min).
    bucket = bucket_de_usuario(uid)
    r_tok = cliente.post(
        f"/buzones/{buzon['id']}/token-efimero",
        headers={
            "X-Servicio-Cliente": "mail-ingest",
            "X-Instancia-Cliente": "mail-ingest-1",
            "X-Buckets-Arrendados": str(bucket),
        },
    )
    assert r_tok.status_code == 200
    assert r_tok.json()["token"].startswith("eph_")

    # 5. Rotación de KEK_region v1 -> v2 sin corte: sigue emitiendo tokens.
    nueva_ver, reenvueltas = servicio.rotar_kek("AM")
    assert nueva_ver == 2
    assert reenvueltas == 1
    r_tok2 = cliente.post(
        f"/buzones/{buzon['id']}/token-efimero",
        headers={
            "X-Servicio-Cliente": "mail-ingest",
            "X-Instancia-Cliente": "mail-ingest-1",
            "X-Buckets-Arrendados": str(bucket),
        },
    )
    assert r_tok2.status_code == 200

    # 6. Desconectar buzón -> 204 y luego aparece Revocado.
    assert cliente.delete(f"/buzones/{buzon['id']}", headers=auth).status_code == 204
    buzones = cliente.get("/buzones", headers=auth).json()
    assert buzones[0]["estado"] == "Revocado"

    # La cadena de auditoría SHA-256 está intacta.
    assert servicio.verificar_integridad_auditoria() is True


def test_deteccion_anomala_y_revocacion_regional_en_bloque(dsn, esquema, contratos):
    cliente, servicio, _ = _armar(dsn, esquema, contratos, p99_base=1)
    token, uid = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}

    # Conectar buzón por imapDelegado (activo de inmediato) y por reenvío.
    r_imap = cliente.post(
        "/buzones",
        headers={**auth, "Idempotency-Key": str(uuid4())},
        json={"via": "imapDelegado", "credencialDelegada": "app-pwd-revocable"},
    )
    assert r_imap.status_code == 201
    buzon_id = r_imap.json()["id"]

    # Solicitud de bucket ajeno bloquea de inmediato a esa réplica (403 persistente).
    bucket_ajeno = (bucket_de_usuario(uid) + 1) % 64
    r_anom = cliente.post(
        f"/buzones/{buzon_id}/token-efimero",
        headers={
            "X-Servicio-Cliente": "mail-ingest",
            "X-Instancia-Cliente": "mail-ingest-comprometida",
            "X-Buckets-Arrendados": str(bucket_ajeno),
        },
    )
    assert r_anom.status_code == 403

    # Incluso si luego pide un bucket válido, la réplica quedó bloqueada.
    r_post_bloq = cliente.post(
        f"/buzones/{buzon_id}/token-efimero",
        headers={
            "X-Servicio-Cliente": "mail-ingest",
            "X-Instancia-Cliente": "mail-ingest-comprometida",
            "X-Buckets-Arrendados": str(bucket_de_usuario(uid)),
        },
    )
    assert r_post_bloq.status_code == 403

    # Revocación regional en bloque: inhabilita KEK v1 y pasa buzones a RequiereReautorizacion.
    afectados = servicio.revocar_region_en_bloque("AM", 1)
    assert afectados == 1
    assert cliente.get("/buzones", headers=auth).json()[0]["estado"] == "RequiereReautorizacion"
    assert servicio.verificar_integridad_auditoria() is True


def test_invitado_otp_y_evaluacion_abac_con_vale_jws(dsn, esquema, contratos):
    comp_id = uuid4()
    propietario = uuid4()
    cliente, servicio, enviador = _armar(
        dsn,
        esquema,
        contratos,
        comparticiones={comp_id: (propietario, frozenset({"invitado@ejemplo.com"}), "EU")},
    )

    # Respuesta siempre 202 neutra, esté o no designado.
    assert (
        cliente.post(
            "/sesiones/invitado/codigo",
            json={"comparticionId": str(comp_id), "correo": "intruso@ejemplo.com"},
        ).status_code
        == 202
    )
    assert (
        cliente.post(
            "/sesiones/invitado/codigo",
            json={"comparticionId": str(comp_id), "correo": "invitado@ejemplo.com"},
        ).status_code
        == 202
    )

    codigo = enviador.enviados[(comp_id, "invitado@ejemplo.com")]
    # Código erróneo -> 404 opaco.
    assert (
        cliente.post(
            "/sesiones/invitado/verificacion",
            json={"comparticionId": str(comp_id), "correo": "invitado@ejemplo.com", "codigo": "000000"},
        ).status_code
        == 404
    )
    # Código válido -> 201 con alcance lectura:comparticion:{id}.
    r_ok = cliente.post(
        "/sesiones/invitado/verificacion",
        json={"comparticionId": str(comp_id), "correo": "invitado@ejemplo.com", "codigo": codigo},
    )
    assert r_ok.status_code == 201

    # Evaluación ABAC: designado permitido recibe vale JWS válido; no designado -> denegar.
    r_abac_ok = cliente.post(
        "/autorizaciones/evaluar",
        headers={"X-Servicio-Cliente": "sharing"},
        json={
            "sujeto": {
                "usuarioId": str(uuid4()),
                "correoVerificado": "invitado@ejemplo.com",
                "alcances": [f"lectura:comparticion:{comp_id}"],
            },
            "accion": "leer",
            "recurso": {"tipo": "comparticion", "id": str(comp_id)},
        },
    )
    assert r_abac_ok.status_code == 200
    assert r_abac_ok.json()["decision"] == "permitir"
    vale = r_abac_ok.json()["vale"]
    verificar_vale(
        vale, servicio._secreto_vale, recurso_tipo="comparticion", recurso_id=comp_id, accion="leer"
    )

    r_abac_no = cliente.post(
        "/autorizaciones/evaluar",
        headers={"X-Servicio-Cliente": "sharing"},
        json={
            "sujeto": {"usuarioId": str(uuid4()), "correoVerificado": "intruso@ejemplo.com"},
            "accion": "leer",
            "recurso": {"tipo": "comparticion", "id": str(comp_id)},
        },
    )
    assert r_abac_no.status_code == 200
    assert r_abac_no.json() == {"decision": "denegar"}


def test_privacidad_exportacion_y_supresion_fase_1(dsn, esquema, contratos):
    cliente, servicio, _ = _armar(dsn, esquema, contratos)
    token, _ = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}

    r_exp = cliente.post(
        "/privacidad/exportaciones",
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert r_exp.status_code == 202
    assert r_exp.json()["estado"] == "Lista"
    assert len(cliente.get("/privacidad/exportaciones", headers=auth).json()) == 1

    r_sup = cliente.delete(
        "/privacidad/cuenta",
        headers={**auth, "Idempotency-Key": str(uuid4())},
    )
    assert r_sup.status_code == 202
    assert "solicitudId" in r_sup.json()
    assert servicio.verificar_integridad_auditoria() is True
