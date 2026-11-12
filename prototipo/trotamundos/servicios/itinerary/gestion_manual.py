"""Módulo `gestion-manual` (vista N2): los comandos del usuario sobre sus reservas (RF-06).

Alta, edición, baja, confirmación o descarte de una reserva de banda media y resolución de un
conflicto. Todo pasa por las reglas de `fusion` (regla I2): la edición del usuario es una
observación más, de fuente manual, y **fija** los campos que toca (ADR-0013).

Cada comando trabaja dentro de la transacción de quien lo llama (a través del puerto
`RepositorioDeReservas`) y devuelve el estado resultante con los eventos de dominio a publicar.
Los errores son `ErrorDeComando`, cada uno con el código HTTP que le corresponde en el contrato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import (
    Fuente,
    Identificador,
    ObservacionCanonica,
    SegmentoObservado,
    instante_a_texto,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, TipoNoRegistrado
from trotamundos.servicios.itinerary.fusion.consolidacion import hojas, reconsolidar
from trotamundos.servicios.itinerary.fusion.eventos import Causa, eventos_del_cambio
from trotamundos.servicios.itinerary.fusion.identidad import (
    MOTIVO_IDENTIFICADOR,
    PosibleDuplicado,
    RepositorioDeReservas,
    ingerir,
    persistir,
)
from trotamundos.servicios.itinerary.reservas import (
    EstadoReserva,
    Fijado,
    ObservacionRegistrada,
    Reserva,
    TransicionInvalida,
)

# Lo que una edición no toca: lo calcula la consolidación o es la estructura del tramo.
_NO_EDITABLES = ("id", "orden", "fijados", "tipo", "versionTipo", "estado")


class ErrorDeComando(Exception):
    status = 500

    def __init__(self, titulo: str, detalle: str | None = None,
                 errores: list[dict[str, str]] | None = None):
        super().__init__(detalle or titulo)
        self.titulo, self.detalle, self.errores = titulo, detalle, errores


class NoEncontrada(ErrorDeComando):
    """La reserva no existe, está dada de baja o es de otro usuario (el mismo 404, ADR-0028)."""

    status = 404

    def __init__(self, detalle: str | None = None):
        super().__init__("No encontrado", detalle)


class SolicitudInvalida(ErrorDeComando):
    status = 400

    def __init__(self, detalle: str, errores: list[dict[str, str]] | None = None):
        super().__init__("Solicitud inválida", detalle, errores)


class ConflictoDeComando(ErrorDeComando):
    """Versión desactualizada o estado que no admite el comando."""

    status = 409

    def __init__(self, detalle: str):
        super().__init__("Conflicto", detalle)


@dataclass(frozen=True)
class Contexto:
    """Con qué trabaja un comando: la transacción (por el repositorio), el usuario y la causa."""

    repositorio: RepositorioDeReservas
    registro: RegistroDeTipos
    usuario_id: UUID
    ahora: datetime
    causa: Causa = field(default_factory=Causa)
    nuevo_id: Callable[[], UUID] = uuid4


@dataclass(frozen=True)
class Resultado:
    reserva: Reserva
    eventos: tuple[Evento, ...]
    posibles_duplicados: tuple[PosibleDuplicado, ...] = ()

    def cuerpo(self, version_usuario: int) -> dict[str, Any]:
        """`ResultadoComandoReserva` de `comun.yaml`. `viajeId` lo agrega `viajes` (paso 5)."""
        cuerpo: dict[str, Any] = {"reserva": self.reserva.a_dict(), "versionUsuario": version_usuario}
        if self.posibles_duplicados:
            cuerpo["posiblesDuplicados"] = [d.a_dict() for d in self.posibles_duplicados]
        return cuerpo


# --- comandos --------------------------------------------------------------------------------

def crear(ctx: Contexto, cuerpo: Mapping[str, Any], clave: UUID) -> Resultado:
    """Alta manual (UC-4). Si coincide por identificadores con una reserva existente, se agrega a
    esa; si no, se crea, y las parecidas vuelven como sugerencia (ADR-0013)."""
    segmentos = []
    for i, nuevo in enumerate(cuerpo["segmentos"]):
        try:
            version = ctx.registro.obtener(nuevo["tipo"]).version  # el alta usa la vigente
        except TipoNoRegistrado as error:
            raise SolicitudInvalida(str(error), [{"campo": f"segmentos[{i}].tipo",
                                                  "mensaje": "tipo de segmento no registrado"}])
        segmentos.append({**nuevo, "versionTipo": version})
    observacion = _observacion_manual(ctx, f"alta/{clave}", cuerpo.get("identificadores", []),
                                      segmentos)

    resultado = ingerir(ctx.repositorio, ctx.usuario_id, observacion, ctx.ahora, ctx.nuevo_id)
    persistir(ctx.repositorio, resultado)
    eventos = eventos_del_cambio(
        resultado.reserva, resultado.consolidacion, Fuente.MANUAL, ctx.causa, ctx.ahora,
        hubo_cambio=resultado.creada or resultado.aplicada or bool(resultado.unificadas),
        creada=resultado.creada, unificadas=resultado.unificadas)
    return Resultado(resultado.reserva, tuple(eventos), resultado.posibles_duplicados)


def editar(ctx: Contexto, reserva_id: UUID, cuerpo: Mapping[str, Any]) -> Resultado:
    """Edición manual: cada campo que cambia queda fijado (ADR-0013). No agrega, quita ni cambia
    el tipo de los tramos; los identificadores nuevos se suman a los que ya tiene."""
    reserva = _vigente(ctx, reserva_id)
    if cuerpo["version"] != reserva.version:
        raise ConflictoDeComando(f"La reserva está en la versión {reserva.version}, "
                                 f"no en la {cuerpo['version']}")

    duplicados, propios = _identificadores_nuevos(ctx, reserva, cuerpo.get("identificadores", []))
    if "segmentos" in cuerpo:
        editados = _segmentos_editados(reserva, cuerpo["segmentos"])
        observacion = _observacion_manual(
            ctx, f"edicion/{ctx.nuevo_id()}",
            [i.a_dict() for i in sorted(reserva.identificadores | propios,
                                        key=lambda i: (i.emisor, i.codigo))],
            editados)
        reserva.registrar(observacion)
        for i, (actual, editado) in enumerate(zip(reserva.vista.segmentos, editados)):
            antes = hojas(_editable(actual))
            for ruta, valor in hojas(_editable(editado)).items():
                if antes.get(ruta) != valor:
                    reserva.fijar(Fijado(f"segmentos[{i}].{ruta}", valor, ctx.ahora))
    reserva.agregar_identificadores(propios)
    return _cerrar(ctx, reserva, duplicados)


def dar_de_baja(ctx: Contexto, reserva_id: UUID) -> Resultado:
    """Baja manual (RF-06): la reserva pasa a `Descartada` y sale de todas las vistas."""
    reserva = _vigente(ctx, reserva_id)
    reserva.dar_de_baja()
    return _cerrar(ctx, reserva)


def confirmar(ctx: Contexto, reserva_id: UUID, cuerpo: Mapping[str, Any]) -> Resultado:
    """Confirma o descarta una reserva de banda media (ADR-0015). La corrección opcional se
    aplica como una edición y por sí sola ya confirma: el usuario «confirma, corrige o descarta»."""
    reserva = _vigente(ctx, reserva_id)
    if reserva.estado != EstadoReserva.POR_CONFIRMAR:
        raise ConflictoDeComando(f"La reserva está {reserva.estado}: solo se confirma o descarta "
                                 "una reserva PorConfirmar")
    if "correccion" in cuerpo:
        if cuerpo["decision"] != "confirmar":
            raise SolicitudInvalida("Una corrección solo acompaña a la decisión confirmar",
                                    [{"campo": "correccion", "mensaje": "no corresponde al descartar"}])
        return editar(ctx, reserva_id, cuerpo["correccion"])
    try:
        reserva.confirmar() if cuerpo["decision"] == "confirmar" else reserva.descartar()
    except TransicionInvalida as error:
        raise ConflictoDeComando(str(error)) from error
    return _cerrar(ctx, reserva)


def resolver_conflicto(ctx: Contexto, reserva_id: UUID, conflicto_id: UUID,
                       cuerpo: Mapping[str, Any]) -> Resultado:
    """`mantenerFijado` conserva el valor del usuario; `aceptarFuente` toma el de `fuente`."""
    reserva = _vigente(ctx, reserva_id)
    conflicto = next((c for c in reserva.vista.conflictos if c.id == UUID(str(conflicto_id))), None)
    if conflicto is None:
        raise NoEncontrada("No hay un conflicto abierto con ese id")
    aceptar = None
    if cuerpo["eleccion"] == "aceptarFuente":
        if "fuente" not in cuerpo:
            raise SolicitudInvalida("aceptarFuente necesita la fuente elegida",
                                    [{"campo": "fuente", "mensaje": "es obligatoria con aceptarFuente"}])
        aceptar = Fuente(cuerpo["fuente"])
        if aceptar not in {v.fuente for v in conflicto.valores}:
            raise SolicitudInvalida(f"La fuente {aceptar} no participa del conflicto")
    reserva.resolver_conflicto(conflicto.id, aceptar=aceptar, ahora=ctx.ahora)
    return _cerrar(ctx, reserva)


# --- auxiliares ------------------------------------------------------------------------------

def _vigente(ctx: Contexto, reserva_id: UUID) -> Reserva:
    reserva = ctx.repositorio.obtener(ctx.usuario_id, UUID(str(reserva_id)))
    if reserva is None or reserva.estado == EstadoReserva.DESCARTADA:
        raise NoEncontrada()
    return reserva


def _cerrar(ctx: Contexto, reserva: Reserva,
            duplicados: tuple[PosibleDuplicado, ...] = ()) -> Resultado:
    version = reserva.version
    consolidacion = reconsolidar(reserva)
    ctx.repositorio.guardar(reserva)
    eventos = eventos_del_cambio(reserva, consolidacion, Fuente.MANUAL, ctx.causa, ctx.ahora,
                                 hubo_cambio=reserva.version != version)
    return Resultado(reserva, tuple(eventos), duplicados)


def _observacion_manual(ctx: Contexto, id_de_fuente: str, identificadores: list,
                        segmentos: list) -> ObservacionRegistrada:
    datos = {"fuente": Fuente.MANUAL.value, "idDeFuente": id_de_fuente,
             "versionDeFuente": instante_a_texto(ctx.ahora),
             "identificadores": list(identificadores), "segmentos": segmentos}
    try:
        ctx.registro.validar_observacion(datos)
    except ErrorDeContrato as error:
        raise SolicitudInvalida("La reserva no cumple el contrato o el esquema de su tipo",
                                [_error(e) for e in error.errores]) from error
    return ObservacionRegistrada(ObservacionCanonica.desde_dict(datos))


def _error(texto: str) -> dict[str, str]:
    campo, _, mensaje = texto.partition(": ")
    return {"campo": campo.removeprefix("$."), "mensaje": mensaje}


def _editable(segmento: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in segmento.items() if k not in _NO_EDITABLES}


def _segmentos_editados(reserva: Reserva, cambios: list[Mapping[str, Any]]) -> list[dict]:
    """Cada tramo editado, completo y normalizado como lo escribe el modelo canónico."""
    actuales = reserva.vista.segmentos
    if len(cambios) != len(actuales):
        raise SolicitudInvalida("Una edición no agrega ni quita tramos: dar de baja la reserva y "
                                "cargarla de nuevo")
    editados = []
    for i, (actual, cambio) in enumerate(zip(actuales, cambios)):
        if "id" in cambio and cambio["id"] != actual["id"]:
            raise SolicitudInvalida(f"El tramo {i} no es {cambio['id']}: los tramos van en orden")
        if cambio["tipo"] != actual["tipo"]:
            raise SolicitudInvalida(f"El tramo {i} es de tipo {actual['tipo']}: una edición no "
                                    "cambia el tipo")
        segmento = {"tipo": actual["tipo"], "versionTipo": actual["versionTipo"],
                    "estado": actual["estado"],
                    **_editable(actual), **{k: v for k, v in cambio.items() if k not in _NO_EDITABLES}}
        try:
            editados.append(SegmentoObservado.desde_dict(segmento).a_dict())
        except (KeyError, ValueError) as error:
            raise SolicitudInvalida(f"El tramo {i} no es válido: {error}") from error
    return editados


def _identificadores_nuevos(ctx: Contexto, reserva: Reserva, pedidos: list[Mapping[str, str]]
                            ) -> tuple[tuple[PosibleDuplicado, ...], set[Identificador]]:
    """Los identificadores que se suman a la reserva. Uno que ya es de otra reserva no se mueve:
    esa otra vuelve como posible duplicado (unificar con una manual pide confirmación)."""
    propios: set[Identificador] = set()
    duplicados: dict[UUID, PosibleDuplicado] = {}
    for pedido in pedidos:
        identificador = Identificador.desde_dict(pedido)
        if identificador in reserva.identificadores:
            continue
        duena = ctx.repositorio.por_identificador(ctx.usuario_id, identificador)
        if duena is None:
            propios.add(identificador)
        elif duena.id != reserva.id and not duena.descartada:  # no sugerir lo que no se ve
            duplicados[duena.id] = PosibleDuplicado(duena.id, MOTIVO_IDENTIFICADOR)
    return tuple(duplicados.values()), propios
