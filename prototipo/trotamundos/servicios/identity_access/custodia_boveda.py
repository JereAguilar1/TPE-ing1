"""Módulo `custodia-boveda` (ADR-0029, Regla R5-estricto, QA-13).

Es el **único** módulo del sistema autorizado a usar el KMS/bóveda y descifrar credenciales
delegadas de correo (`AES-256-GCM` con jerarquía `KEK_region` → `DEK_u` y AAD por usuario).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from trotamundos.servicios.identity_access import auditoria_y_revocacion as auditoria

TTL_MAXIMO_TOKEN_EFIMERO = timedelta(minutes=15)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS boveda_dek (
        usuario_id   uuid        PRIMARY KEY,
        region       text        NOT NULL,
        kek_version  integer     NOT NULL,
        dek_envuelta bytea       NOT NULL,
        creada_en    timestamptz NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS boveda_secreto (
        buzon_id       uuid        PRIMARY KEY,
        usuario_id     uuid        NOT NULL,
        proposito      text        NOT NULL,
        key_version    integer     NOT NULL,
        nonce          bytea       NOT NULL,
        cifrado        bytea       NOT NULL,
        actualizado_en timestamptz NOT NULL
    );
    CREATE INDEX IF NOT EXISTS boveda_secreto_por_usuario ON boveda_secreto (usuario_id);
    """,
)


class ErrorDeBoveda(RuntimeError):
    """Error al envolver, desenvolver o descifrar un secreto en la bóveda."""


@dataclass
class _VersionKek:
    clave: bytes
    habilitada: bool = True


class KmsLocal:
    """Simulador local del HSM/KMS regional (`VAULT`, ADR-0029, ADR-0036).

    Mantiene las claves maestras `KEK_region` confinadas en memoria; el material criptográfico
    nunca se persiste en la base de datos operacional.
    """

    def __init__(self, semilla: bytes | None = None):
        # Si no se provee semilla (p. ej. pruebas), genera una efímera por instancia.
        self._semilla = semilla or os.urandom(32)
        self._claves: dict[tuple[str, int], _VersionKek] = {}
        self._version_actual: dict[str, int] = {}

    def _derivar_kek(self, region: str, version: int) -> bytes:
        return hashlib.sha256(
            self._semilla + f":{region}:v{version}".encode("utf-8")
        ).digest()

    def version_actual(self, region: str) -> int:
        if region not in self._version_actual:
            self._version_actual[region] = 1
            self._claves[(region, 1)] = _VersionKek(self._derivar_kek(region, 1), True)
        return self._version_actual[region]

    def envolver(self, region: str, dek: bytes) -> tuple[int, bytes]:
        version = self.version_actual(region)
        entrada = self._claves[(region, version)]
        if not entrada.habilitada:
            raise ErrorDeBoveda(f"La versión v{version} de KEK_{region} está inhabilitada")
        nonce = os.urandom(12)
        aad = f"kek:{region}:v{version}".encode("utf-8")
        envuelta = nonce + AESGCM(entrada.clave).encrypt(nonce, dek, aad)
        return version, envuelta

    def desenvolver(self, region: str, version: int, dek_envuelta: bytes) -> bytes:
        entrada = self._claves.get((region, version))
        if entrada is None:
            # Si el proceso reinició con la misma semilla, reconstruye la clave salvo inhabilitación.
            entrada = _VersionKek(self._derivar_kek(region, version), True)
            self._claves[(region, version)] = entrada
        if not entrada.habilitada:
            raise ErrorDeBoveda(f"La versión v{version} de KEK_{region} fue inhabilitada")
        nonce, cuerpo = dek_envuelta[:12], dek_envuelta[12:]
        aad = f"kek:{region}:v{version}".encode("utf-8")
        try:
            return AESGCM(entrada.clave).decrypt(nonce, cuerpo, aad)
        except Exception as exc:
            raise ErrorDeBoveda("No se pudo desenvolver la DEK") from exc

    def rotar_region(self, region: str) -> int:
        """Crea `v{N+1}` manteniendo `v{N}` habilitada para lectura sin corte (ADR-0029)."""
        nueva = self.version_actual(region) + 1
        self._version_actual[region] = nueva
        self._claves[(region, nueva)] = _VersionKek(self._derivar_kek(region, nueva), True)
        return nueva

    def inhabilitar_version_kek(self, region: str, version: int) -> None:
        """Inhabilita de inmediato `KEK_region` `v{version}` en fase 1 de emergencia."""
        if (region, version) not in self._claves:
            self._claves[(region, version)] = _VersionKek(
                self._derivar_kek(region, version), False
            )
        else:
            self._claves[(region, version)].habilitada = False

    def esta_habilitada(self, region: str, version: int) -> bool:
        entrada = self._claves.get((region, version))
        return True if entrada is None else entrada.habilitada


