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
    """{paquete: versión} del archivo de bloqueo. Cada paquete va fijado y con al menos un hash."""
    texto = (RAIZ / "requirements.txt").read_text()
    paquetes = re.findall(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.+\-]+) \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)",
                          texto, flags=re.MULTILINE)
    declaradas = re.findall(r"^[A-Za-z0-9]", texto, flags=re.MULTILINE)
    assert len(paquetes) == len(declaradas), "Hay paquetes sin versión exacta o sin hash"
    return {_nombre(nombre): version for nombre, version, _ in paquetes}


def test_cada_dependencia_directa_esta_bloqueada_con_su_version():
    directas = tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["dependencies"]
    bloqueo = _bloqueo()
    for declarada in directas:
        nombre, version = declarada.split("==")
        assert bloqueo.get(_nombre(nombre)) == version.strip(), declarada
