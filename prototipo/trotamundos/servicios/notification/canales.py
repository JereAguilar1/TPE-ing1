"""Módulo `canales` de `notification`: el puerto hacia los canales externos (push y correo).

El canal interno es la tabla `aviso` (la bandeja de la aplicación), que se actualiza siempre. Push y
correo se entregan por un complemento; en el prototipo, `complementos/canales_simulados.py`. Lo que
se entrega no lleva datos personales: el motivo, la severidad y el viaje.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

EXTERNOS = ("push", "correo")


class CanalesExternos(Protocol):
    def enviar(self, canal: str, usuario_id: str, aviso: Mapping[str, Any]) -> None:
        """Entrega el aviso por `canal` (`push` o `correo`)."""
        ...
