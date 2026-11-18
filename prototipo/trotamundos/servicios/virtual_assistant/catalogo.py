"""Lectura de los catálogos por idioma del asistente (`catalogos/<idioma>/`, ADR-0032 y ADR-0037).

Los catálogos son recursos estáticos: `patrones.yaml` (lo usa solo el intérprete) y `mensajes.yaml`
(todo lo que el asistente le dice al viajero). Este módulo los carga y completa los marcadores de los
mensajes: el subconjunto de ICU MessageFormat que usa el catálogo, argumentos simples (`{nombre}`) y
plurales (`{n, plural, one {# reserva} other {# reservas}}`). Las fechas y horas se formatean en
la zona horaria del lugar, con los nombres de días del catálogo.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import yaml

CARPETA = Path(__file__).resolve().parent / "catalogos"
IDIOMA_POR_OMISION = "es"
_MARCADOR = re.compile(r"\{(\w+)\}")
_PLURAL = re.compile(r"\{(\w+), plural, one \{([^{}]*)\} other \{([^{}]*)\}\}")


@lru_cache(maxsize=None)
def _leer(idioma: str, nombre: str) -> dict[str, Any]:
    ruta = CARPETA / idioma / f"{nombre}.yaml"
    if not ruta.is_file():
        ruta = CARPETA / IDIOMA_POR_OMISION / f"{nombre}.yaml"
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def patrones(idioma: str = IDIOMA_POR_OMISION) -> dict[str, Any]:
    """El catálogo de patrones de cada intención y de las entidades."""
    return _leer(idioma, "patrones")


def _completar(plantilla: str, argumentos: dict[str, Any]) -> str:
    def plural(m: re.Match) -> str:
        cantidad = argumentos[m.group(1)]
        return (m.group(2) if cantidad == 1 else m.group(3)).replace("#", str(cantidad))

    return _MARCADOR.sub(lambda m: str(argumentos[m.group(1)]), _PLURAL.sub(plural, plantilla))


class Mensajes:
    """El catálogo de mensajes de un idioma."""

    def __init__(self, idioma: str = IDIOMA_POR_OMISION):
        self.idioma = idioma
        self._catalogo = _leer(idioma, "mensajes")

    def texto(self, clave: str, **argumentos: Any) -> str:
        """El mensaje `clave` (o `grupo.clave`) con sus marcadores completos."""
        valor: Any = self._catalogo
        for parte in clave.split("."):
            valor = valor[parte]
        return _completar(valor, argumentos)

    def tiene(self, clave: str) -> bool:
        valor: Any = self._catalogo
        for parte in clave.split("."):
            if not isinstance(valor, dict) or parte not in valor:
                return False
            valor = valor[parte]
        return True

    def lista(self, elementos: Iterable[str]) -> str:
        return self._catalogo["separador_de_lista"].join(elementos)

    def tipo(self, tipo: str) -> str:
        """Cómo se nombra un tipo de tramo; uno que el catálogo no conoce es una «reserva»."""
        tipos = self._catalogo["tipos"]
        return tipos.get(tipo, tipos["otro"])

    def comienzo(self, tipo: str) -> str:
        """El verbo con que empieza un tramo de ese tipo («sale», «tiene el ingreso»)."""
        verbos = self._catalogo["comienzo_de_tramo"]
        return verbos.get(tipo, verbos["otro"])

    @staticmethod
    def ciudad(zona: str) -> str:
        """La ciudad de una zona IANA, como la conoce el viajero: `America/Argentina/Buenos_Aires`
        es «Buenos Aires»."""
        return zona.rsplit("/", 1)[-1].replace("_", " ")

    def fuente(self, fuente: str) -> str:
        return self._catalogo["fuentes"].get(fuente, fuente)

    # --- fechas y horas, en la zona del lugar ------------------------------------------------

    def _local(self, instante: datetime, zona: str) -> datetime:
        return instante.astimezone(ZoneInfo(zona))

    def fecha(self, instante: datetime, zona: str) -> str:
        local = self._local(instante, zona)
        return _completar(self._catalogo["fecha"], {
            "dia": self._catalogo["dias"][local.weekday()], "d": local.day, "m": local.month})

    def hora(self, instante: datetime, zona: str) -> str:
        return self._local(instante, zona).strftime("%H:%M")

    def fecha_y_hora(self, instante: datetime, zona: str) -> str:
        local = self._local(instante, zona)
        return _completar(self._catalogo["fecha_y_hora"], {
            "dia": self._catalogo["dias"][local.weekday()], "d": local.day, "m": local.month,
            "hora": local.strftime("%H:%M")})
