"""Módulo `auditoria-y-revocacion` (ADR-0029, ADR-0030, QA-13, QA-14).

Mantiene la bitácora inmutable `registro_auditoria` (*append-only* con encadenamiento `SHA-256`),
el detector de anomalías sobre solicitudes de tokens efímeros en ventana deslizante de 60 s y el
registro de instancias bloqueadas para corte inmediato.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

CANTIDAD_BUCKETS = 64
VENTANA_DETECCION = timedelta(seconds=60)
HASH_GENESIS = "0" * 64

DDL = (
    """
    CREATE TABLE IF NOT EXISTS registro_auditoria (
        seq           bigserial   PRIMARY KEY,
        id            uuid        NOT NULL UNIQUE,
        usuario_id    uuid,
        ocurrido_en   timestamptz NOT NULL,
        actor         text        NOT NULL,
        accion        text        NOT NULL,
        recurso_tipo  text        NOT NULL,
        recurso_id    text        NOT NULL,
        resultado     text        NOT NULL,
        motivo        text        NOT NULL DEFAULT '',
        detalle       jsonb       NOT NULL DEFAULT '{}'::jsonb,
        hash_anterior text        NOT NULL,
        hash_actual   text        NOT NULL
    );
    CREATE INDEX IF NOT EXISTS registro_auditoria_por_usuario
        ON registro_auditoria (usuario_id, seq);
    """,
    """
    CREATE TABLE IF NOT EXISTS instancia_bloqueada (
        instancia_id text        PRIMARY KEY,
        motivo       text        NOT NULL,
        bloqueada_en timestamptz NOT NULL
    );
    """,
)


class BovedaDeEmergencia(Protocol):
    """Puerto mínimo para inhabilitar una versión de `KEK_region` en fase 1 de revocación."""

    def inhabilitar_version_kek(self, region: str, version: int) -> None: ...


@dataclass(frozen=True)
class EntradaAuditoria:
    seq: int
    id: UUID
    usuario_id: UUID | None
    ocurrido_en: datetime
    actor: str
    accion: str
    recurso_tipo: str
    recurso_id: str
    resultado: str
    motivo: str
    detalle: dict[str, Any]
    hash_anterior: str
    hash_actual: str


def bucket_de_usuario(usuario_id: UUID) -> int:
    """Partición determinista de `0..63` para `usuario_id` (ADR-0023, ADR-0029)."""
    return zlib.crc32(usuario_id.bytes) % CANTIDAD_BUCKETS


def calcular_hash_entrada(
    *,
    entrada_id: UUID,
    usuario_id: UUID | None,
    ocurrido_en: datetime,
    actor: str,
    accion: str,
    recurso_tipo: str,
    recurso_id: str,
    resultado: str,
    motivo: str,
    detalle: Mapping[str, Any],
    hash_anterior: str,
) -> str:
    """Calcula el `SHA-256` canónico de una fila de auditoría encadenada."""
    canonico = json.dumps(
        {
            "id": str(entrada_id),
            "usuario_id": str(usuario_id) if usuario_id else None,
            "ocurrido_en": ocurrido_en.astimezone(timezone.utc).isoformat(),
            "actor": actor,
            "accion": accion,
            "recurso_tipo": recurso_tipo,
            "recurso_id": recurso_id,
            "resultado": resultado,
            "motivo": motivo,
            "detalle": dict(detalle),
            "hash_anterior": hash_anterior,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonico).hexdigest()


def registrar_evento(
    conexion: psycopg.Connection,
    *,
    actor: str,
    accion: str,
    recurso_tipo: str,
    recurso_id: str,
    resultado: str,
    usuario_id: UUID | None = None,
    motivo: str = "",
    detalle: Mapping[str, Any] | None = None,
    ocurrido_en: datetime | None = None,
    entrada_id: UUID | None = None,
) -> EntradaAuditoria:
    """Inserta una entrada inmutable en `registro_auditoria` manteniendo la cadena `SHA-256`."""
    # Serializa el encadenamiento de la bitácora dentro de la transacción.
    conexion.execute("SELECT pg_advisory_xact_lock(hashtext('identity_access.registro_auditoria'))")
    ultimo = conexion.execute(
        "SELECT hash_actual FROM registro_auditoria ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    hash_anterior = ultimo["hash_actual"] if ultimo else HASH_GENESIS

    eid = entrada_id or uuid4()
    instante = (ocurrido_en or datetime.now(timezone.utc)).astimezone(timezone.utc)
    detalle_dict = dict(detalle or {})
    hash_actual = calcular_hash_entrada(
        entrada_id=eid,
        usuario_id=usuario_id,
        ocurrido_en=instante,
        actor=actor,
        accion=accion,
        recurso_tipo=recurso_tipo,
        recurso_id=recurso_id,
        resultado=resultado,
        motivo=motivo,
        detalle=detalle_dict,
        hash_anterior=hash_anterior,
    )
    fila = conexion.execute(
        """
        INSERT INTO registro_auditoria (
            id, usuario_id, ocurrido_en, actor, accion, recurso_tipo,
            recurso_id, resultado, motivo, detalle, hash_anterior, hash_actual
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING seq
        """,
        (
            eid, usuario_id, instante, actor, accion, recurso_tipo,
            recurso_id, resultado, motivo, Jsonb(detalle_dict), hash_anterior, hash_actual,
        ),
    ).fetchone()
    return EntradaAuditoria(
        seq=int(fila["seq"]),
        id=eid,
        usuario_id=usuario_id,
        ocurrido_en=instante,
        actor=actor,
        accion=accion,
        recurso_tipo=recurso_tipo,
        recurso_id=recurso_id,
        resultado=resultado,
        motivo=motivo,
        detalle=detalle_dict,
        hash_anterior=hash_anterior,
        hash_actual=hash_actual,
    )


def verificar_cadena(conexion: psycopg.Connection) -> bool:
    """Comprueba que ninguna fila de `registro_auditoria` fue alterada ni borrada."""
    with conexion.cursor(row_factory=dict_row) as cur:
        filas = cur.execute(
            """
            SELECT id, usuario_id, ocurrido_en, actor, accion, recurso_tipo,
                   recurso_id, resultado, motivo, detalle, hash_anterior, hash_actual
            FROM registro_auditoria
            ORDER BY seq ASC
            """
        ).fetchall()
    esperado_anterior = HASH_GENESIS
    for fila in filas:
        if fila["hash_anterior"] != esperado_anterior:
            return False
        calculado = calcular_hash_entrada(
            entrada_id=fila["id"],
            usuario_id=fila["usuario_id"],
            ocurrido_en=fila["ocurrido_en"],
            actor=fila["actor"],
            accion=fila["accion"],
            recurso_tipo=fila["recurso_tipo"],
            recurso_id=fila["recurso_id"],
            resultado=fila["resultado"],
            motivo=fila["motivo"],
            detalle=fila["detalle"],
            hash_anterior=fila["hash_anterior"],
        )
        if fila["hash_actual"] != calculado:
            return False
        esperado_anterior = fila["hash_actual"]
    return True


def historial_de_usuario(conexion: psycopg.Connection, usuario_id: UUID) -> list[dict[str, Any]]:
    """Devuelve las entradas de auditoría asociadas a `usuario_id` en orden cronológico."""
    with conexion.cursor(row_factory=dict_row) as cur:
        filas = cur.execute(
            """
            SELECT seq, id, ocurrido_en, actor, accion, recurso_tipo,
                   recurso_id, resultado, motivo, detalle, hash_actual
            FROM registro_auditoria
            WHERE usuario_id = %s
            ORDER BY seq ASC
            """,
            (usuario_id,),
        ).fetchall()
    return [
        {
            "seq": f["seq"],
            "id": str(f["id"]),
            "ocurridoEn": f["ocurrido_en"].astimezone(timezone.utc).isoformat(),
            "actor": f["actor"],
            "accion": f["accion"],
            "recursoTipo": f["recurso_tipo"],
            "recursoId": f["recurso_id"],
            "resultado": f["resultado"],
            "motivo": f["motivo"],
            "detalle": f["detalle"],
            "hashActual": f["hash_actual"],
        }
        for f in filas
    ]


def esta_bloqueada(conexion: psycopg.Connection, instancia_id: str) -> bool:
    """Indica si una instancia de servicio fue bloqueada por anomalía (ADR-0029)."""
    fila = conexion.execute(
        "SELECT 1 FROM instancia_bloqueada WHERE instancia_id = %s",
        (instancia_id,),
    ).fetchone()
    return fila is not None


def bloquear_instancia(
    conexion: psycopg.Connection,
    instancia_id: str,
    motivo: str,
    *,
    ahora: datetime | None = None,
) -> None:
    """Registra el bloqueo inmediato de una réplica sospechosa y lo audita."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conexion.execute(
        """
        INSERT INTO instancia_bloqueada (instancia_id, motivo, bloqueada_en)
        VALUES (%s, %s, %s)
        ON CONFLICT (instancia_id) DO NOTHING
        """,
        (instancia_id, motivo, instante),
    )
    registrar_evento(
        conexion,
        actor=instancia_id,
        accion="bloquear_instancia",
        recurso_tipo="instancia_servicio",
        recurso_id=instancia_id,
        resultado="alerta",
        motivo=motivo,
        ocurrido_en=instante,
    )


