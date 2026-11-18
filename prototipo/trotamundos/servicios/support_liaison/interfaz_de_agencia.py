"""La «interfaz» que `support-liaison` expone a los complementos de agencia (ADR-0006).

Cada agencia (`E-12`) se conecta con un complemento `adaptador-agencia-*` que traduce el caso al
formato de esa agencia (una API o un correo estructurado). El mismo patrón que los adaptadores de
proveedor (`contratos/plugins/adaptador.yaml`, iteración 2 §5.7): el núcleo no conoce a ninguna.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class AgenciaNoDisponible(Exception):
    """La agencia no respondió o respondió con un error transitorio: se reintenta (ADR-0024)."""


class AdaptadorDeAgencia(Protocol):
    """Lo que un complemento de agencia hace por `support-liaison`."""

    def derivar(self, agencia_id: str, caso: Mapping[str, Any]) -> str:
        """Entrega el caso a la agencia y devuelve su referencia en la agencia (el acuse).
        Lanza `AgenciaNoDisponible` si hay que reintentar."""
        ...
