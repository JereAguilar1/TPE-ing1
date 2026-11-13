"""El archivo de bloqueo (`requirements.txt`) coincide con `pyproject.toml`.

`pyproject.toml` declara las dependencias directas con su versión; `requirements.txt` fija además
las transitivas, y es lo que instala la imagen (Dockerfile). Si alguien cambia una versión en un
lado y no en el otro, esta prueba falla.
"""

import re
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _nombre(texto: str) -> str:
    """Nombre normalizado de un paquete (PEP 503), sin extras."""
    return re.sub(r"[-_.]+", "-", texto.split("[")[0]).lower()


def _bloqueo() -> dict[str, str]:
    lineas = [l.strip() for l in (RAIZ / "requirements.txt").read_text().splitlines()]
    fijadas = [l for l in lineas if l and not l.startswith("#")]
    for linea in fijadas:
        assert re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.+\-]+", linea), f"No está fijada: {linea}"
    return {_nombre(l.split("==")[0]): l.split("==")[1] for l in fijadas}


def test_cada_dependencia_directa_esta_bloqueada_con_su_version():
    directas = tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["dependencies"]
    bloqueo = _bloqueo()
    for declarada in directas:
        nombre, version = declarada.split("==")
        assert bloqueo.get(_nombre(nombre)) == version.strip(), declarada
