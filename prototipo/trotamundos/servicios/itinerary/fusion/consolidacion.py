"""Consolidación determinista de una reserva (ADR-0010, ADR-0013).

`consolidar` es una función pura: recibe las observaciones y los fijados de una reserva y
devuelve su vista consolidada. No depende del orden de llegada, así que aplicar las mismas
observaciones en cualquier orden, o repetirlas, da el mismo resultado (ADR-0014, N3).

Reglas, en el orden en que se aplican:

1. **Una observación vigente por fuente.** De cada fuente cuenta solo la de mayor versión de la
   fuente (fecha de emisión, no de llegada): «dos versiones de la misma fuente, gana la de mayor
   versión» (ADR-0013). Es también la que conserva la compactación de observaciones (ADR-0012,
   ADR-0023), así que compactar no cambia la vista. Si la reserva ya está confirmada por alguna
   observación, las de banda media no cuentan: ningún dato dudoso entra como confirmado
   (ADR-0015).
2. **Valor por campo.** Las vigentes se ordenan por fuente: proveedor, correo, manual. Cada hoja de
   cada segmento toma el valor de la primera que la informa: el proveedor gana en los hechos
   operativos, el correo completa lo que el proveedor no informa y el usuario es la autoridad
   solo cuando no hay otra fuente o cuando fijó el campo (tabla de ADR-0013). La estructura
   (cuántos segmentos y de qué tipo) la da la primera; las demás aportan a un segmento solo si
   coinciden en cantidad de segmentos y en tipo y versión del tipo en esa posición, para no
   mezclar tramos ni detalles de versiones distintas.
3. **Cancelación.** La decide la primera observación, así que la del proveedor prevalece.
4. **Campos fijados.** Un campo fijado conserva el valor del usuario. Si una fuente automática lo
   contradice con una observación **posterior** al fijado, se abre un conflicto. Excepción: una
   cancelación del proveedor posterior a una reactivación manual prevalece sin conflicto. El
   tipo y su versión no se fijan (son la estructura), y un fijado del detalle que no valida
   contra el tipo actual del segmento (porque la estructura cambió) no se aplica.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid5

from trotamundos.comun.modelo import Fuente, ObservacionCanonica, instante_a_texto
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.itinerary.reservas import (
    CAMPO_CANCELADA,
    ConflictoDeFuentes,
    EstadoReserva,
    Fijado,
    ObservacionRegistrada,
    Reserva,
    ValorEnDisputa,
    VistaConsolidada,
)

PRECEDENCIA = (Fuente.PROVEEDOR, Fuente.CORREO, Fuente.MANUAL)

# Partes de un segmento que no se fusionan: las calcula la consolidación.
_DERIVADOS = ("id", "orden", "fijados")
# Partes que no se fijan: además de las derivadas, la estructura (el tipo y su versión).
_NO_FIJABLES = frozenset({*_DERIVADOS, "tipo", "versionTipo"})
# Valores que se toman enteros aunque sean objetos: un lugar no se arma con pedazos de dos fuentes.
_ATOMICOS = frozenset({"lugar"})
_CAMPO_DE_SEGMENTO = re.compile(r"^segmentos\[(\d+)\]\.(.+)$")
# Clave de `VistaConsolidada.origen` para lo que no tiene un origen propio (la estructura).
ORIGEN_DE_LA_ESTRUCTURA = "segmentos"


# --- campos como rutas -----------------------------------------------------------------------

def hojas(valor: Mapping[str, Any], prefijo: str = "") -> dict[str, Any]:
    """Aplana un objeto a `{ruta: valor}` (`inicio.instante`, `detalle.puerta`…)."""
    planas: dict[str, Any] = {}
    for clave, contenido in valor.items():
        ruta = f"{prefijo}{clave}"
        if isinstance(contenido, Mapping) and contenido and clave not in _ATOMICOS:
            planas.update(hojas(contenido, ruta + "."))
        else:
            planas[ruta] = contenido
    return planas


def _armar(planas: Mapping[str, Any]) -> dict[str, Any]:
    objeto: dict[str, Any] = {}
    for ruta, valor in planas.items():
        _asignar(objeto, ruta, valor)
    return objeto


def _asignar(objeto: dict[str, Any], ruta: str, valor: Any) -> None:
    *camino, ultima = ruta.split(".")
    for parte in camino:
        if not isinstance(objeto.get(parte), dict):
            objeto[parte] = {}
        objeto = objeto[parte]
    objeto[ultima] = copy.deepcopy(valor)


def _leer(objeto: Mapping[str, Any], ruta: str) -> Any:
    for parte in ruta.split("."):
        if not isinstance(objeto, Mapping) or parte not in objeto:
            return None
        objeto = objeto[parte]
    return objeto


# --- consolidación ---------------------------------------------------------------------------

def _clave_de_orden(registrada: ObservacionRegistrada) -> tuple:
    return (PRECEDENCIA.index(registrada.fuente), -registrada.version_de_fuente.timestamp(),
            registrada.observacion.id_de_fuente, registrada.huella)


def ordenar(observaciones: Iterable[ObservacionRegistrada]) -> list[ObservacionRegistrada]:
    """Observaciones de mayor a menor precedencia: por fuente y, dentro de cada una, por versión."""
    return sorted(observaciones, key=_clave_de_orden)


def vigentes(observaciones: Iterable[ObservacionRegistrada]) -> list[ObservacionRegistrada]:
    """La observación vigente de cada fuente, en orden de precedencia (reglas 1 y 2).

    Si alguna observación confirma la reserva, las de banda media no son vigentes: se guardan (y
    sus identificadores cuentan), pero no cambian los valores de una reserva confirmada (ADR-0015).
    """
    candidatas = list(observaciones)
    if any(o.confirma for o in candidatas):
        candidatas = [o for o in candidatas if o.confirma]
    elegidas: dict[Fuente, ObservacionRegistrada] = {}
    for registrada in ordenar(candidatas):
        elegidas.setdefault(registrada.fuente, registrada)
    return list(elegidas.values())


def _alineada(observacion: ObservacionCanonica, base: ObservacionCanonica, i: int) -> bool:
    if len(observacion.segmentos) != len(base.segmentos):
        return False
    propio, de_la_base = observacion.segmentos[i], base.segmentos[i]
    return (propio.tipo, propio.version_tipo) == (de_la_base.tipo, de_la_base.version_tipo)


def _segmento(observacion: ObservacionCanonica, i: int) -> dict[str, Any]:
    return observacion.segmentos[i].a_dict()


def consolidar(reserva_id: UUID, observaciones: Iterable[ObservacionRegistrada],
               fijados: Mapping[str, Fijado], registro: RegistroDeTipos) -> VistaConsolidada:
    ordenadas = vigentes(observaciones)
    if not ordenadas:
        raise ValueError("No se consolida una reserva sin observaciones")
    base = ordenadas[0]
    origen: dict[str, Fuente] = {ORIGEN_DE_LA_ESTRUCTURA: base.fuente,
                                 CAMPO_CANCELADA: base.fuente}

    # Regla 2: valor por campo.
    aportantes: list[list[ObservacionRegistrada]] = []
    segmentos: list[dict[str, Any]] = []
    for i in range(len(base.observacion.segmentos)):
        alineadas = [o for o in ordenadas if _alineada(o.observacion, base.observacion, i)]
        valores: dict[str, Any] = {}
        for registrada in alineadas:
            for ruta, valor in hojas(_segmento(registrada.observacion, i)).items():
                if valor is not None and ruta not in valores:
                    valores[ruta] = valor
                    origen[f"segmentos[{i}].{ruta}"] = registrada.fuente
        aportantes.append(alineadas)
        segmentos.append(_armar(valores))

    # Regla 3: cancelación.
    cancelada = base.observacion.cancelada

    # Regla 4: campos fijados y conflictos.
    conflictos: list[ConflictoDeFuentes] = []
    fijados_por_segmento: dict[int, list[str]] = {}
    for campo in sorted(fijados):
        fijado = fijados[campo]
        if campo == CAMPO_CANCELADA:
            posteriores = [o for o in ordenadas if o.version_de_fuente > fijado.fijado_en]
            if fijado.valor is False and any(o.fuente == Fuente.PROVEEDOR and o.observacion.cancelada
                                             for o in posteriores):
                cancelada, origen[campo] = True, Fuente.PROVEEDOR
                continue
            disputa = _disputa(fijado, [(o, o.observacion.cancelada) for o in posteriores])
            cancelada, origen[campo] = fijado.valor, Fuente.MANUAL
        else:
            coincidencia = _CAMPO_DE_SEGMENTO.match(campo)
            i, ruta = int(coincidencia[1]), coincidencia[2]
            if i >= len(segmentos) or ruta.split(".")[0] in _NO_FIJABLES:
                continue  # la estructura cambió y el campo ya no existe: no hay qué fijar
            if ruta.startswith("detalle.") and not _admite(registro, segmentos[i], ruta, fijado.valor):
                continue  # el segmento ya no es del tipo para el que se fijó el valor
            disputa = _disputa(fijado, [(o, _leer(_segmento(o.observacion, i), ruta))
                                        for o in aportantes[i]
                                        if o.version_de_fuente > fijado.fijado_en])
            _asignar(segmentos[i], ruta, fijado.valor)
            origen[campo] = Fuente.MANUAL
            fijados_por_segmento.setdefault(i, []).append(ruta)
        if disputa:
            conflictos.append(ConflictoDeFuentes(
                id=uuid5(reserva_id, f"conflicto/{campo}/{instante_a_texto(fijado.fijado_en)}"),
                campo=campo,
                valores=(ValorEnDisputa(Fuente.MANUAL, fijado.valor, fijado.fijado_en), *disputa),
            ))

    for i, segmento in enumerate(segmentos):
        if cancelada:
            segmento["estado"] = "cancelado"
        else:
            segmento.setdefault("estado", "confirmado")
        segmento["id"] = str(uuid5(reserva_id, f"segmento/{i}"))
        segmento["orden"] = i
        if i in fijados_por_segmento:
            segmento["fijados"] = sorted(fijados_por_segmento[i])

    return VistaConsolidada(segmentos=tuple(segmentos), cancelada=cancelada,
                            conflictos=tuple(conflictos), origen=origen)


def _admite(registro: RegistroDeTipos, segmento: Mapping[str, Any], ruta: str, valor: Any) -> bool:
    """El detalle del segmento sigue validando contra su descriptor con el valor fijado."""
    detalle = copy.deepcopy(dict(segmento.get("detalle", {})))
    _asignar(detalle, ruta.removeprefix("detalle."), valor)
    return not registro.errores_de_detalle(segmento["tipo"], segmento["versionTipo"], detalle)


def _disputa(fijado: Fijado, candidatos: list[tuple[ObservacionRegistrada, Any]]) -> list[ValorEnDisputa]:
    """Valores distintos del fijado, uno por fuente automática: el de su observación vigente, si
    es posterior al fijado e informa el campo."""
    vistas: set[Fuente] = set()
    valores = []
    for registrada, valor in candidatos:  # ya vienen en orden de precedencia
        if registrada.fuente == Fuente.MANUAL or valor is None or registrada.fuente in vistas:
            continue
        vistas.add(registrada.fuente)
        if valor != fijado.valor:
            valores.append(ValorEnDisputa(registrada.fuente, copy.deepcopy(valor),
                                          registrada.version_de_fuente))
    return valores


# --- cambios entre dos vistas ----------------------------------------------------------------

@dataclass(frozen=True)
class Cambio:
    """Un elemento de `cambios` de `ReservaActualizada` (AsyncAPI)."""

    campo: str
    anterior: Any
    nuevo: Any
    fuente: Fuente

    def a_dict(self) -> dict[str, Any]:
        datos: dict[str, Any] = {"campo": self.campo, "fuente": self.fuente.value}
        if self.anterior is not None:
            datos["anterior"] = self.anterior
        if self.nuevo is not None:
            datos["nuevo"] = self.nuevo
        return datos


def _plana(vista: VistaConsolidada) -> dict[str, Any]:
    plana: dict[str, Any] = {CAMPO_CANCELADA: vista.cancelada}
    for i, segmento in enumerate(vista.segmentos):
        propios = {k: v for k, v in segmento.items() if k not in _DERIVADOS}
        plana.update({f"segmentos[{i}].{ruta}": valor for ruta, valor in hojas(propios).items()})
    return plana


def _origen(vista: VistaConsolidada, campo: str) -> Fuente:
    """La fuente de un campo, o la del campo más cercano que lo contiene."""
    ruta = campo
    while ruta:
        if ruta in vista.origen:
            return vista.origen[ruta]
        ruta = ruta.rpartition(".")[0]
    return vista.origen[ORIGEN_DE_LA_ESTRUCTURA]


def diferencias(anterior: VistaConsolidada, nueva: VistaConsolidada) -> tuple[Cambio, ...]:
    antes, despues = _plana(anterior), _plana(nueva)
    return tuple(
        Cambio(campo, antes.get(campo), despues.get(campo), _origen(nueva, campo))
        for campo in sorted(antes.keys() | despues.keys())
        if antes.get(campo) != despues.get(campo)
    )


@dataclass(frozen=True)
class Consolidacion:
    """Lo que cambió al reconsolidar; de acá salen los eventos de dominio (paso 4)."""

    cambios: tuple[Cambio, ...]
    conflictos_nuevos: tuple[ConflictoDeFuentes, ...]
    estado_anterior: EstadoReserva | None
    estado: EstadoReserva

    @property
    def cancelada_ahora(self) -> bool:
        """La reserva pasó a `Cancelada` (se publica `ReservaCancelada`). Se mide por el estado y
        no por la vista: una reserva por confirmar no se cancela con datos de banda media."""
        return self.estado == EstadoReserva.CANCELADA != self.estado_anterior


def reconsolidar(reserva: Reserva) -> Consolidacion:
    """Recalcula la vista de la reserva a partir de sus entradas y la guarda en el agregado.

    Una reserva recién creada no informa cambios campo por campo: todo es nuevo.
    """
    anterior, estado_anterior = (reserva.vista, reserva.estado_consolidado) if reserva.consolidada \
        else (None, None)
    nueva = consolidar(reserva.id, reserva.observaciones, reserva.fijados, reserva.registro)
    reserva.establecer_vista(nueva)
    if anterior is None:
        return Consolidacion((), nueva.conflictos, None, reserva.estado)
    previos = {c.id for c in anterior.conflictos}
    return Consolidacion(diferencias(anterior, nueva),
                         tuple(c for c in nueva.conflictos if c.id not in previos),
                         estado_anterior, reserva.estado)
