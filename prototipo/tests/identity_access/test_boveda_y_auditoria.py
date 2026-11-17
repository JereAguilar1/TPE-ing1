"""Pruebas unitarias de bóveda, detector de anomalías, auditoría, OIDC y ABAC (paso 7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from trotamundos.servicios.identity_access.auditoria_y_revocacion import (
    HASH_GENESIS,
    DetectorDeAnomalias,
    bucket_de_usuario,
    calcular_hash_entrada,
)
from trotamundos.servicios.identity_access.autenticacion_oidc import (
    CredencialesInvalidas,
    ProveedorOidcSimulado,
)
from trotamundos.servicios.identity_access.custodia_boveda import ErrorDeBoveda, KmsLocal
from trotamundos.servicios.identity_access.motor_autorizacion_abac import verificar_vale


def test_kms_envuelve_desenvuelve_y_rota_sin_corte():
    kms = KmsLocal(b"semilla-de-prueba")
    dek = b"0" * 32

    v1, envuelta_v1 = kms.envolver("AM", dek)
    assert v1 == 1
    assert kms.desenvolver("AM", v1, envuelta_v1) == dek

    v2 = kms.rotar_region("AM")
    assert v2 == 2
    # v1 sigue habilitada para lectura mientras se re-envuelven las DEK.
    assert kms.desenvolver("AM", v1, envuelta_v1) == dek

    kms.inhabilitar_version_kek("AM", v1)
    with pytest.raises(ErrorDeBoveda):
        kms.desenvolver("AM", v1, envuelta_v1)


def test_detector_detecta_bucket_ajeno_y_rafaga_anomala():
    detector = DetectorDeAnomalias(p99_base_por_minuto=2)  # límite = 6 en 60 s
    ahora = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    usuario = uuid4()
    bucket_real = bucket_de_usuario(usuario)
    bucket_otro = (bucket_real + 1) % 64

    # Bucket fuera de arrendamiento -> dispara de inmediato.
    motivo = detector.evaluar(
        instancia_id="mail-ingest-1",
        usuario_id=usuario,
        buckets_arrendados={bucket_otro},
        ahora=ahora,
    )
    assert motivo == f"bucket_no_arrendado:{bucket_real}"

    # 6 peticiones dentro del límite pasan; la 7ma en 60 s dispara.
    for i in range(6):
        assert (
            detector.evaluar(
                instancia_id="mail-ingest-2",
                usuario_id=usuario,
                buckets_arrendados={bucket_real},
                ahora=ahora + timedelta(seconds=i),
            )
            is None
        )
    motivo_rafaga = detector.evaluar(
        instancia_id="mail-ingest-2",
        usuario_id=usuario,
        buckets_arrendados={bucket_real},
        ahora=ahora + timedelta(seconds=10),
    )
    assert motivo_rafaga is not None and motivo_rafaga.startswith("tasa_anomala:")


def test_cadena_sha256_de_auditoria_detecta_alteracion():
    instante = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    eid = uuid4()
    uid = uuid4()
    h1 = calcular_hash_entrada(
        entrada_id=eid,
        usuario_id=uid,
        ocurrido_en=instante,
        actor="usuario",
        accion="crear_sesion",
        recurso_tipo="sesion",
        recurso_id=str(uid),
        resultado="permitido",
        motivo="",
        detalle={"regionPrimaria": "AM"},
        hash_anterior=HASH_GENESIS,
    )
    h1_alterado = calcular_hash_entrada(
        entrada_id=eid,
        usuario_id=uid,
        ocurrido_en=instante,
        actor="atacante",
        accion="crear_sesion",
        recurso_tipo="sesion",
        recurso_id=str(uid),
        resultado="permitido",
        motivo="",
        detalle={"regionPrimaria": "AM"},
        hash_anterior=HASH_GENESIS,
    )
    assert h1 != h1_alterado


def test_proveedor_oidc_simulado_resuelve_perfil_y_rechaza_invalido():
    prov = ProveedorOidcSimulado("AM")
    perfil = prov.intercambiar("oidc:ana@ejemplo.com:EU", "pkce-ok", "https://app.test/cb")
    assert perfil.correo == "ana@ejemplo.com"
    assert perfil.region_primaria == "EU"

    with pytest.raises(CredencialesInvalidas):
        prov.intercambiar("invalido-123", "pkce-ok", "https://app.test/cb")


def test_verificar_vale_jws_valida_recurso_accion_y_vencimiento():
    secreto = "secreto-vale-prueba-32-bytes-minimo"
    ahora = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    recurso_id = uuid4()
    vale = jwt.encode(
        {
            "jti": str(uuid4()),
            "sub": str(uuid4()),
            "accion": "leer",
            "recurso_tipo": "viaje",
            "recurso_id": str(recurso_id),
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(seconds=60)).timestamp()),
        },
        secreto,
        algorithm="HS256",
    )

    datos = verificar_vale(
        vale, secreto, recurso_tipo="viaje", recurso_id=recurso_id, accion="leer", ahora=ahora
    )
    assert datos["recurso_id"] == str(recurso_id)

    with pytest.raises(jwt.InvalidTokenError):
        verificar_vale(
            vale, secreto, recurso_tipo="viaje", recurso_id=uuid4(), accion="leer", ahora=ahora
        )
    with pytest.raises(jwt.ExpiredSignatureError):
        verificar_vale(
            vale,
            secreto,
            recurso_tipo="viaje",
            recurso_id=recurso_id,
            accion="leer",
            ahora=ahora + timedelta(seconds=61),
        )
