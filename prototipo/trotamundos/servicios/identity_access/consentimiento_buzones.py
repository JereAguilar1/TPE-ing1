"""Módulo `consentimiento-buzones` (RF-01, ADR-0007, ADR-0029, ADR-0035).

Gestiona el ciclo de vida de los buzones (`Solicitado → Activo → RequiereReautorizacion →
Revocado`), la emisión controlada de tokens efímeros hacia `mail-ingest` y el barrido de
revocación regional en bloque.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from trotamundos.servicios.identity_access import auditoria_y_revocacion as auditoria
from trotamundos.servicios.identity_access import custodia_boveda as boveda

DDL = (
    """
    CREATE TABLE IF NOT EXISTS buzon (
        id             uuid        PRIMARY KEY,
        usuario_id     uuid        NOT NULL,
        via            text        NOT NULL,
        proveedor      text,
        direccion      text,
        estado         text        NOT NULL,
        alias_reenvio  text,
        region         text        NOT NULL,
        actualizado_en timestamptz NOT NULL
    );
    CREATE INDEX IF NOT EXISTS buzon_por_usuario ON buzon (usuario_id);
    CREATE INDEX IF NOT EXISTS buzon_por_region_estado ON buzon (region, estado);
    """,
)


class BuzonNoEncontrado(Exception):
    """El buzón no existe o no pertenece al usuario."""


class ConflictoDeBuzon(Exception):
    """El estado o vía del buzón no admite la transición solicitada."""


class SolicitudBuzonInvalida(Exception):
    """Faltan datos obligatorios para la vía elegida (p. ej. `credencialDelegada`)."""


class InstanciaBloqueada(Exception):
    """La instancia solicitante fue bloqueada por anomalía o ya estaba revocada (403)."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _serializar_buzon(fila: dict[str, Any]) -> dict[str, Any]:
    salida: dict[str, Any] = {
        "id": str(fila["id"]),
        "via": fila["via"],
        "estado": fila["estado"],
    }
    if fila.get("direccion"):
        salida["direccion"] = fila["direccion"]
    return salida


def listar_buzones(conexion: psycopg.Connection, usuario_id: UUID) -> list[dict[str, Any]]:
    with conexion.cursor(row_factory=dict_row) as cur:
        filas = cur.execute(
            """
            SELECT id, via, estado, direccion
            FROM buzon
            WHERE usuario_id = %s
            ORDER BY actualizado_en ASC, id ASC
            """,
            (usuario_id,),
        ).fetchall()
    return [_serializar_buzon(f) for f in filas]


def conectar_buzon(
    conexion: psycopg.Connection,
    kms: boveda.KmsLocal,
    *,
    usuario_id: UUID,
    region: str,
    via: str,
    proveedor: str | None = None,
    credencial_delegada: str | None = None,
    direccion: str | None = None,
    buzon_id: UUID | None = None,
    ahora: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inicia la conexión de un buzón según `via` (`oauth`, `reenvio`, `imapDelegado`).

    Devuelve `(respuesta_api, cambios_de_estado_para_eventos)`.
    """
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    bid = buzon_id or uuid4()
    eventos: list[dict[str, Any]] = []

    if via == "imapDelegado":
        if not credencial_delegada or not credencial_delegada.strip():
            raise SolicitudBuzonInvalida("imapDelegado requiere credencialDelegada")
        boveda.guardar_secreto(
            conexion,
            kms,
            usuario_id=usuario_id,
            region=region,
            buzon_id=bid,
            proposito="imap_delegado",
            secreto_en_claro=credencial_delegada,
            actor=str(usuario_id),
            ahora=instante,
        )
        estado = "Activo"
        alias_reenvio = None
        url_autorizacion = None
        eventos.append(
            {
                "buzonId": str(bid),
                "estadoAnterior": "Solicitado",
                "estadoNuevo": "Activo",
                "motivo": "otorgado",
            }
        )
    elif via == "reenvio":
        token = secrets.token_urlsafe(12)
        alias_reenvio = f"viajes+{token}@ingesta.trotamundos.app"
        estado = "Activo"
        url_autorizacion = None
        eventos.append(
            {
                "buzonId": str(bid),
                "estadoAnterior": "Solicitado",
                "estadoNuevo": "Activo",
                "motivo": "otorgado",
            }
        )
    elif via == "oauth":
        estado = "Solicitado"
        alias_reenvio = None
        prov = proveedor or "generico"
        url_autorizacion = f"https://oauth.simulado.trotamundos.app/autorizar?buzon={bid}&proveedor={prov}"
    else:
        raise SolicitudBuzonInvalida(f"Vía de buzón no soportada: {via}")

    conexion.execute(
        """
        INSERT INTO buzon (
            id, usuario_id, via, proveedor, direccion, estado, alias_reenvio, region, actualizado_en
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (bid, usuario_id, via, proveedor, direccion, estado, alias_reenvio, region, instante),
    )
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=str(usuario_id),
        accion="conectar_buzon",
        recurso_tipo="buzon",
        recurso_id=str(bid),
        resultado="permitido",
        detalle={"via": via, "estado": estado},
        ocurrido_en=instante,
    )

    respuesta: dict[str, Any] = {"id": str(bid), "via": via, "estado": estado}
    if direccion:
        respuesta["direccion"] = direccion
    if url_autorizacion:
        respuesta["urlAutorizacion"] = url_autorizacion
    if alias_reenvio:
        respuesta["aliasReenvio"] = alias_reenvio
    return respuesta, eventos


