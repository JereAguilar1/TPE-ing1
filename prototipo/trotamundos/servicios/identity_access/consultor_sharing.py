"""Módulo `consultor_sharing` de `identity-access`: los atributos de una compartición, leídos de
`sharing` (`GET /interno/comparticiones/{cid}`, ADR-0028).

Implementa los dos puertos que hasta el paso 13 arrancaban cerrados: `ConsultorDeDesignados` (el
código de invitado) y `ConsultorDeRecursos` (la evaluación ABAC). Si `sharing` no responde, se
deniega: nunca se abre por una falla (*fail-closed*).
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

import httpx

from trotamundos.servicios.identity_access.motor_autorizacion_abac import AtributosRecurso

_registro = logging.getLogger(__name__)


class ConsultorDeSharingHttp:
    def __init__(self, url_base: str, region: str, timeout_s: float = 3.0,
                 cliente: httpx.Client | None = None):
        self._url, self._region = url_base.rstrip("/"), region
        self._timeout, self._http = timeout_s, cliente or httpx

    def _comparticion(self, comparticion_id: UUID) -> dict | None:
        try:
            respuesta = self._http.get(f"{self._url}/interno/comparticiones/{comparticion_id}",
                                       timeout=self._timeout)
        except httpx.HTTPError:
            _registro.warning("sharing no responde: se deniega (fail-closed)")
            return None
        return respuesta.json() if respuesta.status_code == 200 else None

    def esta_designado(self, comparticion_id: UUID, correo: str) -> tuple[bool, str]:
        datos = self._comparticion(comparticion_id)
        designado = (datos is not None and datos["estado"] == "Activa"
                     and correo.strip().lower() in datos["designados"])
        return designado, self._region

    def atributos(self, tipo: str, recurso_id: UUID) -> AtributosRecurso | None:
        if tipo != "comparticion":
            return None
        datos = self._comparticion(recurso_id)
        if datos is None:
            return None
        return AtributosRecurso(
            propietario_id=UUID(datos["propietarioId"]), estado=datos["estado"],
            designados=frozenset(datos["designados"]),
            expira_en=datetime.fromisoformat(datos["expiraEn"].replace("Z", "+00:00")))
