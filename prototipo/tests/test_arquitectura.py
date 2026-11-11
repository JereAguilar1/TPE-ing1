"""Reglas estructurales verificadas sobre el código (ADR-0036, vista de módulos N1).

Ningún servicio importa a otro servicio: solo pueden compartir `trotamundos.comun`. Así la
separación de ADR-0001 se mantiene aunque el prototipo sea un solo paquete Python.
"""

import ast
from pathlib import Path

PAQUETE = Path(__file__).resolve().parents[1] / "trotamundos"


def _modulo_absoluto(raiz: Path, archivo: Path, nodo: ast.ImportFrom) -> str:
    """Nombre absoluto del módulo de un `from ... import`, resolviendo los relativos."""
    if nodo.level == 0:
        return nodo.module or ""
    partes = ["trotamundos", *archivo.relative_to(raiz).with_suffix("").parts]
    if partes[-1] == "__init__":
        partes.pop()
    else:
        partes.pop()  # el paquete que contiene al módulo
    base = partes[: len(partes) - (nodo.level - 1)]
    return ".".join([*base, *([nodo.module] if nodo.module else [])])


def _importaciones(raiz: Path, archivo: Path) -> set[str]:
    nombres: set[str] = set()
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            nombres.update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            modulo = _modulo_absoluto(raiz, archivo, nodo)
            nombres.add(modulo)
            # `from trotamundos.servicios import otro` importa el subpaquete `otro`.
            nombres.update(f"{modulo}.{a.name}" for a in nodo.names)
    return nombres


def violaciones(raiz: Path) -> list[str]:
    """Importaciones de un servicio hacia otro, bajo `raiz` (la carpeta `trotamundos`)."""
    servicios = raiz / "servicios"
    encontradas = []
    for servicio in (p for p in servicios.iterdir() if p.is_dir() and p.name != "__pycache__"):
        for archivo in servicio.rglob("*.py"):
            for nombre in _importaciones(raiz, archivo):
                partes = nombre.split(".")
                if partes[:2] == ["trotamundos", "servicios"] and len(partes) > 2 \
                        and partes[2] != servicio.name:
                    encontradas.append(f"{archivo.relative_to(servicios)} importa {nombre}")
    return sorted(encontradas)


def test_ningun_servicio_importa_otro_servicio():
    assert violaciones(PAQUETE) == []


def test_la_regla_detecta_importaciones_absolutas_y_relativas(tmp_path):
    # Paquete de prueba: el servicio `a` importa al `b` de tres formas distintas.
    servicios = tmp_path / "servicios"
    for nombre in ("a", "b"):
        (servicios / nombre).mkdir(parents=True)
        (servicios / nombre / "__init__.py").write_text("")
    (servicios / "a" / "absoluta.py").write_text("import trotamundos.servicios.b.x\n")
    (servicios / "a" / "relativa.py").write_text("from ..b import x\n")
    (servicios / "a" / "subpaquete.py").write_text("from trotamundos.servicios import b\n")
    (servicios / "a" / "permitida.py").write_text("from trotamundos.comun import eventos\nfrom . import absoluta\n")

    encontradas = violaciones(tmp_path)

    assert sorted({v.split(" ")[0] for v in encontradas}) == [
        "a/absoluta.py", "a/relativa.py", "a/subpaquete.py",
    ]
