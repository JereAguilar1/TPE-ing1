"""El elemento `bff-mobile`: arma los adaptadores HTTP y expone la API para `app-movil`
(`contratos/openapi/bff-mobile.yaml`, ADR-0005, ADR-0019).

Sin estado propio (vista C&C N1): delega en `itinerary-lectura` e `itinerary-escritura` con la
misma composición que `bff-web` (`comun.bff`) y arma el panel compacto (`resumen`).
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import FastAPI

from trotamundos.comun.bff import (
    ComposicionDeItinerarioHttp,
    EscritorDeItinerario,
    LectorDeItinerario,
)
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.servicios.bff_mobile import api, resumen


class BffMobile(ComposicionDeItinerarioHttp):
    def __init__(self, *, contratos: Contratos | None = None,
                 lector: LectorDeItinerario | None = None,
                 escritor: EscritorDeItinerario | None = None,
                 secreto_jwt: str | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        super().__init__(lector=lector, escritor=escritor)
        self._contratos = contratos or contratos_por_omision()
        self._secreto_jwt = (secreto_jwt or os.environ.get("TROTAMUNDOS_JWT_SECRETO")
                             or secrets.token_hex(32))
        self._reloj = reloj

    def leer_panel_resumen(self, usuario_id: UUID, *, min_version: int | None = None,
                           traceparent: str | None = None) -> dict[str, Any]:
        panel = self.leer_panel(usuario_id, min_version=min_version, traceparent=traceparent)
        return resumen.del_panel(panel, self._reloj())

    def app(self) -> FastAPI:
        return api.crear_app(self, self._contratos, self._secreto_jwt)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.bff_mobile.servicio:crear_app`."""
    return BffMobile().app()
