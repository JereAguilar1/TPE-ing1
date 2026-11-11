"""Registro de tipos de segmento (ADR-0011, QA-15).

Carga los descriptores de `contratos/tipos-de-segmento/` y los ofrece a quien los necesita:
`itinerary` (validar el detalle, agrupar por `rolEnViaje`), los adaptadores y extractores (validar
su salida, QA-10 y QA-11), `notification` (`camposRelevantes`), los BFF (`presentacion`) y el plano
analítico (`dimension`). En la vista de módulos de adaptadores, los descriptores son un artefacto
común transversal; por eso el registro vive en `comun` y no dentro de un servicio. La vista N2 lo
ubica en `itinerary`; ver «Decisiones de implementación» en el README del prototipo.

**Ningún tipo concreto aparece en este código.** Agregar un tipo es agregar su descriptor: el
registro lo descubre al arrancar (guía de extensión de la iteración 4).

Versionado (ADR-0027): cada descriptor tiene una `version` entera. Las versiones coexisten y un
segmento se valida siempre contra la versión con que se creó (`versionTipo`).
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Any, Iterable, Mapping

from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision
from trotamundos.comun.modelo import DescriptorDeTipo, RolEnViaje

METAESQUEMA = "tipos-de-segmento/descriptor.schema.yaml"
OBSERVACION = "openapi/comun.yaml#/components/schemas/ObservacionCanonica"
_SEGMENTO = ("openapi/comun.yaml", "/components/schemas/Segmento")
_NOMBRE_DE_ARCHIVO = re.compile(r"^tipos-de-segmento/(?P<tipo>[^/.]+)\.v(?P<version>\d+)\.yaml$")
_MARCADOR_DE_TITULO = re.compile(r"\{([^{}]+)\}")


class DescriptorInvalido(ValueError):
    """Uno o más descriptores no cumplen el metaesquema o no son coherentes con el núcleo."""

    def __init__(self, problemas: list[str]):
        self.problemas = problemas
        super().__init__("Descriptores de tipo de segmento inválidos: " + "; ".join(problemas))


class TipoNoRegistrado(LookupError):
    """No hay descriptor para ese tipo (o para esa versión del tipo)."""


class RegistroDeTipos:
    """Descriptores vigentes, indexados por `(tipo, version)`."""

    def __init__(self, contratos: Contratos, descriptores: Iterable[tuple[str, Mapping[str, Any]]]):
        self._contratos = contratos
        self._archivos: dict[tuple[str, int], str] = {}
        self._descriptores: dict[tuple[str, int], DescriptorDeTipo] = {}
        # Copia privada de cada descriptor completo; hacia afuera solo salen copias.
        self._documentos: dict[tuple[str, int], dict[str, Any]] = {}

        problemas: list[str] = []
        for relativa, documento in descriptores:
            encontrados = self._revisar(relativa, documento)
            if encontrados:
                problemas.extend(f"{relativa}: {p}" for p in encontrados)
                continue
            clave = (documento["tipo"], documento["version"])
            self._archivos[clave] = relativa
            self._documentos[clave] = copy.deepcopy(dict(documento))
            self._descriptores[clave] = DescriptorDeTipo.desde_dict(self._documentos[clave])
        if problemas:
            raise DescriptorInvalido(problemas)

    @classmethod
    def desde_contratos(cls, contratos: Contratos) -> RegistroDeTipos:
        return cls(contratos, contratos.descriptores())

    # --- consultas -----------------------------------------------------------------------

    def tipos(self) -> list[str]:
        return sorted({tipo for tipo, _ in self._descriptores})

    def obtener(self, tipo: str, version: int | None = None) -> DescriptorDeTipo:
        """Descriptor de `(tipo, version)`; sin versión, el vigente (la más alta)."""
        if version is None:
            versiones = [v for t, v in self._descriptores if t == tipo]
            if not versiones:
                raise TipoNoRegistrado(f"Tipo de segmento no registrado: {tipo}")
            version = max(versiones)
        try:
            return self._descriptores[(tipo, version)]
        except KeyError:
            raise TipoNoRegistrado(f"Tipo de segmento no registrado: {tipo} v{version}") from None

    def rol(self, tipo: str, version: int) -> RolEnViaje:
        return self.obtener(tipo, version).rol_en_viaje

    def documento(self, tipo: str, version: int | None = None) -> dict[str, Any]:
        """Copia del descriptor completo (con `presentacion` y `dimension`)."""
        descriptor = self.obtener(tipo, version)
        return copy.deepcopy(self._documentos[(descriptor.tipo, descriptor.version)])

    def documentos(self) -> list[dict[str, Any]]:
        """Todos los descriptores, incluidas las versiones anteriores (`GET /tipos-de-segmento`)."""
        return [copy.deepcopy(self._documentos[clave]) for clave in sorted(self._documentos)]

    # --- validación ----------------------------------------------------------------------

    def errores_de_detalle(self, tipo: str, version: int, detalle: Any,
                           prefijo: str = "$") -> list[str]:
        """Errores del `detalle` contra el `esquemaDeDetalle` de `(tipo, version)`."""
        if (tipo, version) not in self._descriptores:
            return [f"{prefijo}: tipo de segmento no registrado: {tipo} v{version}"]
        referencia = f"{self._archivos[(tipo, version)]}#/esquemaDeDetalle"
        return [prefijo + error.removeprefix("$")
                for error in self._contratos.errores(referencia, detalle)]

    def validar_detalle(self, tipo: str, version: int, detalle: Any) -> None:
        errores = self.errores_de_detalle(tipo, version, detalle)
        if errores:
            raise ErrorDeContrato(f"{tipo} v{version}", errores)

    def validar_observacion(self, observacion: Any) -> None:
        """Valida una `ObservacionCanonica` completa: el núcleo contra `comun.yaml` y el detalle
        de cada segmento contra el descriptor de su tipo (salida de adaptadores y extractores)."""
        errores = self._contratos.errores(OBSERVACION, observacion)
        segmentos = observacion.get("segmentos") if isinstance(observacion, dict) else None
        for i, segmento in enumerate(segmentos if isinstance(segmentos, list) else []):
            if not isinstance(segmento, dict):
                continue
            tipo, version = segmento.get("tipo"), segmento.get("versionTipo")
            if not (isinstance(tipo, str) and isinstance(version, int)):
                continue  # ya lo informa la validación del núcleo
            if (tipo, version) not in self._descriptores:
                errores.append(f"$.segmentos[{i}].tipo: tipo de segmento no registrado: "
                               f"{tipo} v{version}")
            elif "detalle" in segmento:
                errores += self.errores_de_detalle(tipo, version, segmento["detalle"],
                                                   prefijo=f"$.segmentos[{i}].detalle")
        if errores:
            raise ErrorDeContrato(OBSERVACION, sorted(errores))

    # --- revisión de un descriptor al cargarlo -------------------------------------------

    def _revisar(self, relativa: str, documento: Mapping[str, Any]) -> list[str]:
        """Problemas de un descriptor. El metaesquema no puede expresar que los campos que
        nombra existan; eso se comprueba acá contra el núcleo (`Segmento`) y el detalle."""
        problemas = self._contratos.errores(METAESQUEMA, documento)
        if problemas:
            return problemas

        nombre = _NOMBRE_DE_ARCHIVO.match(relativa)
        if not nombre or (nombre["tipo"], int(nombre["version"])) != (documento["tipo"],
                                                                     documento["version"]):
            problemas.append(f"el archivo debe llamarse {documento['tipo']}.v{documento['version']}.yaml")

        detalle = documento["esquemaDeDetalle"]
        for relevante in documento["camposRelevantes"]:
            campo = relevante["campo"]
            existe = (self._en_esquema(detalle, campo.removeprefix("detalle.").split("."))
                      if campo.startswith("detalle.") else self._en_nucleo(campo))
            if not existe:
                problemas.append(f"camposRelevantes nombra un campo inexistente: {campo}")
        for fila in documento["presentacion"]["filas"]:
            if not self._en_esquema(detalle, fila.split(".")):
                problemas.append(f"presentacion.filas nombra un campo del detalle inexistente: {fila}")
        for marcador in _MARCADOR_DE_TITULO.findall(documento["presentacion"]["titulo"]):
            if not self._en_nucleo(marcador):
                problemas.append(f"presentacion.titulo usa un campo que no es del núcleo: {marcador}")
        for atributo in documento["dimension"]["atributos"]:
            if not (self._en_nucleo(atributo) or self._en_esquema(detalle, atributo.split("."))):
                problemas.append(f"dimension.atributos nombra un campo inexistente: {atributo}")
        return problemas

    def _en_nucleo(self, ruta: str) -> bool:
        """`ruta` es un campo del núcleo del segmento (todo `Segmento` menos su `detalle`)."""
        partes = ruta.split(".")
        archivo, puntero = _SEGMENTO
        raiz = self._contratos.documento(archivo)
        return partes[0] != "detalle" and self._en_esquema(_resolver(raiz, puntero), partes, raiz)

    def _en_esquema(self, esquema: Mapping[str, Any], partes: list[str],
                    raiz: Mapping[str, Any] | None = None) -> bool:
        """`partes` es una ruta de propiedades declarada en `esquema` (sigue `$ref` locales)."""
        for parte in partes:
            while (isinstance(esquema, Mapping) and raiz is not None
                   and str(esquema.get("$ref", "")).startswith("#/")):
                esquema = _resolver(raiz, esquema["$ref"][1:])
            if not isinstance(esquema, Mapping):
                return False  # esquema booleano (`true`): no declara propiedades
            propiedades = esquema.get("properties", {})
            if parte not in propiedades:
                return False
            esquema = propiedades[parte]
        return True


def _resolver(documento: Mapping[str, Any], puntero: str) -> Mapping[str, Any]:
    nodo: Any = documento
    for parte in puntero.strip("/").split("/"):
        nodo = nodo[parte.replace("~1", "/").replace("~0", "~")]
    return nodo


@lru_cache(maxsize=1)
def registro_por_omision() -> RegistroDeTipos:
    """Registro construido a partir de la carpeta de contratos configurada."""
    return RegistroDeTipos.desde_contratos(contratos_por_omision())
