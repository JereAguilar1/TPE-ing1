"""La interfaz web mínima (paso 20, RF-09): `app_web/` servida por nginx (`docker-compose.yml`).

Las primeras pruebas leen los archivos y no necesitan nada levantado: la página llama solo a
operaciones que existen en `bff-web.yaml` (ADR-0005, *spec-driven*), no nombra tipos de segmento
(QA-15) y todo texto que usa está en su catálogo (ADR-0032). Las últimas recorren la página por
nginx contra los contenedores; sin ellos se saltean, como los escenarios del paso 17.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from tests.escenarios.contenedores import exigir_contenedores
from trotamundos.comun.contratos import contratos_por_omision
from trotamundos.comun.tipos_de_segmento import registro_por_omision

APP_WEB = Path(__file__).resolve().parents[2] / "app_web"
PUBLICO = APP_WEB / "publico"
JS = (PUBLICO / "app.js").read_text(encoding="utf-8")
HTML = (PUBLICO / "index.html").read_text(encoding="utf-8")
TEXTOS = json.loads((PUBLICO / "locales" / "es-AR.json").read_text(encoding="utf-8"))
URL = "http://localhost:18111"


def _plantilla(ruta: str) -> str:
    """`/asistente/sesiones/${estado.sesionAsistente}/mensajes` -> `/asistente/sesiones/{}/mensajes`."""
    return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{}", ruta)


def test_la_pagina_solo_llama_operaciones_de_bff_web():
    contrato = yaml.safe_load((contratos_por_omision().ruta / "openapi" / "bff-web.yaml")
                              .read_text(encoding="utf-8"))
    operaciones = {(metodo.upper(), _plantilla(ruta)) for ruta, ops in contrato["paths"].items()
                   for metodo in ops if metodo in ("get", "post", "put", "delete")}
    llamadas = {(metodo, _plantilla(ruta))
                for metodo, ruta in re.findall(r'llamar\("(\w+)", [`"]([^`"]+)[`"]', JS)}
    assert llamadas, "no se encontraron llamadas a la API en app.js"
    assert llamadas <= operaciones, f"fuera del contrato: {sorted(llamadas - operaciones)}"


def test_la_pagina_no_nombra_tipos_de_segmento():
    """Cada tramo se presenta con el descriptor de su tipo (QA-15): el código no conoce tipos."""
    literales = set(re.findall(r'"([^"\\]*)"', JS)) | set(re.findall(r"'([^'\\]*)'", JS))
    assert literales & set(registro_por_omision().tipos()) == set()


def _clave_existe(clave: str) -> bool:
    nodo = TEXTOS
    for parte in clave.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            return False
        nodo = nodo[parte]
    return True


def test_cada_texto_de_la_pagina_esta_en_el_catalogo():
    claves = set(re.findall(r'\bt\("([\w.]+)"', JS)) | set(re.findall(r'data-texto="([\w.]+)"', HTML))
    assert claves and sorted(c for c in claves if not _clave_existe(c)) == []


def test_el_catalogo_tiene_icono_y_etiquetas_para_cada_tipo_registrado():
    """Un tipo nuevo se ve con su ícono y sus filas agregando entradas al catálogo, sin tocar el
    código de la página (QA-15, elemento 2 de la guía de extensión: recursos de presentación)."""
    presentaciones = [d["presentacion"] for d in registro_por_omision().documentos()]
    assert {p["icono"] for p in presentaciones} <= set(TEXTOS["iconos"]) and "otro" in TEXTOS["iconos"]
    filas = {fila for p in presentaciones for fila in p["filas"]}
    assert sorted(filas - set(TEXTOS["campos"])) == []


# --- contra los contenedores ------------------------------------------------------------------

@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(base_url=URL, timeout=15) as cliente:
        yield cliente


def test_nginx_sirve_la_pagina_y_no_su_configuracion(cliente):
    for archivo in ("/", "/app.js", "/estilos.css", "/locales/es-AR.json"):
        assert cliente.get(archivo).status_code == 200, archivo
    assert cliente.get("/nginx.conf").status_code == 404
    assert cliente.get("/api/ia/sesiones").status_code == 403  # de identity-access, solo el POST
    assert cliente.get("/api/ia/buzones").status_code == 404   # y nada más


def test_el_recorrido_de_la_pagina_por_nginx(cliente):
    """Lo mismo que hace `app.js`: iniciar sesión, leer el panel (con `ETag`) y chatear."""
    correo = f"web-{uuid4().hex[:8]}@ejemplo.com"
    sesion = cliente.post("/api/ia/sesiones", json={
        "codigo": f"oidc:{correo}:AM", "verificadorPkce": "v" * 43, "uriRedireccion": f"{URL}/"})
    assert sesion.status_code == 201, sesion.text
    cabeceras = {"Authorization": f"Bearer {sesion.json()['tokenAcceso']}",
                 "Accept": "application/vnd.trotamundos.v1+json"}

    panel = cliente.get("/api/bff/panel", headers=cabeceras)
    assert panel.status_code == 200 and panel.json()["viajesActivos"] == []
    sin_cambios = cliente.get("/api/bff/panel",
                              headers={**cabeceras, "If-None-Match": panel.headers["ETag"]})
    assert sin_cambios.status_code == 304

    tipos = cliente.get("/api/bff/tipos-de-segmento")
    assert {"vuelo", "tren"} <= {t["tipo"] for t in tipos.json()}

    medio = {"Content-Type": "application/vnd.trotamundos.v1+json"}
    chat = cliente.post("/api/bff/asistente/sesiones", content="{}",
                        headers={**cabeceras, **medio, "Idempotency-Key": str(uuid4())})
    assert chat.status_code == 201, chat.text
    respuesta = cliente.post(f"/api/bff/asistente/sesiones/{chat.json()['id']}/mensajes",
                             content=json.dumps({"texto": "¿Cómo viene mi viaje?"}),
                             headers={**cabeceras, **medio, "Idempotency-Key": str(uuid4())})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["mensajes"] == ["No tenés viajes activos."]
