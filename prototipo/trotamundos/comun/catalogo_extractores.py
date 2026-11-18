"""Catálogo declarativo común, sin importar complementos (ADR-0006, RF-04)."""
from pathlib import Path
import yaml
from trotamundos.comun.contratos import contratos_por_omision


def entradas() -> list[dict]:
    datos = yaml.safe_load(Path(__file__).with_suffix(".yaml").read_text(encoding="utf-8"))
    contratos = contratos_por_omision()
    for entrada in datos:
        contratos.validar("plugins/extractor.yaml#/manifiesto", entrada["manifiesto"])
    return datos


def remitentes() -> list[dict[str, str]]:
    return [{"patron": patron, "extractorId": entrada["manifiesto"]["id"]}
            for entrada in entradas()
            for patron in entrada["manifiesto"]["remitentesQueReconoce"]]