def autorizar_buzon_oauth(
    conexion: psycopg.Connection,
    kms: boveda.KmsLocal,
    *,
    usuario_id: UUID,
    buzon_id: UUID,
    codigo: str,
    direccion: str | None = None,
    ahora: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Completa el consentimiento OAuth (`Solicitado`/`RequiereReautorizacion` → `Activo`)."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not codigo or codigo.startswith("invalido"):
        raise SolicitudBuzonInvalida("Código de consentimiento OAuth inválido")

    with conexion.cursor(row_factory=dict_row) as cur:
        fila = cur.execute(
            "SELECT id, via, estado, direccion, region FROM buzon WHERE id = %s AND usuario_id = %s",
            (buzon_id, usuario_id),
        ).fetchone()
    if fila is None:
        raise BuzonNoEncontrado()
    if fila["via"] != "oauth":
        raise ConflictoDeBuzon("Solo un buzón OAuth admite confirmación de consentimiento")
    if fila["estado"] not in {"Solicitado", "RequiereReautorizacion"}:
        raise ConflictoDeBuzon(f"El buzón está en estado {fila['estado']}")

    refresh_token = f"oauth_rt_{buzon_id}_{codigo}"
    boveda.guardar_secreto(
        conexion,
        kms,
        usuario_id=usuario_id,
        region=fila["region"],
        buzon_id=buzon_id,
        proposito="oauth_refresh_token",
        secreto_en_claro=refresh_token,
        actor=str(usuario_id),
        ahora=instante,
    )
    nueva_direccion = direccion or fila["direccion"]
    conexion.execute(
        """
        UPDATE buzon SET estado = 'Activo', direccion = %s, actualizado_en = %s
        WHERE id = %s AND usuario_id = %s
        """,
        (nueva_direccion, instante, buzon_id, usuario_id),
    )
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=str(usuario_id),
        accion="autorizar_buzon",
        recurso_tipo="buzon",
        recurso_id=str(buzon_id),
        resultado="permitido",
        detalle={"estadoAnterior": fila["estado"], "estadoNuevo": "Activo"},
        ocurrido_en=instante,
    )
    respuesta = _serializar_buzon(
        {"id": buzon_id, "via": fila["via"], "estado": "Activo", "direccion": nueva_direccion}
    )
    eventos = [
        {
            "buzonId": str(buzon_id),
            "estadoAnterior": fila["estado"],
            "estadoNuevo": "Activo",
            "motivo": "otorgado",
        }
    ]
    return respuesta, eventos