class DetectorDeAnomalias:
    """Detector en ventana deslizante de 60 s para emisiones de tokens efímeros (ADR-0029).

    Dispara bloqueo si:
    (a) la tasa en los últimos 60 s supera `3 × p99_base`, o
    (b) se pide un token para un `usuario_id` fuera de los `buckets` arrendados por la réplica.
    """

    def __init__(self, p99_base_por_minuto: int = 20):
        self._limite = max(1, p99_base_por_minuto * 3)
        self._ventanas: dict[str, deque[datetime]] = defaultdict(deque)

    def evaluar(
        self,
        *,
        instancia_id: str,
        usuario_id: UUID,
        buckets_arrendados: set[int] | None,
        ahora: datetime,
    ) -> str | None:
        """Devuelve el motivo de anomalía si corresponde bloquear, o `None` si es normal."""
        if buckets_arrendados is not None:
            bucket = bucket_de_usuario(usuario_id)
            if bucket not in buckets_arrendados:
                return f"bucket_no_arrendado:{bucket}"

        cola = self._ventanas[instancia_id]
        corte = ahora - VENTANA_DETECCION
        while cola and cola[0] < corte:
            cola.popleft()
        cola.append(ahora)
        if len(cola) > self._limite:
            return f"tasa_anomala:{len(cola)}_en_60s"
        return None
