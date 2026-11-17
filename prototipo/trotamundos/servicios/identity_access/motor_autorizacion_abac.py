"""Módulo `motor-autorizacion-abac` (ADR-0028, QA-12).

Evalúa políticas declarativas por atributos sobre `(sujeto, acción, recurso)` y emite vales JWS
de corta vida (`TTL 60 s`) ligados al recurso específico.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

import jwt
import psycopg

from trotamundos.servicios.identity_access import auditoria_y_revocacion as auditoria

TTL_VALE = timedelta(seconds=60)


@dataclass(frozen=True)
class AtributosRecurso:
    propietario_id: UUID
    estado: str = "Activa"
    designados: frozenset[str] = frozenset()
    expira_en: datetime | None = None


class ConsultorDeRecursos(Protocol):
    def atributos(self, tipo: str, recurso_id: UUID) -> AtributosRecurso | None: ...


class ConsultorDeRecursosNulo:
    """Fail-closed por omisión cuando el servicio dueño del recurso no está conectado."""

    def atributos(self, tipo: str, recurso_id: UUID) -> AtributosRecurso | None:
        return None


def evaluar(
    conexion: psycopg.Connection,
    consultor: ConsultorDeRecursos,
    *,
    sujeto: Mapping[str, Any],
    accion: str,
    recurso: Mapping[str, Any],
    secreto_vale: str,
    actor_servicio: str,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Evalúa la política ABAC y, si permite, emite un vale JWS de 60 s ligado al recurso."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    usuario_id = UUID(str(sujeto["usuarioId"]))
    correo = str(sujeto.get("correoVerificado", "")).strip().lower()
    alcances = set(sujeto.get("alcances") or [])
    recurso_tipo = str(recurso["tipo"])
    recurso_id = UUID(str(recurso["id"]))

    atributos = consultor.atributos(recurso_tipo, recurso_id)
    permitido = False
    motivo = "recurso_desconocido"

    if atributos is not None:
        if atributos.propietario_id == usuario_id:
            permitido = True
            motivo = "propietario"
        elif recurso_tipo == "comparticion" and accion == "leer":
            vigente = atributos.expira_en is None or atributos.expira_en > instante
            if atributos.estado != "Activa" or not vigente:
                motivo = "comparticion_inactiva_o_vencida"
            elif f"lectura:comparticion:{recurso_id}" in alcances:
                permitido = True
                motivo = "alcance_invitado"
            elif correo and correo in atributos.designados:
                permitido = True
                motivo = "designado"
            else:
                motivo = "no_designado"
        else:
            motivo = "sin_permiso"

    auditoria.registrar_evento(
        conexion,
        usuario_id=usuario_id,
        actor=actor_servicio,
        accion=f"abac:{accion}",
        recurso_tipo=recurso_tipo,
        recurso_id=str(recurso_id),
        resultado="permitido" if permitido else "denegado",
        motivo=motivo,
        ocurrido_en=instante,
    )

    if not permitido:
        return {"decision": "denegar"}

    expira_en = instante + TTL_VALE
    vale = jwt.encode(
        {
            "jti": str(uuid4()),
            "sub": str(usuario_id),
            "accion": accion,
            "recurso_tipo": recurso_tipo,
            "recurso_id": str(recurso_id),
            "iat": int(instante.timestamp()),
            "exp": int(expira_en.timestamp()),
        },
        secreto_vale,
        algorithm="HS256",
    )
    return {"decision": "permitir", "vale": vale}


def verificar_vale(
    vale: str,
    secreto_vale: str,
    *,
    recurso_tipo: str,
    recurso_id: UUID,
    accion: str,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Verifica firma, vigencia y ligadura al recurso de un vale JWS emitido por `identity-access`."""
    instante = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    datos = jwt.decode(
        vale,
        secreto_vale,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    if int(datos["exp"]) < int(instante.timestamp()):
        raise jwt.ExpiredSignatureError("Vale expirado")
    if (
        datos.get("recurso_tipo") != recurso_tipo
        or datos.get("recurso_id") != str(recurso_id)
        or datos.get("accion") != accion
    ):
        raise jwt.InvalidTokenError("El vale no corresponde al recurso o acción")
    return datos