def _aad(usuario_id: UUID, proposito: str, key_version: int) -> bytes:
    """AAD vinculada a `{usuario_id, proposito, key_version}` (ADR-0029)."""
    return json.dumps(
        {
            "usuario_id": str(usuario_id),
            "proposito": proposito,
            "key_version": key_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _obtener_o_crear_dek(
    conexion: psycopg.Connection,
    kms: KmsLocal,
    usuario_id: UUID,
    region: str,
    ahora: datetime,
) -> tuple[int, bytes]:
    fila = conexion.execute(
        "SELECT region, kek_version, dek_envuelta FROM boveda_dek WHERE usuario_id = %s",
        (usuario_id,),
    ).fetchone()
    if fila is not None:
        reg, ver, envuelta = fila["region"], fila["kek_version"], fila["dek_envuelta"]
        return int(ver), kms.desenvolver(reg, int(ver), bytes(envuelta))

    dek = AESGCM.generate_key(bit_length=256)
    version, envuelta = kms.envolver(region, dek)
    conexion.execute(
        """
        INSERT INTO boveda_dek (usuario_id, region, kek_version, dek_envuelta, creada_en)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (usuario_id, region, version, envuelta, ahora),
    )
    return version, dek


def guardar_secreto(
    conexion: psycopg.Connection,
    kms: KmsLocal,
    *,
    usuario_id: UUID,
    region: str,
    buzon_id: UUID,
    proposito: str,
    secreto_en_claro: str,
    actor: str,
    ahora: datetime | None = None,
) -> None:
    """Cifra un *refresh token* o credencial delegada bajo `DEK_u` y audita la custodia."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key_version, dek = _obtener_o_crear_dek(conexion, kms, usuario_id, region, instante)
    nonce = os.urandom(12)
    cifrado = AESGCM(dek).encrypt(
        nonce,
        secreto_en_claro.encode("utf-8"),
        _aad(usuario_id, proposito, key_version),
    )
    conexion.execute(
        """
        INSERT INTO boveda_secreto (
            buzon_id, usuario_id, proposito, key_version, nonce, cifrado, actualizado_en
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (buzon_id) DO UPDATE SET
            proposito = EXCLUDED.proposito,
            key_version = EXCLUDED.key_version,
            nonce = EXCLUDED.nonce,
            cifrado = EXCLUDED.cifrado,
            actualizado_en = EXCLUDED.actualizado_en
        """,
        (buzon_id, usuario_id, proposito, key_version, nonce, cifrado, instante),
    )
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=actor,
        accion="guardar_secreto_buzon",
        recurso_tipo="buzon",
        recurso_id=str(buzon_id),
        resultado="permitido",
        detalle={"proposito": proposito, "keyVersion": key_version},
        ocurrido_en=instante,
    )


def emitir_token_efimero(
    conexion: psycopg.Connection,
    kms: KmsLocal,
    *,
    usuario_id: UUID,
    buzon_id: UUID,
    actor: str,
    ttl: timedelta = TTL_MAXIMO_TOKEN_EFIMERO,
    ahora: datetime | None = None,
) -> tuple[str, datetime]:
    """Desenvuelve `DEK_u`, descifra el secreto de buzón y emite un token efímero (`TTL ≤ 15 m`)."""
    if ttl <= timedelta(0) or ttl > TTL_MAXIMO_TOKEN_EFIMERO:
        raise ValueError("El TTL del token efímero debe estar entre 1 s y 15 min")
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)

    fila = conexion.execute(
        """
        SELECT d.region, d.kek_version, d.dek_envuelta,
               s.proposito, s.key_version, s.nonce, s.cifrado
        FROM boveda_secreto s
        JOIN boveda_dek d ON d.usuario_id = s.usuario_id
        WHERE s.buzon_id = %s AND s.usuario_id = %s
        """,
        (buzon_id, usuario_id),
    ).fetchone()
    if fila is None:
        auditoria.registrar_evento(
            conexion,
            usuario_id=usuario_id,
            actor=actor,
            accion="emitir_token_efimero",
            recurso_tipo="buzon",
            recurso_id=str(buzon_id),
            resultado="error",
            motivo="secreto_inexistente",
            ocurrido_en=instante,
        )
        raise ErrorDeBoveda("No existe secreto custodiado para el buzón")

    region = fila["region"]
    kek_version = fila["kek_version"]
    dek_envuelta = fila["dek_envuelta"]
    proposito = fila["proposito"]
    key_version = fila["key_version"]
    nonce = fila["nonce"]
    cifrado = fila["cifrado"]
    dek = kms.desenvolver(region, int(kek_version), bytes(dek_envuelta))
    try:
        secreto = AESGCM(dek).decrypt(
            bytes(nonce),
            bytes(cifrado),
            _aad(usuario_id, proposito, int(key_version)),
        ).decode("utf-8")
    except Exception as exc:
        raise ErrorDeBoveda("Falló la verificación AAD/GCM del secreto") from exc

    # Simula el intercambio ante el proveedor OAuth: deriva un access token opaco de corta vida
    # sin devolver jamás el refresh token custodiado.
    huella = hashlib.sha256(
        f"{secreto}:{buzon_id}:{instante.isoformat()}:{secrets.token_hex(8)}".encode("utf-8")
    ).hexdigest()[:32]
    token_efimero = f"eph_{huella}"
    expira_en = instante + ttl

    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=actor,
        accion="emitir_token_efimero",
        recurso_tipo="buzon",
        recurso_id=str(buzon_id),
        resultado="permitido",
        detalle={"expiraEn": expira_en.isoformat()},
        ocurrido_en=instante,
    )
    return token_efimero, expira_en


