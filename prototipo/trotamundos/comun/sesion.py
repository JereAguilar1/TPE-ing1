"""La sesión OIDC de las operaciones públicas (`oidc` en `comun.yaml`; ADR-0007).

`identity-access` emite el token de sesión; los servicios con operaciones públicas lo verifican
acá. En el prototipo la firma es `HS256` con `TROTAMUNDOS_JWT_SECRETO`, compartido por `.env`; en
producción cada servicio verificaría con la clave pública que publica `identity-access`.
"""

from __future__ import annotations

from uuid import UUID

import jwt

from trotamundos.comun.errores import Problema


def usuario_de_sesion(authorization: str | None, secreto: str) -> UUID:
    """El usuario de `Authorization: Bearer <token>`; `401` si falta, no valida o venció. Un
    token de invitado (ADR-0028) no es de un usuario con cuenta, y también responde `401`."""
    try:
        return UUID(sujeto_de_sesion(authorization, secreto))
    except ValueError as error:
        raise Problema(401, "No autenticado") from error


def sujeto_de_sesion(authorization: str | None, secreto: str) -> str:
    """Sujeto firmado de una sesión, incluso de invitado; no concede acceso a recursos."""
    if not authorization or not authorization.startswith("Bearer "):
        raise Problema(401, "No autenticado")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        datos = jwt.decode(token, secreto, algorithms=["HS256"])
        sujeto = datos["sub"]
        if not isinstance(sujeto, str) or not sujeto:
            raise ValueError("Falta el sujeto de la sesión")
        return sujeto
    except (jwt.InvalidTokenError, KeyError, ValueError) as error:
        raise Problema(401, "No autenticado") from error


def region_de_sesion(authorization: str | None, secreto: str) -> str | None:
    """La región primaria del usuario (`region_primaria` del token, ADR-0018 §1), o `None` si el
    token no la trae. Se llama después de `usuario_de_sesion`, que ya validó el token."""
    try:
        token = (authorization or "").removeprefix("Bearer ").strip()
        region = jwt.decode(token, secreto, algorithms=["HS256"]).get("region_primaria")
    except jwt.InvalidTokenError:
        return None
    return str(region) if region else None
