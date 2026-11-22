"""Canales push y correo simulados: registran en memoria lo que se habría entregado."""

from __future__ import annotations

import logging
import threading
from typing import Any, Mapping

_registro = logging.getLogger(__name__)


class CanalesSimulados:
    def __init__(self) -> None:
        self._candado = threading.Lock()
        self.entregados: list[tuple[str, str, dict[str, Any]]] = []

    def enviar(self, canal: str, usuario_id: str, aviso: Mapping[str, Any]) -> None:
        with self._candado:
            self.entregados.append((canal, str(usuario_id), dict(aviso)))
        _registro.info("Aviso %s por %s", aviso.get("avisoId"), canal)
