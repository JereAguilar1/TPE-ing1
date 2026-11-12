"""Módulo `reservas`: el agregado `Reserva` (ADR-0010, iteración 2 §5.2).

`Reserva` es la unidad de identidad y de fusión. Guarda las **entradas** de la consolidación
(las observaciones, los campos fijados por el usuario y sus decisiones) y la **vista
consolidada** que el módulo `fusion` calcula a partir de ellas. La vista es una función
determinista de las entradas (ADR-0010, ADR-0013): este módulo no decide valores, solo cuida las
invariantes del agregado.

Por la regla I1 de la vista N2, este módulo no conoce a `viajes` ni a `fusion`. Sí usa el
registro de tipos (vista N2: `reservas` → `tipos-de-segmento`) para validar el detalle de cada
segmento contra el descriptor de su tipo y versión (ADR-0011, ADR-0027).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping
from uuid import UUID

from trotamundos.comun.modelo import (
    Fuente,
    Identificador,
    ObservacionCanonica,
    instante_a_texto,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, registro_por_omision


class EstadoReserva(StrEnum):
    """Estados de una reserva (iteración 2 §5.2; `EstadoReserva` de `comun.yaml`)."""

    POR_CONFIRMAR = "PorConfirmar"
    CONFIRMADA = "Confirmada"
    CANCELADA = "Cancelada"
    FINALIZADA = "Finalizada"
    DESCARTADA = "Descartada"


class Banda(StrEnum):
    """Banda de confianza de una extracción de correo (ADR-0015). La baja no llega a `itinerary`."""

    ALTA = "alta"
    MEDIA = "media"


class TransicionInvalida(Exception):
    """El comando no se puede aplicar en el estado actual de la reserva (se responde 409)."""


class ReservaInvalida(ValueError):
    """Se violaría una invariante del agregado."""


# Campos fijables: `cancelada` (el estado de la reserva) o una hoja de un segmento, con la forma
# de `ConflictoDeFuentes.campo` en `comun.yaml` (por ejemplo, `segmentos[0].inicio.instante`).
# Las partes admiten cualquier carácter salvo los separadores de la ruta: las claves del detalle
# las define cada descriptor, y un tipo nuevo no debe obligar a tocar este código (QA-15).
_CAMPO_FIJABLE = re.compile(r"^(cancelada|segmentos\[(0|[1-9]\d*)\]\.[^.\[\]]+(\.[^.\[\]]+)*)$")
CAMPO_CANCELADA = "cancelada"


@dataclass(frozen=True)
class ObservacionRegistrada:
    """Una `ObservacionCanonica` tal como la guarda la reserva, con su banda si vino del correo."""

    observacion: ObservacionCanonica
    banda: Banda | None = None
    confianza: float | None = None

    def __post_init__(self) -> None:
        if (self.observacion.fuente == Fuente.CORREO) != (self.banda is not None):
            raise ReservaInvalida("La banda va en las observaciones del correo y solo en ellas")

    @property
    def clave(self) -> tuple[Fuente, str]:
        return self.observacion.clave

    @property
    def fuente(self) -> Fuente:
        return self.observacion.fuente

    @property
    def version_de_fuente(self) -> datetime:
        return self.observacion.version_de_fuente

    @property
    def orden(self) -> tuple[datetime, str]:
        """Orden total entre versiones de una misma clave: primero la versión de la fuente; ante
        un empate, el contenido, para que el resultado no dependa del orden de llegada."""
        return self.version_de_fuente, self.huella

    @property
    def huella(self) -> str:
        return json.dumps([self.observacion.a_dict(), self.banda, self.confianza],
                          sort_keys=True, ensure_ascii=False)

    @property
    def confirma(self) -> bool:
        """La banda media necesita la confirmación del usuario (ADR-0015); el resto no."""
        return self.banda != Banda.MEDIA


@dataclass(frozen=True)
class Fijado:
    """Un campo que el usuario fijó con una edición manual (ADR-0013). `valor` en forma JSON."""

    campo: str
    valor: Any
    fijado_en: datetime

    def __post_init__(self) -> None:
        if not _CAMPO_FIJABLE.match(self.campo):
            raise ReservaInvalida(f"Campo no fijable: {self.campo}")
        if self.campo == CAMPO_CANCELADA and not isinstance(self.valor, bool):
            raise ReservaInvalida("El campo cancelada se fija con true o false")


@dataclass(frozen=True)
class ValorEnDisputa:
    fuente: Fuente
    valor: Any
    observado_en: datetime

    def a_dict(self) -> dict[str, Any]:
        return {"fuente": self.fuente.value, "valor": self.valor,
                "observadoEn": instante_a_texto(self.observado_en)}


@dataclass(frozen=True)
class ConflictoDeFuentes:
    """Un campo fijado que una fuente posterior contradice (ADR-0013). Solo hay abiertos: al
    resolverlo cambia el fijado y el conflicto deja de derivarse."""

    id: UUID
    campo: str
    valores: tuple[ValorEnDisputa, ...]

    def a_dict(self) -> dict[str, Any]:
        return {"id": str(self.id), "campo": self.campo,
                "valores": [v.a_dict() for v in self.valores], "estado": "Abierto"}


@dataclass(frozen=True)
class VistaConsolidada:
    """Lo que la reserva dice hoy, derivado de las observaciones y de los fijados.

    `segmentos` tiene la forma de `Segmento` de `comun.yaml`. `origen` dice de qué fuente salió
    cada valor (campo → fuente), para que cada valor consolidado sea explicable (ADR-0013).
    """

    segmentos: tuple[Mapping[str, Any], ...]
    cancelada: bool
    conflictos: tuple[ConflictoDeFuentes, ...] = ()
    origen: Mapping[str, Fuente] = field(default_factory=dict, compare=False)


class Reserva:
    """Raíz del agregado `Reserva` (ADR-0010).

    Invariantes que cuida:
    * Por cada clave `(fuente, idDeFuente)` se conserva una sola observación, la de mayor versión
      de la fuente (ADR-0014): repetir una observación o recibir una versión vieja no cambia nada.
    * Las observaciones no se borran: solo se agregan o se reemplazan por una versión posterior.
    * Toda observación cumple `ObservacionCanonica` y su detalle valida contra el descriptor.
    * La vista consolidada tiene al menos un segmento, y el detalle de cada uno valida contra el
      descriptor de su `(tipo, versionTipo)`.
    * `version` aumenta una vez por cada cambio aplicado (control de concurrencia optimista).
    """

    def __init__(self, id: UUID, usuario_id: UUID, creada_en: datetime,
                 registro: RegistroDeTipos | None = None):
        self.id = id
        self.usuario_id = usuario_id
        self.creada_en = creada_en
        self.registro = registro if registro is not None else registro_por_omision()
        self.version = 0
        self._estado_consolidado: EstadoReserva | None = None
        self._observaciones: dict[tuple[Fuente, str], ObservacionRegistrada] = {}
        self._fijados: dict[str, Fijado] = {}
        self._identificadores: set[Identificador] = set()
        self._confirmada_por_usuario = False
        self._descartada = False
        self._vista: VistaConsolidada | None = None
        self._pendiente = False

    @classmethod
    def restaurar(cls, *, id: UUID, usuario_id: UUID, creada_en: datetime, version: int,
                  observaciones: Iterable[ObservacionRegistrada], fijados: Iterable[Fijado],
                  identificadores: Iterable[Identificador], confirmada_por_usuario: bool,
                  descartada: bool, vista: VistaConsolidada,
                  registro: RegistroDeTipos | None = None) -> Reserva:
        """Reconstruye una reserva guardada, tal como quedó (sin validar de nuevo ni subir la
        versión): lo que se guardó ya cumplió las invariantes al entrar."""
        reserva = cls(id, usuario_id, creada_en, registro)
        reserva.version = version
        reserva._observaciones = {o.clave: o for o in observaciones}
        reserva._fijados = {f.campo: f for f in fijados}
        reserva._identificadores = set(identificadores)
        reserva._confirmada_por_usuario = confirmada_por_usuario
        reserva._descartada = descartada
        reserva._vista = vista
        reserva._estado_consolidado = reserva.estado
        return reserva

    # --- entradas de la consolidación ----------------------------------------------------

    def registrar(self, registrada: ObservacionRegistrada) -> bool:
        """Agrega la observación; devuelve `False` si ya tenía esa versión o una posterior.

        Lanza `ErrorDeContrato` si la observación no cumple el contrato o su detalle no valida
        contra el descriptor del tipo: nada que no valide entra al agregado (ADR-0011).
        """
        self.registro.validar_observacion(registrada.observacion.a_dict())
        actual = self._observaciones.get(registrada.clave)
        if actual is not None and actual.orden >= registrada.orden:
            return False
        self._observaciones[registrada.clave] = registrada
        if registrada.fuente == Fuente.MANUAL:
            # Un alta del usuario sobre una reserva que él descartó o dio de baja la vuelve a
            # mostrar: manda su última decisión. Una fuente automática no la revive.
            self._descartada = False
        self._pendiente = True
        return True

    def agregar_identificadores(self, identificadores: set[Identificador] | tuple[Identificador, ...]) -> None:
        nuevos = set(identificadores) - self._identificadores
        if nuevos:
            self._identificadores |= nuevos
            self._pendiente = True

    def fijar(self, fijado: Fijado) -> None:
        if self._fijados.get(fijado.campo) != fijado:
            self._fijados[fijado.campo] = fijado
            self._pendiente = True

    def desfijar(self, campo: str) -> None:
        if self._fijados.pop(campo, None) is not None:
            self._pendiente = True

    def confirmar(self) -> None:
        """El usuario confirma una reserva de banda media (ADR-0015)."""
        self._exigir_estado(EstadoReserva.POR_CONFIRMAR)
        self._confirmada_por_usuario = True
        self._pendiente = True

    def descartar(self) -> None:
        """El usuario descarta una reserva de banda media (`PorConfirmar` → `Descartada`)."""
        self._exigir_estado(EstadoReserva.POR_CONFIRMAR)
        self._descartada = True
        self._pendiente = True

    def dar_de_baja(self) -> None:
        """Baja manual (RF-06): la reserva pasa a `Descartada` desde cualquier estado.

        La reserva y sus observaciones se conservan, así que un correo posterior con el mismo
        localizador no la revive: se agrega a esta reserva, que sigue descartada.
        """
        if self._descartada:
            raise TransicionInvalida("La reserva ya está dada de baja")
        self._descartada = True
        self._pendiente = True

    def resolver_conflicto(self, conflicto_id: UUID, aceptar: Fuente | None, ahora: datetime) -> None:
        """Resuelve un conflicto con una nueva fijación (ADR-0013).

        `aceptar=None` mantiene el valor fijado; `aceptar=<fuente>` fija el valor de esa fuente.
        En los dos casos el fijado pasa a ser posterior a las observaciones en disputa, así que el
        conflicto deja de derivarse; un valor distinto que llegue después abre otro.
        """
        conflicto = next((c for c in self.vista.conflictos if c.id == conflicto_id), None)
        if conflicto is None:
            raise TransicionInvalida(f"No hay un conflicto abierto {conflicto_id}")
        fuentes = {v.fuente: v.valor for v in conflicto.valores}
        fuente = Fuente.MANUAL if aceptar is None else aceptar
        if fuente not in fuentes:
            raise TransicionInvalida(f"La fuente {fuente} no participa del conflicto")
        self.fijar(Fijado(conflicto.campo, fuentes[fuente], ahora))

    def unir(self, otra: Reserva) -> None:
        """Absorbe las entradas de `otra` (unificación por identificadores, ADR-0013). Ante dos
        fijados del mismo campo queda el más reciente."""
        if otra.usuario_id != self.usuario_id:
            raise ReservaInvalida("Solo se unifican reservas del mismo usuario")
        for registrada in otra._observaciones.values():
            self.registrar(registrada)
        for fijado in otra._fijados.values():
            actual = self._fijados.get(fijado.campo)
            if actual is None or (actual.fijado_en, json.dumps(actual.valor, sort_keys=True)) < \
                    (fijado.fijado_en, json.dumps(fijado.valor, sort_keys=True)):
                self.fijar(fijado)
        self.agregar_identificadores(otra._identificadores)
        if otra._confirmada_por_usuario and not self._confirmada_por_usuario:
            self._confirmada_por_usuario = True
            self._pendiente = True

    # --- vista consolidada ---------------------------------------------------------------

    def establecer_vista(self, vista: VistaConsolidada) -> None:
        """La fija `fusion` después de consolidar. Si hubo cambios desde la última, sube la
        versión."""
        if not vista.segmentos:
            raise ReservaInvalida("Una reserva tiene al menos un segmento")
        errores = [error
                   for i, segmento in enumerate(vista.segmentos)
                   for error in self.registro.errores_de_detalle(
                       segmento["tipo"], segmento["versionTipo"], segmento.get("detalle"),
                       prefijo=f"$.segmentos[{i}].detalle")]
        if errores:
            raise ReservaInvalida("Detalle inválido para su tipo: " + "; ".join(errores))
        if vista != self._vista:
            self._pendiente = True
        self._vista = vista
        self._estado_consolidado = self.estado
        if self._pendiente:
            self.version += 1
            self._pendiente = False

    @property
    def vista(self) -> VistaConsolidada:
        if self._vista is None:
            raise ReservaInvalida("La reserva todavía no se consolidó")
        return self._vista

    @property
    def consolidada(self) -> bool:
        return self._vista is not None

    @property
    def estado_consolidado(self) -> EstadoReserva | None:
        """El estado al fijarse la última vista: contra él se detecta una transición (paso 4)."""
        return self._estado_consolidado

    # --- consultas -----------------------------------------------------------------------

    @property
    def observaciones(self) -> tuple[ObservacionRegistrada, ...]:
        return tuple(self._observaciones[c] for c in sorted(self._observaciones))

    @property
    def fijados(self) -> dict[str, Fijado]:
        return dict(self._fijados)

    @property
    def confirmada_por_usuario(self) -> bool:
        return self._confirmada_por_usuario

    @property
    def descartada(self) -> bool:
        return self._descartada

    @property
    def identificadores(self) -> frozenset[Identificador]:
        return frozenset(self._identificadores)

    @property
    def fuentes(self) -> set[Fuente]:
        return {fuente for fuente, _ in self._observaciones}

    @property
    def es_manual(self) -> bool:
        """Tiene alguna observación del usuario (alta o edición): unificarla pide confirmación."""
        return Fuente.MANUAL in self.fuentes

    @property
    def banda(self) -> Banda | None:
        """Solo para reservas con observaciones del correo: la mejor banda recibida."""
        bandas = {o.banda for o in self._observaciones.values() if o.banda is not None}
        if not bandas:
            return None
        return Banda.ALTA if Banda.ALTA in bandas else Banda.MEDIA

    @property
    def estado(self) -> EstadoReserva:
        """Sigue la máquina de estados de la iteración 2 §5.2: `PorConfirmar` → `Confirmada` →
        `Cancelada`. Una reserva por confirmar no pasa a `Cancelada` por datos de banda media,
        que no disparan avisos críticos (ADR-0015). `Finalizada` depende del tiempo y la deriva el
        ciclo de vida (paso 5 del prototipo)."""
        if self._descartada:
            return EstadoReserva.DESCARTADA
        if not (self._confirmada_por_usuario
                or any(o.confirma for o in self._observaciones.values())):
            return EstadoReserva.POR_CONFIRMAR
        if self.consolidada and self.vista.cancelada:
            return EstadoReserva.CANCELADA
        return EstadoReserva.CONFIRMADA

    def _exigir_estado(self, esperado: EstadoReserva) -> None:
        if self.estado != esperado:
            raise TransicionInvalida(f"La reserva está {self.estado}, no {esperado}")

    # --- contrato ------------------------------------------------------------------------

    def a_dict(self) -> dict[str, Any]:
        """Representación `Reserva` de `comun.yaml`. `viajeId` lo agrega quien conoce el viaje."""
        vista = self.vista
        datos: dict[str, Any] = {
            "id": str(self.id),
            "estado": self.estado.value,
            "version": self.version,
            "identificadores": [i.a_dict() for i in sorted(self._identificadores,
                                                           key=lambda i: (i.emisor, i.codigo))],
            "segmentos": [json.loads(json.dumps(s)) for s in vista.segmentos],
            "fuentes": sorted(f.value for f in self.fuentes),
            "conflictosAbiertos": [c.a_dict() for c in vista.conflictos],
        }
        if self.banda is not None:
            datos["banda"] = self.banda.value
        return datos