def destruir_secreto(
    conexion: psycopg.Connection,
    *,
    usuario_id: UUID,
    buzon_id: UUID,
    actor: str,
    ahora: datetime | None = None,
) -> None:
    """Elimina el secreto cifrado de un buzón al revocarlo."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conexion.execute(
        "DELETE FROM boveda_secreto WHERE buzon_id = %s AND usuario_id = %s",
        (buzon_id, usuario_id),
    )
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=actor,
        accion="destruir_secreto_buzon",
        recurso_tipo="buzon",
        recurso_id=str(buzon_id),
        resultado="permitido",
        ocurrido_en=instante,
    )


def destruir_dek(
    conexion: psycopg.Connection,
    *,
    usuario_id: UUID,
    actor: str,
    ahora: datetime | None = None,
) -> None:
    """Destruye `DEK_u` y todos los secretos del usuario (cripto-supresión, ADR-0030)."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conexion.execute("DELETE FROM boveda_secreto WHERE usuario_id = %s", (usuario_id,))
    conexion.execute("DELETE FROM boveda_dek WHERE usuario_id = %s", (usuario_id,))
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=actor,
        accion="destruir_dek_usuario",
        recurso_tipo="cuenta",
        recurso_id=str(usuario_id),
        resultado="permitido",
        ocurrido_en=instante,
    )


def rotar_kek(
    conexion: psycopg.Connection,
    kms: KmsLocal,
    region: str,
    *,
    actor: str,
    ahora: datetime | None = None,
) -> tuple[int, int]:
    """Rota `KEK_region` a `v{N+1}` y re-envuelve las `DEK_u` sin tocar los secretos (ADR-0029)."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    nueva_version = kms.rotar_region(region)
    filas = conexion.execute(
        "SELECT usuario_id, kek_version, dek_envuelta FROM boveda_dek WHERE region = %s",
        (region,),
    ).fetchall()
    cantidad = 0
    for fila in filas:
        usuario_id = fila["usuario_id"]
        version_vieja = fila["kek_version"]
        envuelta = fila["dek_envuelta"]
        dek = kms.desenvolver(region, int(version_vieja), bytes(envuelta))
        version_envuelta, nueva_envuelta = kms.envolver(region, dek)
        conexion.execute(
            "UPDATE boveda_dek SET kek_version = %s, dek_envuelta = %s WHERE usuario_id = %s",
            (version_envuelta, nueva_envuelta, usuario_id),
        )
        cantidad += 1

    auditoria.registrar_evento(
        conexion,
        actor=actor,
        accion="rotar_kek_region",
        recurso_tipo="kms_region",
        recurso_id=region,
        resultado="permitido",
        detalle={"nuevaVersion": nueva_version, "deksReenvueltas": cantidad},
        ocurrido_en=instante,
    )
    return nueva_version, cantidad
