"""`preferences` contra PostgreSQL (RF-15, `preferences.yaml`); sin base, se saltean."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.preferences.servicio import Preferences

USUARIO = UUID("00000000-0000-4000-8000-0000000000f1")
SECRETO = "secreto-jwt-de-prueba-de-32-bytes!"
TIPO = {"Content-Type": "application/vnd.trotamundos.v1+json"}
PREFERENCIAS = "openapi/preferences.yaml#/components/schemas/Preferencias"


def sesion(usuario: UUID = USUARIO) -> dict[str, str]:
    token = jwt.encode({"sub": str(usuario), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       SECRETO, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def preferencias(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    servicio = Preferences(configuracion, esquema=esquema, contratos=contratos, secreto_jwt=SECRETO)
    servicio.crear_esquema()
    servicio.cliente = TestClient(servicio.app())
    servicio.bd = (dsn, esquema)
    return servicio


def _publicados(servicio) -> list[dict]:
    with conectar(*servicio.bd) as conexion:
        return conexion.execute("SELECT tipo, carga, usuario_id FROM bandeja_salida").fetchall()


def test_sin_preferencias_guardadas_devuelve_las_de_omision(preferencias, contratos):
    respuesta = preferencias.cliente.get("/preferencias", headers=sesion())
    assert respuesta.status_code == 200
    contratos.validar(PREFERENCIAS, respuesta.json())
    assert respuesta.json()["idioma"] == "es-AR" and respuesta.json()["agenciaPreferida"] is None


def test_guardar_completa_lo_que_falta_y_publica_el_evento(preferencias, contratos):
    cuerpo = {"idioma": "es-AR", "zonaHoraria": "Europe/Madrid", "region": "EU",
              "agenciaPreferida": {"id": "agencia-sur", "nombre": "Agencia del Sur"}}
    respuesta = preferencias.cliente.put("/preferencias", content=json.dumps(cuerpo),
                                         headers={**sesion(), **TIPO})
    assert respuesta.status_code == 200
    guardadas = respuesta.json()
    assert guardadas["zonaHoraria"] == "Europe/Madrid" and guardadas["canales"]["push"] is True
    assert preferencias.cliente.get("/preferencias", headers=sesion()).json() == guardadas
    (evento,) = _publicados(preferencias)
    assert evento["tipo"] == "PreferenciasActualizadas" and str(evento["usuario_id"]) == str(USUARIO)
    assert evento["carga"]["preferencias"] == guardadas

    # guardar lo mismo no vuelve a publicar
    preferencias.cliente.put("/preferencias", content=json.dumps(cuerpo), headers={**sesion(), **TIPO})
    assert len(_publicados(preferencias)) == 1


def test_un_cuerpo_invalido_es_400_y_sin_sesion_401(preferencias):
    invalido = {"idioma": "es-AR", "zonaHoraria": "UTC", "region": "MARTE"}
    assert preferencias.cliente.put("/preferencias", content=json.dumps(invalido),
                                    headers={**sesion(), **TIPO}).status_code == 400
    assert preferencias.cliente.get("/preferencias").status_code == 401
    assert _publicados(preferencias) == []


def test_cada_viajero_ve_solo_las_suyas_y_la_orden_de_borrado_las_borra(preferencias):
    otro = uuid4()
    for usuario, zona in ((USUARIO, "Europe/Madrid"), (otro, "America/Bogota")):
        preferencias.cliente.put("/preferencias", content=json.dumps(
            {"idioma": "es-AR", "zonaHoraria": zona, "region": "AM"}), headers={**sesion(usuario), **TIPO})
    assert preferencias.cliente.get("/preferencias", headers=sesion(otro)).json()["zonaHoraria"] == \
        "America/Bogota"
    assert preferencias.cliente.delete(f"/interno/usuarios/{USUARIO}").status_code == 204
    assert preferencias.cliente.get("/preferencias", headers=sesion()).json()["zonaHoraria"] == \
        "America/Argentina/Buenos_Aires"  # volvió a las de omisión
