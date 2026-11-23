"""Conector de redes sociales simulado: guarda en memoria lo que habría publicado (E-13)."""

from __future__ import annotations

import threading
from typing import Any, Mapping
from uuid import uuid4


class RedSocialSimulada:
    def __init__(self) -> None:
        self._candado = threading.Lock()
        self.publicadas: list[tuple[str, dict[str, Any]]] = []

    def publicar(self, red: str, resumen: Mapping[str, Any]) -> str:
        with self._candado:
            self.publicadas.append((red, dict(resumen)))
        return f"{red}:{uuid4().hex[:12]}"
