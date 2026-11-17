"""Módulo `autenticacion-oidc` (ADR-0007, ADR-0028, ADR-0030).

Gestiona la federación OIDC simulada (`E-14`), la emisión de sesiones con `region_primaria`
(ADR-0018) y el desafío OTP de 6 dígitos para designados sin cuenta previa (`ADR-0028`).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

import jwt
import psycopg

from trotamundos.servicios.identity_access import auditoria_y_revocacion as auditoria

TTL_SESION = timedelta(hours=1)
TTL_OTP_INVITADO = timedelta(minutes=10)
MAX_INTENTOS_OTP = 3
REGIONES_VALIDAS = frozenset({"AM", "EU", "AP"})

DDL = (
    """
    CREATE TABLE IF NOT EXISTS usuario_identidad (
        usuario_id      uuid        PRIMARY KEY,
        sujeto_externo  text        NOT NULL UNIQUE,
        correo          text        NOT NULL,
        region_primaria text        NOT NULL,
        creado_en       timestamptz NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS mapa_seudonimo_usuario (
        usuario_id          uuid PRIMARY KEY,
        seudonimo_analitico text NOT NULL UNIQUE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS codigo_invitado (
        comparticion_id uuid        NOT NULL,
        correo          text        NOT NULL,
        codigo_hash     text        NOT NULL,
        intentos        integer     NOT NULL DEFAULT 0,
        expira_en       timestamptz NOT NULL,
        PRIMARY KEY (comparticion_id, correo)
    );
    """,
)


class CredencialesInvalidas(Exception):
    """El código OIDC o el verificador PKCE fueron rechazados por el proveedor."""


class AccesoInvitadoDenegado(Exception):
    """El código OTP es inválido, venció o superó los intentos (responde 404 opaco)."""


@dataclass(frozen=True)
class PerfilOidc:
    sujeto_externo: str
    correo: str
    region_primaria: str


class ProveedorOidc(Protocol):
    def intercambiar(self, codigo: str, verificador_pkce: str, uri_redireccion: str) -> PerfilOidc: ...


class ConsultorDeDesignados(Protocol):
    """Verifica si un correo está en `designados` de una compartición activa (ADR-0028)."""

    def esta_designado(self, comparticion_id: UUID, correo: str) -> tuple[bool, str]: ...


class EnviadorOtp(Protocol):
    def enviar(self, correo: str, comparticion_id: UUID, codigo: str) -> None: ...


class ProveedorOidcSimulado:
    """Simulador determinista del proveedor OIDC externo (`E-14`, ADR-0036)."""

    def __init__(self, region_por_omision: str = "AM"):
        self._region_por_omision = region_por_omision

    def intercambiar(self, codigo: str, verificador_pkce: str, uri_redireccion: str) -> PerfilOidc:
        if not codigo or not verificador_pkce or codigo.startswith("invalido"):
            raise CredencialesInvalidas("Código de autorización o PKCE inválido")
        region = self._region_por_omision
        identidad = codigo
        if codigo.startswith("oidc:"):
            partes = codigo.split(":")
            identidad = partes[1] or "viajero"
            if len(partes) >= 3 and partes[2] in REGIONES_VALIDAS:
                region = partes[2]
        correo = identidad if "@" in identidad else f"{identidad}@ejemplo.trotamundos.app"
        return PerfilOidc(
            sujeto_externo=f"oidc:{correo}",
            correo=correo.lower(),
            region_primaria=region,
        )


class ConsultorNulo:
    """Implementación por defecto mientras `sharing` (paso 13) no esté conectado."""

    def esta_designado(self, comparticion_id: UUID, correo: str) -> tuple[bool, str]:
        return False, "AM"


class EnviadorOtpEnMemoria:
    """Registra en memoria el último código emitido para pruebas y demostración."""

    def __init__(self) -> None:
        self.enviados: dict[tuple[UUID, str], str] = {}

    def enviar(self, correo: str, comparticion_id: UUID, codigo: str) -> None:
        self.enviados[(comparticion_id, correo.lower())] = codigo


def crear_sesion(
    conexion: psycopg.Connection,
    proveedor: ProveedorOidc,
    *,
    codigo: str,
    verificador_pkce: str,
    uri_redireccion: str,
    secreto_jwt: str,
    ahora: datetime | None = None,
) -> dict[str, str]:
    """Intercambia el código OIDC por una sesión JWT con `region_primaria`."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        perfil = proveedor.intercambiar(codigo, verificador_pkce, uri_redireccion)
    except CredencialesInvalidas:
        auditoria.registrar_evento(
            conexion,
            actor="anonimo",
            accion="crear_sesion",
            recurso_tipo="sesion",
            recurso_id="oidc",
            resultado="denegado",
            motivo="codigo_oidc_invalido",
            ocurrido_en=instante,
        )
        raise

    fila = conexion.execute(
        "SELECT usuario_id, region_primaria FROM usuario_identidad WHERE sujeto_externo = %s",
        (perfil.sujeto_externo,),
    ).fetchone()
    if fila is None:
        usuario_id = uuid4()
        region = perfil.region_primaria
        conexion.execute(
            """
            INSERT INTO usuario_identidad (usuario_id, sujeto_externo, correo, region_primaria, creado_en)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (usuario_id, perfil.sujeto_externo, perfil.correo, region, instante),
        )
        seudonimo = f"seu_{hashlib.sha256(f'{usuario_id}:{secrets.token_hex(16)}'.encode()).hexdigest()[:24]}"
        conexion.execute(
            """
            INSERT INTO mapa_seudonimo_usuario (usuario_id, seudonimo_analitico)
            VALUES (%s, %s)
            """,
            (usuario_id, seudonimo),
        )
    else:
        usuario_id, region = fila["usuario_id"], fila["region_primaria"]

    expira_en = instante + TTL_SESION
    token_acceso = jwt.encode(
        {
            "sub": str(usuario_id),
            "email": perfil.correo,
            "region_primaria": region,
            "iat": int(instante.timestamp()),
            "exp": int(expira_en.timestamp()),
            "alcances": ["usuario"],
        },
        secreto_jwt,
        algorithm="HS256",
    )
    token_refresco = f"rt_{secrets.token_urlsafe(32)}"

    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=str(usuario_id),
        accion="crear_sesion",
        recurso_tipo="sesion",
        recurso_id=str(usuario_id),
        resultado="permitido",
        detalle={"regionPrimaria": region},
        ocurrido_en=instante,
    )
    return {
        "tokenAcceso": token_acceso,
        "tokenRefresco": token_refresco,
        "expiraEn": expira_en.isoformat(),
        "regionPrimaria": region,
    }


def solicitar_codigo_invitado(
    conexion: psycopg.Connection,
    consultor: ConsultorDeDesignados,
    enviador: EnviadorOtp,
    *,
    comparticion_id: UUID,
    correo: str,
    ahora: datetime | None = None,
) -> None:
    """Genera y envía un OTP de 6 dígitos solo si el correo figura como designado (ADR-0028).

    Nunca revela si el correo está autorizado: quien llama siempre devuelve 202 neutro.
    """
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    correo_norm = correo.strip().lower()
    autorizado, _ = consultor.esta_designado(comparticion_id, correo_norm)
    if not autorizado:
        auditoria.registrar_evento(
            conexion,
            actor="invitado",
            accion="solicitar_otp_invitado",
            recurso_tipo="comparticion",
            recurso_id=str(comparticion_id),
            resultado="denegado",
            motivo="no_designado",
            ocurrido_en=instante,
        )
        return

    codigo = f"{secrets.randbelow(1_000_000):06d}"
    codigo_hash = hashlib.sha256(f"{comparticion_id}:{correo_norm}:{codigo}".encode()).hexdigest()
    expira_en = instante + TTL_OTP_INVITADO
    conexion.execute(
        """
        INSERT INTO codigo_invitado (comparticion_id, correo, codigo_hash, intentos, expira_en)
        VALUES (%s, %s, %s, 0, %s)
        ON CONFLICT (comparticion_id, correo) DO UPDATE SET
            codigo_hash = EXCLUDED.codigo_hash,
            intentos = 0,
            expira_en = EXCLUDED.expira_en
        """,
        (comparticion_id, correo_norm, codigo_hash, expira_en),
    )
    enviador.enviar(correo_norm, comparticion_id, codigo)
    auditoria.registrar_evento(
        conexion,
        actor="invitado",
        accion="solicitar_otp_invitado",
        recurso_tipo="comparticion",
        recurso_id=str(comparticion_id),
        resultado="permitido",
        ocurrido_en=instante,
    )


def verificar_codigo_invitado(
    conexion: psycopg.Connection,
    consultor: ConsultorDeDesignados,
    *,
    comparticion_id: UUID,
    correo: str,
    codigo: str,
    secreto_jwt: str,
    ahora: datetime | None = None,
) -> dict[str, str]:
    """Canjea un OTP válido por un token efímero `lectura:comparticion:{id}` sin crear perfil."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    correo_norm = correo.strip().lower()
    fila = conexion.execute(
        """
        SELECT codigo_hash, intentos, expira_en
        FROM codigo_invitado
        WHERE comparticion_id = %s AND correo = %s
        """,
        (comparticion_id, correo_norm),
    ).fetchone()
    if fila is None:
        auditoria.registrar_evento(
            conexion,
            actor="invitado",
            accion="verificar_otp_invitado",
            recurso_tipo="comparticion",
            recurso_id=str(comparticion_id),
            resultado="denegado",
            motivo="otp_inexistente",
            ocurrido_en=instante,
        )
        raise AccesoInvitadoDenegado()

    codigo_hash_guardado = fila["codigo_hash"]
    intentos = fila["intentos"]
    expira_en = fila["expira_en"]
    if expira_en < instante or int(intentos) >= MAX_INTENTOS_OTP:
        auditoria.registrar_evento(
            conexion,
            actor="invitado",
            accion="verificar_otp_invitado",
            recurso_tipo="comparticion",
            recurso_id=str(comparticion_id),
            resultado="denegado",
            motivo="otp_vencido_o_agotado",
            ocurrido_en=instante,
        )
        raise AccesoInvitadoDenegado()

    codigo_hash = hashlib.sha256(f"{comparticion_id}:{correo_norm}:{codigo}".encode()).hexdigest()
    if not secrets.compare_digest(codigo_hash, codigo_hash_guardado):
        conexion.execute(
            """
            UPDATE codigo_invitado SET intentos = intentos + 1
            WHERE comparticion_id = %s AND correo = %s
            """,
            (comparticion_id, correo_norm),
        )
        auditoria.registrar_evento(
            conexion,
            actor="invitado",
            accion="verificar_otp_invitado",
            recurso_tipo="comparticion",
            recurso_id=str(comparticion_id),
            resultado="denegado",
            motivo="otp_incorrecto",
            ocurrido_en=instante,
        )
        raise AccesoInvitadoDenegado()

    conexion.execute(
        "DELETE FROM codigo_invitado WHERE comparticion_id = %s AND correo = %s",
        (comparticion_id, correo_norm),
    )
    _, region = consultor.esta_designado(comparticion_id, correo_norm)
    expira_sesion = instante + TTL_SESION
    alcance = f"lectura:comparticion:{comparticion_id}"
    token_acceso = jwt.encode(
        {
            "sub": f"invitado:{correo_norm}",
            "email": correo_norm,
            "email_verificado": True,
            "region_primaria": region,
            "alcances": [alcance],
            "iat": int(instante.timestamp()),
            "exp": int(expira_sesion.timestamp()),
        },
        secreto_jwt,
        algorithm="HS256",
    )
    auditoria.registrar_evento(
        conexion,
        actor=f"invitado:{correo_norm}",
        accion="verificar_otp_invitado",
        recurso_tipo="comparticion",
        recurso_id=str(comparticion_id),
        resultado="permitido",
        detalle={"alcance": alcance},
        ocurrido_en=instante,
    )
    return {
        "tokenAcceso": token_acceso,
        "expiraEn": expira_sesion.isoformat(),
        "regionPrimaria": region,
    }


def obtener_region_usuario(conexion: psycopg.Connection, usuario_id: UUID) -> str | None:
    fila = conexion.execute(
        "SELECT region_primaria FROM usuario_identidad WHERE usuario_id = %s",
        (usuario_id,),
    ).fetchone()
    return str(fila["region_primaria"]) if fila else None


def datos_de_identidad(conexion: psycopg.Connection, usuario_id: UUID) -> dict[str, str] | None:
    """Lo que `identity-access` guarda de la persona (para la exportación, ADR-0030)."""
    fila = conexion.execute(
        "SELECT correo, region_primaria, creado_en FROM usuario_identidad WHERE usuario_id = %s",
        (usuario_id,),
    ).fetchone()
    if fila is None:
        return None
    return {
        "correo": fila["correo"],
        "regionPrimaria": fila["region_primaria"],
        "creadoEn": fila["creado_en"].astimezone(timezone.utc).isoformat(),
    }


def obtener_seudonimo(conexion: psycopg.Connection, usuario_id: UUID) -> str | None:
    fila = conexion.execute(
        "SELECT seudonimo_analitico FROM mapa_seudonimo_usuario WHERE usuario_id = %s",
        (usuario_id,),
    ).fetchone()
    return str(fila["seudonimo_analitico"]) if fila else None


def eliminar_identidad_usuario(
    conexion: psycopg.Connection,
    usuario_id: UUID,
    *,
    ahora: datetime | None = None,
) -> str | None:
    """Elimina la identidad R1 y el vínculo de seudónimo devolviendo `seudonimo_analitico` (ADR-0030)."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seudonimo = obtener_seudonimo(conexion, usuario_id)
    conexion.execute("DELETE FROM mapa_seudonimo_usuario WHERE usuario_id = %s", (usuario_id,))
    conexion.execute("DELETE FROM usuario_identidad WHERE usuario_id = %s", (usuario_id,))
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=str(usuario_id),
        accion="suprimir_identidad_r1",
        recurso_tipo="cuenta",
        recurso_id=str(usuario_id),
        resultado="permitido",
        ocurrido_en=instante,
    )
    return seudonimo
