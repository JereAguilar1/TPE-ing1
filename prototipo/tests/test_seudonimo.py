"""El seudónimo analítico compartido por `identity-access` y `event-pipeline` (ADR-0030)."""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from trotamundos.comun import seudonimo
from trotamundos.comun.seudonimo import seudonimo_analitico

USUARIO = UUID("6f1c2a52-6d0e-4a4c-9a55-3c1c4b1f7d10")


def test_es_determinista_y_no_depende_de_como_se_escribe_el_uuid():
    assert seudonimo_analitico(USUARIO, "clave") == seudonimo_analitico(str(USUARIO).upper(), "clave")
    assert re.fullmatch(r"seu_[0-9a-f]{24}", seudonimo_analitico(USUARIO, "clave"))


def test_sin_la_clave_no_se_puede_recalcular_a_partir_del_usuario():
    assert seudonimo_analitico(USUARIO, "una") != seudonimo_analitico(USUARIO, "otra")


def test_sin_secreto_configurado_no_usa_una_clave_vacia(monkeypatch):
    monkeypatch.setenv("TROTAMUNDOS_SECRETO_SEUDONIMO", "")
    seudonimo._clave_por_omision.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="TROTAMUNDOS_SECRETO_SEUDONIMO"):
            seudonimo_analitico(USUARIO)
    finally:
        seudonimo._clave_por_omision.cache_clear()
