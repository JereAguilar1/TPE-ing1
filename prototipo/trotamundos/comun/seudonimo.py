"""El seudónimo analítico de un usuario (ADR-0016, ADR-0030).

`identity-access` lo guarda en `mapa_seudonimo_usuario` y lo publica en `CuentaSuprimida`;
`event-pipeline` lo usa en lugar de `usuarioId` en todo el plano analítico. Los dos tienen que
calcular el mismo, o la supresión de la fase 2 no encuentra las filas del usuario.

Es un HMAC-SHA256 del `usuario_id` con `TROTAMUNDOS_SECRETO_SEUDONIMO` (de `.env`, nunca del
código): sin el secreto, conocer el `usuario_id` no alcanza para encontrar sus filas analíticas.
Si falta, no se calcula con una clave vacía: el servicio falla al primer uso.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
from uuid import UUID

from trotamundos.comun.config import _variable

PREFIJO = "seu_"
_LARGO = 24  # caracteres hexadecimales


@functools.lru_cache(maxsize=1)
def _clave_por_omision() -> str:
    clave = _variable("TROTAMUNDOS_SECRETO_SEUDONIMO")
    if not clave:
        raise RuntimeError("Falta TROTAMUNDOS_SECRETO_SEUDONIMO: correr `make infra-arriba`, que "
                           "lo agrega a prototipo/.env")
    return clave


def seudonimo_analitico(usuario_id: UUID | str, clave: str | None = None) -> str:
    """`seu_` y 24 caracteres hexadecimales, deterministas para el mismo usuario y la misma clave."""
    clave = clave if clave is not None else _clave_por_omision()
    resumen = hmac.new(clave.encode("utf-8"), f"analitica:{UUID(str(usuario_id))}".encode("utf-8"),
                       hashlib.sha256).hexdigest()
    return f"{PREFIJO}{resumen[:_LARGO]}"
