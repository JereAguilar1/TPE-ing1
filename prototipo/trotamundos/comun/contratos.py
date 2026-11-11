"""Acceso en ejecución a los contratos de `contratos/` (ADR-0009, ADR-0017, ADR-0036).

El código del prototipo no redefine esquemas: los carga de los archivos OpenAPI, AsyncAPI y de
tipos de segmento, y valida contra ellos. Así un cambio en un contrato se refleja de inmediato en
las validaciones, y el código no puede divergir en silencio de la especificación.

Las referencias se escriben relativas a la carpeta `contratos/`, con el puntero JSON del esquema:

    contratos.validar("openapi/comun.yaml#/components/schemas/Reserva", reserva)

Todos los esquemas se evalúan con JSON Schema 2020-12, que es el dialecto de OpenAPI 3.1. Los
esquemas del contrato AsyncAPI usan solo construcciones que significan lo mismo en ese dialecto y
en el de AsyncAPI 3.0 (superconjunto de Draft 07).
"""

from __future__ import annotations

import copy
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

import yaml
from jsonschema import Draft202012Validator
from jsonschema_specifications import REGISTRY as ESPECIFICACIONES
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from trotamundos.comun.config import Configuracion

# El metaesquema de descriptores declara este $id; se sirve desde el archivo local.
_PREFIJO_ID_PUBLICO = "https://contratos.trotamundos.app/"
_ASYNCAPI = "asyncapi/eventos-de-dominio.yaml"


class ErrorDeContrato(ValueError):
    """Una instancia no cumple el esquema de su contrato."""

    def __init__(self, referencia: str, errores: list[str]):
        self.referencia = referencia
        self.errores = errores
        super().__init__(f"No cumple {referencia}: " + "; ".join(errores))


class Contratos:
    """Carga los contratos de una carpeta y valida instancias contra sus esquemas."""

    def __init__(self, ruta: Path):
        self.ruta = ruta.resolve()
        if not self.ruta.is_dir():
            raise FileNotFoundError(f"No existe la carpeta de contratos: {self.ruta}")

    # --- carga de documentos -------------------------------------------------------------

    @lru_cache(maxsize=None)
    def _documento(self, relativa: str) -> dict[str, Any]:
        """Documento parseado y compartido por los validadores. No debe modificarse."""
        archivo = self._dentro_de_contratos(self.ruta / relativa)
        with open(archivo, encoding="utf-8") as fuente:
            return yaml.safe_load(fuente)

    def documento(self, relativa: str) -> dict[str, Any]:
        """Copia de un archivo de contratos ya parseado.

        Es una copia para que quien la modifique no altere las validaciones posteriores.
        """
        return copy.deepcopy(self._documento(relativa))

    def _dentro_de_contratos(self, ruta: Path) -> Path:
        ruta = ruta.resolve()
        if not ruta.is_relative_to(self.ruta):
            raise ValueError(f"La referencia sale de la carpeta de contratos: {ruta}")
        return ruta

    def _uri(self, relativa: str) -> str:
        return self._dentro_de_contratos(self.ruta / relativa).as_uri()

    def _recuperar(self, uri: str) -> Resource:
        if uri.startswith("https://json-schema.org/"):
            return ESPECIFICACIONES.get_or_retrieve(uri).value
        if uri.startswith(_PREFIJO_ID_PUBLICO):
            uri = self._uri(uri.removeprefix(_PREFIJO_ID_PUBLICO))
        if not uri.startswith("file://"):
            raise LookupError(f"Referencia externa no permitida en un contrato: {uri}")
        # La ruta puede tener espacios y tildes: la URI llega codificada.
        ruta = self._dentro_de_contratos(Path(unquote(urlparse(uri).path)))
        relativa = ruta.relative_to(self.ruta).as_posix()
        return Resource.from_contents(self._documento(relativa), default_specification=DRAFT202012)

    @cached_property
    def _registro(self) -> Registry:
        return Registry(retrieve=self._recuperar)  # type: ignore[call-arg]

    # --- validación ----------------------------------------------------------------------

    @lru_cache(maxsize=None)
    def validador(self, referencia: str) -> Draft202012Validator:
        """Validador para `archivo#/puntero` (relativo a la carpeta de contratos)."""
        archivo, _, puntero = referencia.partition("#")
        esquema = {"$ref": f"{self._uri(archivo)}#{puntero}"}
        return Draft202012Validator(
            esquema,
            registry=self._registro,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )

    def errores(self, referencia: str, instancia: Any) -> list[str]:
        """Lista de errores (vacía si la instancia cumple el contrato)."""
        errores = sorted(self.validador(referencia).iter_errors(instancia),
                         key=lambda e: (e.json_path, e.message))
        return [f"{e.json_path}: {e.message}" for e in errores]

    def validar(self, referencia: str, instancia: Any) -> None:
        """Lanza `ErrorDeContrato` si la instancia no cumple el esquema."""
        errores = self.errores(referencia, instancia)
        if errores:
            raise ErrorDeContrato(referencia, errores)

    # --- eventos de dominio (AsyncAPI) ---------------------------------------------------

    def tipos_de_evento(self) -> list[str]:
        return sorted(self._documento(_ASYNCAPI)["components"]["messages"])

    def canal_de_evento(self, tipo: str) -> str:
        """Tópico del broker donde se publica el evento (`address` del canal)."""
        for canal in self._documento(_ASYNCAPI)["channels"].values():
            if tipo in canal["messages"]:
                return canal["address"]
        raise KeyError(f"Evento sin canal en el contrato AsyncAPI: {tipo}")

    def referencia_sobre(self, tipo: str) -> str:
        self._exigir_evento(tipo)
        return f"{_ASYNCAPI}#/components/messages/{tipo}/headers"

    def referencia_carga(self, tipo: str) -> str:
        self._exigir_evento(tipo)
        return f"{_ASYNCAPI}#/components/messages/{tipo}/payload"

    def _exigir_evento(self, tipo: str) -> None:
        if tipo not in self._documento(_ASYNCAPI)["components"]["messages"]:
            raise KeyError(f"Tipo de evento no declarado en el contrato AsyncAPI: {tipo}")

    # --- descriptores de tipo de segmento ------------------------------------------------

    def descriptores(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Pares (archivo, copia del descriptor) de `tipos-de-segmento/*.v<N>.yaml`."""
        for archivo in sorted((self.ruta / "tipos-de-segmento").glob("*.v*.yaml")):
            relativa = archivo.relative_to(self.ruta).as_posix()
            yield relativa, self.documento(relativa)


@lru_cache(maxsize=1)
def contratos_por_omision() -> Contratos:
    """Contratos de la carpeta configurada (`TROTAMUNDOS_CONTRATOS` o `<repo>/contratos`)."""
    return Contratos(Configuracion.desde_entorno().ruta_contratos)
