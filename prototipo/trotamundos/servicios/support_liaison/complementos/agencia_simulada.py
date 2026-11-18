"""`adaptador-agencia-simulada`: una agencia de viajes simulada para el prototipo (ADR-0036).

Recibe los casos en memoria y devuelve una referencia propia, como haría una agencia real al acusar
recibo. Como no ofrece una interfaz de estado, el viajero marca el caso como resuelto (iteración 2
§5.7). Las pruebas pueden hacerla fallar para ejercitar el reintento.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping
from uuid import uuid4

from trotamundos.servicios.support_liaison.interfaz_de_agencia import AgenciaNoDisponible


class AgenciaSimulada:
    def __init__(self) -> None:
        self.recibidos: list[tuple[str, dict[str, Any]]] = []
        self._falla = False
        self._cerrojo = threading.Lock()

    def fallar(self, falla: bool = True) -> None:
        self._falla = falla

    def derivar(self, agencia_id: str, caso: Mapping[str, Any]) -> str:
        if self._falla:
            raise AgenciaNoDisponible(agencia_id)
        with self._cerrojo:
            self.recibidos.append((agencia_id, dict(caso)))
        return f"AG-{uuid4().hex[:8].upper()}"
