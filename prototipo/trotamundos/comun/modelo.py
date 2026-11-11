"""Modelo canónico: los tipos compartidos por el dominio y la capa de anticorrupción.

Es el módulo `modelo-canonico` de la vista de módulos N1 (ADR-0006, ADR-0010): la forma común en
que adaptadores y extractores entregan lo que observan, y en que `itinerary` lo recibe. Los
agregados `Reserva` y `Viaje` no están acá: son de `itinerary` (vista de módulos N2).

Regla R7 de la vista N1: este módulo **no depende de nada** fuera de la biblioteca estándar. No
valida contra los contratos; quien construye un objeto a partir de un diccionario debe haberlo
validado antes (`trotamundos.comun.tipos_de_segmento.RegistroDeTipos.validar_observacion`).

Los nombres de los campos en `a_dict` y `desde_dict` son los de `contratos/openapi/comun.yaml`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class Fuente(StrEnum):
    """Origen de una observación; determina la precedencia al fusionar (ADR-0013)."""

    CORREO = "correo"
    PROVEEDOR = "proveedor"
    MANUAL = "manual"


class Precision(StrEnum):
    """`dia` para boletos abiertos que valen «ese día», sin hora (ADR-0011)."""

    INSTANTE = "instante"
    DIA = "dia"


class EstadoSegmento(StrEnum):
    CONFIRMADO = "confirmado"
    CANCELADO = "cancelado"


class RolEnViaje(StrEnum):
    """La agrupación en viajes razona por rol, nunca por tipo de segmento (ADR-0010, RF-07)."""

    TRASLADO = "traslado"
    ALOJAMIENTO = "alojamiento"
    MOVILIDAD_LOCAL = "movilidadLocal"


class Severidad(StrEnum):
    CRITICA = "critica"
    INFORMATIVA = "informativa"


# --- instantes ------------------------------------------------------------------------------

def instante_desde_texto(texto: str) -> datetime:
    """Instante RFC 3339 a `datetime` en UTC. Rechaza instantes sin zona (ADR-0032)."""
    instante = datetime.fromisoformat(texto)
    if instante.tzinfo is None:
        raise ValueError(f"Instante sin zona horaria: {texto}")
    return instante.astimezone(timezone.utc)


def instante_a_texto(instante: datetime) -> str:
    """`datetime` a RFC 3339 en UTC con sufijo `Z`, sin fracciones de segundo si no las tiene."""
    utc = instante.astimezone(timezone.utc)
    if utc.microsecond == 0:
        especificacion = "seconds"
    elif utc.microsecond % 1000 == 0:
        especificacion = "milliseconds"
    else:
        especificacion = "microseconds"
    return utc.replace(tzinfo=None).isoformat(timespec=especificacion) + "Z"


def _sin_nulos(campos: dict[str, Any]) -> dict[str, Any]:
    return {clave: valor for clave, valor in campos.items() if valor is not None}


# --- tipos del núcleo -----------------------------------------------------------------------

@dataclass(frozen=True)
class Coordenadas:
    lat: float
    lon: float


@dataclass(frozen=True)
class Lugar:
    nombre: str
    pais: str
    zona_horaria: str
    codigo: str | None = None
    esquema_de_codigo: str | None = None
    coordenadas: Coordenadas | None = None

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> Lugar:
        coordenadas = datos.get("coordenadas")
        return cls(
            nombre=datos["nombre"],
            pais=datos["pais"],
            zona_horaria=datos["zonaHoraria"],
            codigo=datos.get("codigo"),
            esquema_de_codigo=datos.get("esquemaDeCodigo"),
            coordenadas=Coordenadas(coordenadas["lat"], coordenadas["lon"]) if coordenadas else None,
        )

    def a_dict(self) -> dict[str, Any]:
        return _sin_nulos({
            "nombre": self.nombre,
            "codigo": self.codigo,
            "esquemaDeCodigo": self.esquema_de_codigo,
            "pais": self.pais,
            "coordenadas": (
                {"lat": self.coordenadas.lat, "lon": self.coordenadas.lon}
                if self.coordenadas else None
            ),
            "zonaHoraria": self.zona_horaria,
        })


@dataclass(frozen=True)
class Extremo:
    """Inicio o fin de un segmento: instante en UTC más la zona horaria local (ADR-0032)."""

    instante: datetime
    precision: Precision
    zona_horaria: str
    lugar: Lugar

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> Extremo:
        return cls(
            instante=instante_desde_texto(datos["instante"]),
            precision=Precision(datos["precision"]),
            zona_horaria=datos["zonaHoraria"],
            lugar=Lugar.desde_dict(datos["lugar"]),
        )

    def a_dict(self) -> dict[str, Any]:
        return {
            "instante": instante_a_texto(self.instante),
            "precision": self.precision.value,
            "zonaHoraria": self.zona_horaria,
            "lugar": self.lugar.a_dict(),
        }


@dataclass(frozen=True)
class Identificador:
    """Par que identifica una reserva ante un emisor (ADR-0013)."""

    emisor: str
    codigo: str

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> Identificador:
        return cls(emisor=datos["emisor"], codigo=datos["codigo"])

    def a_dict(self) -> dict[str, Any]:
        return {"emisor": self.emisor, "codigo": self.codigo}


@dataclass(frozen=True)
class SegmentoObservado:
    """Un tramo tal como lo afirma una fuente. El `detalle` depende del tipo (ADR-0011)."""

    tipo: str
    version_tipo: int
    inicio: Extremo
    fin: Extremo
    operador: str
    # El detalle es un diccionario: participa de la igualdad pero no del hash, para que los
    # segmentos y las observaciones puedan usarse en conjuntos y como claves.
    detalle: Mapping[str, Any] = field(hash=False)
    referencia: str | None = None
    estado: EstadoSegmento | None = None

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> SegmentoObservado:
        estado = datos.get("estado")
        return cls(
            tipo=datos["tipo"],
            version_tipo=datos["versionTipo"],
            inicio=Extremo.desde_dict(datos["inicio"]),
            fin=Extremo.desde_dict(datos["fin"]),
            operador=datos["operador"],
            detalle=copy.deepcopy(dict(datos["detalle"])),
            referencia=datos.get("referencia"),
            estado=EstadoSegmento(estado) if estado else None,
        )

    def a_dict(self) -> dict[str, Any]:
        return _sin_nulos({
            "tipo": self.tipo,
            "versionTipo": self.version_tipo,
            "inicio": self.inicio.a_dict(),
            "fin": self.fin.a_dict(),
            "operador": self.operador,
            "referencia": self.referencia,
            "estado": self.estado.value if self.estado else None,
            "detalle": copy.deepcopy(dict(self.detalle)),
        })


@dataclass(frozen=True)
class ObservacionCanonica:
    """Lo que una fuente afirma sobre una reserva en un momento (ADR-0010).

    Se identifica por `(fuente, id_de_fuente)` y se ordena por `version_de_fuente` (ADR-0014).
    """

    fuente: Fuente
    id_de_fuente: str
    version_de_fuente: datetime
    identificadores: tuple[Identificador, ...]
    segmentos: tuple[SegmentoObservado, ...]
    cancelada: bool = False

    @property
    def clave(self) -> tuple[Fuente, str]:
        return self.fuente, self.id_de_fuente

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> ObservacionCanonica:
        return cls(
            fuente=Fuente(datos["fuente"]),
            id_de_fuente=datos["idDeFuente"],
            version_de_fuente=instante_desde_texto(datos["versionDeFuente"]),
            identificadores=tuple(Identificador.desde_dict(i) for i in datos["identificadores"]),
            segmentos=tuple(SegmentoObservado.desde_dict(s) for s in datos["segmentos"]),
            cancelada=datos.get("cancelada", False),
        )

    def a_dict(self) -> dict[str, Any]:
        datos: dict[str, Any] = {
            "fuente": self.fuente.value,
            "idDeFuente": self.id_de_fuente,
            "versionDeFuente": instante_a_texto(self.version_de_fuente),
            "identificadores": [i.a_dict() for i in self.identificadores],
            "segmentos": [s.a_dict() for s in self.segmentos],
        }
        if self.cancelada:
            datos["cancelada"] = True
        return datos


# --- descriptor de tipo de segmento ---------------------------------------------------------

@dataclass(frozen=True)
class CampoRelevante:
    """Un cambio en `campo` genera aviso con esta severidad (consumido por `notification`)."""

    campo: str
    severidad: Severidad
    umbral_minutos: int | None = None


@dataclass(frozen=True)
class DescriptorDeTipo:
    """Declaración versionada de un tipo de segmento (ADR-0011, ADR-0027).

    Solo tiene los campos que el código interpreta. El descriptor completo (con `presentacion` y
    `dimension`, que se sirven tal cual) se obtiene del registro, como copia.
    """

    tipo: str
    version: int
    rol_en_viaje: RolEnViaje
    campos_relevantes: tuple[CampoRelevante, ...]

    @classmethod
    def desde_dict(cls, datos: Mapping[str, Any]) -> DescriptorDeTipo:
        return cls(
            tipo=datos["tipo"],
            version=datos["version"],
            rol_en_viaje=RolEnViaje(datos["rolEnViaje"]),
            campos_relevantes=tuple(
                CampoRelevante(c["campo"], Severidad(c["severidad"]), c.get("umbralMinutos"))
                for c in datos["camposRelevantes"]
            ),
        )
