"""La documentación del prototipo no se desactualiza sin que falle una prueba (QA-16).

Lo que se revisaba a mano en el cierre (paso 21) y se encontró desactualizado varias veces: la
numeración del plan (`README.md`), el árbol de `docs/estructura.md`, la matriz de
`docs/matriz-codigo-adr.md` y los enlaces entre el README del repositorio, la wiki, la
documentación del prototipo y el guion. No revisa la redacción: solo
lo que se puede comparar con el código.
"""

from __future__ import annotations

import re
from pathlib import Path

PROTOTIPO = Path(__file__).resolve().parents[1]
RAIZ = PROTOTIPO.parent
README = PROTOTIPO / "README.md"
ESTRUCTURA = PROTOTIPO / "docs" / "estructura.md"
MATRIZ = PROTOTIPO / "docs" / "matriz-codigo-adr.md"
CODIGO = PROTOTIPO / "trotamundos"
# Los documentos que mantiene el grupo (los de la 1ra entrega no se editan: AGENTS.md).
DOCUMENTOS = [RAIZ / "README.md", RAIZ / "docs" / "Home.md", README,
              PROTOTIPO / "demo" / "guion.md", *sorted((PROTOTIPO / "docs").glob("*.md"))]


def _seccion(texto: str, desde: str, hasta: str) -> str:
    inicio = texto.index(desde)
    return texto[inicio:texto.index(hasta, inicio)]


def _modulos() -> list[Path]:
    """Los archivos de código de `trotamundos/`, sin los complementos ni los catálogos."""
    return sorted(p for p in CODIGO.rglob("*.py")
                  if p.name != "__init__.py" and "complementos" not in p.parts
                  and "__pycache__" not in p.parts)


def test_los_pasos_del_plan_estan_numerados_en_orden():
    plan = _seccion(README.read_text(encoding="utf-8"), "## Plan de construcción", "### Recorte")
    numeros = [int(n) for n in re.findall(r"^\| (\d+) \|", plan, re.M)]
    assert numeros == list(range(1, len(numeros) + 1))


def test_el_arbol_de_estructura_nombra_cada_archivo_de_cada_servicio():
    arbol = _seccion(ESTRUCTURA.read_text(encoding="utf-8"), "```", "## Reglas verificadas")
    lineas = arbol.splitlines()
    servicios = sorted(d.name for d in (CODIGO / "servicios").iterdir()
                       if d.is_dir() and d.name != "__pycache__")
    faltan = []
    for servicio in servicios:
        inicio = next(i for i, l in enumerate(lineas) if f"── {servicio}/" in l)
        fin = next((i for i in range(inicio + 1, len(lineas))
                    if any(f"── {otro}/" in lineas[i] for otro in servicios)), len(lineas))
        bloque = "\n".join(lineas[inicio:fin])
        for archivo in sorted((CODIGO / "servicios" / servicio).iterdir()):
            nombre = archivo.name + ("/" if archivo.is_dir() else "")
            if archivo.name not in ("__init__.py", "__pycache__") and nombre not in bloque:
                faltan.append(f"{servicio}/{nombre}")
    for archivo in sorted((CODIGO / "comun").glob("*.py")):
        if archivo.name != "__init__.py" and archivo.name not in arbol:
            faltan.append(f"comun/{archivo.name}")
    assert faltan == []


def test_la_matriz_nombra_cada_modulo_y_cada_prueba():
    matriz = MATRIZ.read_text(encoding="utf-8")
    sin_matriz = [str(p.relative_to(PROTOTIPO)) for p in _modulos()
                  if p.name not in matriz and f"{p.parent.name}/" not in matriz]
    sin_matriz += [str(p.relative_to(PROTOTIPO)) for p in sorted(PROTOTIPO.glob("tests/**/test_*.py"))
                   if p.name not in matriz]
    assert sin_matriz == []


def test_lo_que_nombra_la_matriz_existe():
    matriz = MATRIZ.read_text(encoding="utf-8")
    existentes = [p for p in RAIZ.rglob("*")
                  if not {".git", ".venv", "__pycache__", "node_modules"} & set(p.parts)]
    nombres = {p.name for p in existentes}
    rutas = {p.as_posix() for p in existentes}
    inexistentes = []
    for referencia in re.findall(r"`([^`]+)`", matriz):
        for parte in (x.strip().rstrip("/") for x in referencia.split(",")):
            if not re.search(r"\.(py|ya?ml|json|html|js|css|conf|sql|md|sh)$", parte):
                continue
            if "/" in parte:
                encontrada = any(r.endswith("/" + parte) for r in rutas)
            else:
                encontrada = parte in nombres
            if not encontrada:
                inexistentes.append(parte)
    assert inexistentes == []


def _ancla(titulo: str) -> str:
    """El identificador que GitHub le da a un título."""
    return re.sub(r"[^\w\- ]", "", titulo.strip().lower()).replace(" ", "-")


def test_los_enlaces_entre_documentos_llevan_a_archivos_y_secciones_que_existen():
    rotos = []
    for documento in DOCUMENTOS:
        for destino in re.findall(r"\]\(([^)\s]+)\)", documento.read_text(encoding="utf-8")):
            if destino.startswith(("http://", "https://", "mailto:")):
                continue
            ruta, _, ancla = destino.partition("#")
            archivo = (documento.parent / ruta).resolve() if ruta else documento
            if not archivo.exists():
                rotos.append(f"{documento.relative_to(RAIZ)} → {destino}")
            elif ancla and archivo.suffix == ".md":
                titulos = re.findall(r"^#+ (.+)$", archivo.read_text(encoding="utf-8"), re.M)
                if ancla not in {_ancla(t) for t in titulos}:
                    rotos.append(f"{documento.relative_to(RAIZ)} → {destino}")
    assert rotos == []