def desconectar_buzon(
    conexion: psycopg.Connection,
    *,
    usuario_id: UUID,
    buzon_id: UUID,
    ahora: datetime | None = None,
) -> list[dict[str, Any]]:
    """Revoca el consentimiento del buzón, destruye su secreto y pasa a `Revocado`."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fila = conexion.execute(
        "SELECT estado FROM buzon WHERE id = %s AND usuario_id = %s",
        (buzon_id, usuario_id),
    ).fetchone()
    if fila is None:
        raise BuzonNoEncontrado()
    estado_anterior = str(fila["estado"])
    if estado_anterior == "Revocado":
        return []

    boveda.destruir_secreto(
        conexion,
        usuario_id=usuario_id,
        buzon_id=buzon_id,
        actor=str(usuario_id),
        ahora=instante,
    )
    conexion.execute(
        "UPDATE buzon SET estado = 'Revocado', actualizado_en = %s WHERE id = %s",
        (instante, buzon_id),
    )
    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=str(usuario_id),
        accion="desconectar_buzon",
        recurso_tipo="buzon",
        recurso_id=str(buzon_id),
        resultado="permitido",
        detalle={"estadoAnterior": estado_anterior, "estadoNuevo": "Revocado"},
        ocurrido_en=instante,
    )
    return [
        {
            "buzonId": str(buzon_id),
            "estadoAnterior": estado_anterior,
            "estadoNuevo": "Revocado",
            "motivo": "desconectadoPorUsuario",
        }
    ]


def emitir_token_efimero(
    conexion: psycopg.Connection,
    kms: boveda.KmsLocal,
    detector: auditoria.DetectorDeAnomalias,
    *,
    buzon_id: UUID,
    instancia_id: str,
    buckets_arrendados: set[int] | None = None,
    ahora: datetime | None = None,
) -> dict[str, str]:
    """Entrega un token de acceso efímero a `mail-ingest` validando estado y anomalías."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if auditoria.esta_bloqueada(conexion, instancia_id):
        raise InstanciaBloqueada("instancia_bloqueada")

    fila = conexion.execute(
        "SELECT usuario_id, estado FROM buzon WHERE id = %s",
        (buzon_id,),
    ).fetchone()
    if fila is None:
        raise BuzonNoEncontrado()
    usuario_id, estado = fila["usuario_id"], fila["estado"]

    anomalia = detector.evaluar(
        instancia_id=instancia_id,
        usuario_id=usuario_id,
        buckets_arrendados=buckets_arrendados,
        ahora=instante,
    )
    if anomalia is not None:
        auditoria.bloquear_instancia(conexion, instancia_id, anomalia, ahora=instante)
        raise InstanciaBloqueada(anomalia)

    if estado != "Activo":
        raise ConflictoDeBuzon(f"El buzón está en estado {estado}")

    token, expira_en = boveda.emitir_token_efimero(
        conexion,
        kms,
        usuario_id=usuario_id,
        buzon_id=buzon_id,
        actor=instancia_id,
        ahora=instante,
    )
    return {"token": token, "expiraEn": expira_en.isoformat()}


def revocar_region_en_bloque(
    conexion: psycopg.Connection,
    kms: boveda.KmsLocal,
    *,
    region: str,
    version_kek: int,
    actor: str,
    ahora: datetime | None = None,
) -> list[tuple[UUID, dict[str, Any]]]:
    """Ejecuta la revocación regional en dos fases de ADR-0029 (< 15 min).

    1. Inhabilita `KEK_region` `v{version_kek}` al instante (y rota si era la vigente).
    2. Pasa a `RequiereReautorizacion` los buzones `Activo` de la región que guardan un token o
       credencial en la bóveda. Los de `reenvio` no guardan ninguno: siguen `Activo`. Un buzón
       `imapDelegado` se reconecta dándolo de baja y conectándolo con una credencial nueva.
    """
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    boveda.revocar_version_kek(
        conexion, kms, region, version_kek, actor=actor, ahora=instante
    )

    filas = conexion.execute(
        """
        SELECT id, usuario_id FROM buzon
        WHERE region = %s AND estado = 'Activo' AND via <> 'reenvio'
        """,
        (region,),
    ).fetchall()
    eventos: list[tuple[UUID, dict[str, Any]]] = []
    for fila in filas:
        buzon_id, usuario_id = fila["id"], fila["usuario_id"]
        conexion.execute(
            "UPDATE buzon SET estado = 'RequiereReautorizacion', actualizado_en = %s WHERE id = %s",
            (instante, buzon_id),
        )
        eventos.append(
            (
                usuario_id,
                {
                    "buzonId": str(buzon_id),
                    "estadoAnterior": "Activo",
                    "estadoNuevo": "RequiereReautorizacion",
                    "motivo": "revocadoPorProveedor",
                },
            )
        )

    auditoria.registrar_evento(
        conexion,
        actor=actor,
        accion="revocar_region_en_bloque",
        recurso_tipo="kms_region",
        recurso_id=region,
        resultado="permitido",
        detalle={"versionKek": version_kek, "buzonesAfectados": len(eventos)},
        ocurrido_en=instante,
    )
    return eventos
