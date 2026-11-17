"""Pruebas de integración de `identity-access` contra PostgreSQL y contratos (paso 7)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient

from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.identity_access import api
from trotamundos.servicios.identity_access.auditoria_y_revocacion import (
    DetectorDeAnomalias,
    bucket_de_usuario,
)
from trotamundos.servicios.identity_access.autenticacion_oidc import EnviadorOtpEnMemoria
from trotamundos.servicios.identity_access.custodia_boveda import KmsLocal
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
    kms: KmsLocal | None = None,
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
        kms=kms,
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


_MAIL_INGEST = {"X-Servicio-Cliente": "mail-ingest"}


def _conectar_imap(cliente: TestClient, auth: dict[str, str]) -> str:
    resp = cliente.post(
        "/buzones",
        headers={**auth, "Idempotency-Key": str(uuid4())},
        json={"via": "imapDelegado", "credencialDelegada": "app-pwd-revocable"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _filas(dsn: str, esquema: str, consulta: str) -> list[dict]:
    with conectar(dsn, esquema) as conexion:
        return conexion.execute(consulta).fetchall()


def test_tras_la_revocacion_regional_se_reautoriza_y_se_conectan_buzones(dsn, esquema, contratos):
    """ADR-0029: la KEK revocada deja ilegibles los tokens, pero la región sigue operando."""
    cliente, servicio, _ = _armar(dsn, esquema, contratos)
    token, _ = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}
    r_oauth = cliente.post(
        "/buzones", headers={**auth, "Idempotency-Key": str(uuid4())}, json={"via": "oauth"}
    )
    buzon_id = r_oauth.json()["id"]
    assert cliente.post(
        f"/buzones/{buzon_id}/autorizacion", headers=auth, json={"codigo": "antes"}
    ).status_code == 200

    assert servicio.revocar_region_en_bloque("AM", 1) == 1
    # Las DEK_u envueltas con la versión revocada se descartan: no queda nada ilegible guardado.
    assert _filas(dsn, esquema, "SELECT * FROM boveda_dek") == []
    assert _filas(dsn, esquema, "SELECT * FROM boveda_secreto") == []

    # El usuario reautoriza: su token nuevo queda bajo una DEK_u nueva, envuelta con KEK v2.
    r_reaut = cliente.post(
        f"/buzones/{buzon_id}/autorizacion", headers=auth, json={"codigo": "despues"}
    )
    assert r_reaut.status_code == 200
    assert r_reaut.json()["estado"] == "Activo"
    assert [f["kek_version"] for f in _filas(dsn, esquema, "SELECT * FROM boveda_dek")] == [2]
    assert cliente.post(
        f"/buzones/{buzon_id}/token-efimero", headers=_MAIL_INGEST
    ).status_code == 200

    # Otros usuarios de la región también pueden conectar buzones nuevos.
    token_otro, _ = _iniciar_sesion(cliente, "oidc:otra@test.app:AM")
    _conectar_imap(cliente, {"Authorization": f"Bearer {token_otro}"})
    assert servicio.verificar_integridad_auditoria() is True


def test_la_boveda_recupera_sus_versiones_de_kek_tras_reiniciar(dsn, esquema, contratos):
    """Un reinicio con la misma semilla no rehabilita la KEK revocada ni pierde la vigente."""
    semilla = b"semilla-kms-de-pruebas-32-bytes!"
    cliente, servicio, _ = _armar(dsn, esquema, contratos, kms=KmsLocal(semilla))
    token, _ = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}
    _conectar_imap(cliente, auth)
    servicio.revocar_region_en_bloque("AM", 1)
    token_otro, _ = _iniciar_sesion(cliente, "oidc:otra@test.app:AM")
    buzon_nuevo = _conectar_imap(cliente, {"Authorization": f"Bearer {token_otro}"})

    kms_reiniciado = KmsLocal(semilla)
    cliente2, _, _ = _armar(dsn, esquema, contratos, kms=kms_reiniciado)

    assert kms_reiniciado.version_actual("AM") == 2
    assert kms_reiniciado.esta_habilitada("AM", 1) is False
    assert cliente2.post(
        f"/buzones/{buzon_nuevo}/token-efimero", headers=_MAIL_INGEST
    ).status_code == 200
    _conectar_imap(cliente2, auth)
    versiones = {f["kek_version"] for f in _filas(dsn, esquema, "SELECT * FROM boveda_dek")}
    assert versiones == {2}


def test_con_la_semilla_del_entorno_los_buzones_sobreviven_a_un_reinicio(
    dsn, esquema, contratos, monkeypatch
):
    """`docker-compose.yml` pasa `TROTAMUNDOS_KMS_SECRETO` desde `.env`: otro proceso descifra."""
    monkeypatch.setenv("TROTAMUNDOS_KMS_SECRETO", "semilla-fija-del-entorno")
    cliente, _, _ = _armar(dsn, esquema, contratos)
    token, _ = _iniciar_sesion(cliente)
    buzon_id = _conectar_imap(cliente, {"Authorization": f"Bearer {token}"})

    cliente_reiniciado, _, _ = _armar(dsn, esquema, contratos)
    assert cliente_reiniciado.post(
        f"/buzones/{buzon_id}/token-efimero", headers=_MAIL_INGEST
    ).status_code == 200


def test_la_supresion_de_cuenta_publica_la_revocacion_de_cada_buzon(dsn, esquema, contratos):
    """`mail-ingest` consume `EstadoDeBuzonCambiado`: tiene que enterarse de que deje de leer."""
    cliente, _, _ = _armar(dsn, esquema, contratos)
    token, _ = _iniciar_sesion(cliente)
    auth = {"Authorization": f"Bearer {token}"}
    buzon_imap = _conectar_imap(cliente, auth)
    r_reenvio = cliente.post(
        "/buzones", headers={**auth, "Idempotency-Key": str(uuid4())}, json={"via": "reenvio"}
    )
    buzon_reenvio = r_reenvio.json()["id"]

    assert cliente.delete(
        "/privacidad/cuenta", headers={**auth, "Idempotency-Key": str(uuid4())}
    ).status_code == 202

    filas = _filas(
        dsn, esquema,
        "SELECT tipo, carga, carril FROM bandeja_salida ORDER BY creado_en, tipo",
    )
    revocados = {
        f["carga"]["buzonId"]
        for f in filas
        if f["tipo"] == "EstadoDeBuzonCambiado" and f["carga"]["estadoNuevo"] == "Revocado"
    }
    assert revocados == {buzon_imap, buzon_reenvio}
    assert all(
        f["carga"]["motivo"] == "desconectadoPorUsuario" and f["carril"] == "P2"
        for f in filas
        if f["tipo"] == "EstadoDeBuzonCambiado" and f["carga"]["estadoNuevo"] == "Revocado"
    )
    assert [f["carril"] for f in filas if f["tipo"] == "CuentaSuprimida"] == ["P3"]
