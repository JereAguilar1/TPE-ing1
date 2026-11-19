"""Módulo `dialogo` del asistente: atiende un turno (RF-B1, RF-B2).

Interpreta el mensaje (ADR-0037), consulta el contexto del viajero y decide si responde, propone una
acción o propone derivar (ADR-0038, ADR-0039). Nada cambia sin una `confirmacion` explícita del
`accionId` propuesto, que vence a los 10 minutos. Todos los textos salen del catálogo de mensajes.

No toca la base: recibe el estado de la sesión y devuelve el estado nuevo, y `servicio` lo guarda.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID

from trotamundos.servicios.virtual_assistant import acciones, derivacion
from trotamundos.servicios.virtual_assistant.catalogo import Mensajes
from trotamundos.servicios.virtual_assistant.contexto import (
    ItinerarioNoDisponible,
    LectorDeItinerario,
)
from trotamundos.servicios.virtual_assistant.interprete import (
    NO_ENTENDIDO,
    ContextoDelViajero,
    InterpreteDeIntenciones,
    Interpretacion,
    proximo_tramo,
    referencia_de,
)

UMBRAL_DE_CONFIANZA = 0.6  # el umbral bajo de ADR-0015, supuesto a calibrar (ADR-0037)
VIGENCIA_DE_PROPUESTA = timedelta(minutes=10)  # supuesto a calibrar (ADR-0038)
CONFIRMACION = "confirmacion"
_SIN_ITINERARIO = frozenset({"saludo", "ayuda", CONFIRMACION})  # no necesitan leer `itinerary`


class AccionNoVigente(Exception):
    """La confirmación es de una acción que no existe, ya se ejecutó o venció (`409`)."""


class ViajeAjeno(Exception):
    """El `viajeId` del mensaje no es un viaje del viajero (`404`)."""


@dataclass(frozen=True)
class EstadoDeSesion:
    viaje_id: str | None = None
    no_entendidos: int = 0
    accion: Mapping[str, Any] | None = None  # `AccionPropuesta` con sus `datos` para ejecutarla
    turnos: Sequence[Mapping[str, Any]] = ()  # los anteriores, para la síntesis de un caso


@dataclass(frozen=True)
class ResultadoDelTurno:
    respuesta: dict[str, Any]  # `Respuesta` de `virtual-assistant.yaml`
    estado: EstadoDeSesion
    texto_del_viajero: str


@dataclass
class _Salida:
    """Lo que arma cada intención."""

    mensajes: list[str] = field(default_factory=list)
    propuesta: dict[str, Any] | None = None
    realizada: dict[str, Any] | None = None
    viaje_id: str | None = None
    restaurar: bool = False  # el servicio no respondió: la acción sigue pendiente


@dataclass(frozen=True)
class _Contexto:
    """Lo que se leyó de `itinerary` para este turno (`panel` es `None` si no respondió)."""

    usuario_id: str
    authorization: str
    ahora: datetime
    estado: EstadoDeSesion
    panel: Mapping[str, Any] | None
    viaje_en_foco: Mapping[str, Any] | None

    @property
    def viajes(self) -> list[Mapping[str, Any]]:
        viajes = list(self.panel["viajesActivos"]) if self.panel else []
        if self.viaje_en_foco and all(v["id"] != self.viaje_en_foco["id"] for v in viajes):
            viajes.append(self.viaje_en_foco)
        return viajes

    @property
    def por_confirmar(self) -> list[Mapping[str, Any]]:
        return list(self.panel["porConfirmar"]) if self.panel else []

    def viaje(self, viaje_id: str | None) -> Mapping[str, Any] | None:
        return next((v for v in self.viajes if v["id"] == viaje_id), None)

    def reservas(self, viaje_id: str | None = None) -> list[Mapping[str, Any]]:
        viajes = [self.viaje(viaje_id)] if viaje_id else self.viajes
        return [r for v in viajes if v for r in v["reservas"]]

    def reserva(self, reserva_id: str | None) -> Mapping[str, Any] | None:
        return next((r for r in [*self.reservas(), *self.por_confirmar] if r["id"] == reserva_id),
                    None)

    def viaje_de(self, reserva_id: str | None) -> str | None:
        return next((v["id"] for v in self.viajes
                     if any(r["id"] == reserva_id for r in v["reservas"])), None)


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


class Dialogo:
    def __init__(self, interprete: InterpreteDeIntenciones, lector: LectorDeItinerario,
                 escritor: acciones.EscritorDeItinerario, abridor: derivacion.AbridorDeCasos,
                 disrupciones: Callable[[str, str], Mapping[str, Any] | None],
                 mensajes: Mensajes, nuevo_id: Callable[[], UUID]):
        self._interprete = interprete
        self._lector = lector
        self._escritor = escritor
        self._abridor = abridor
        self._disrupciones = disrupciones  # (usuario, reserva) -> la disrupción conocida o None
        self._m = mensajes
        self._nuevo_id = nuevo_id

    # --- un turno ----------------------------------------------------------------------------

    def atender(self, usuario_id: UUID | str, authorization: str, estado: EstadoDeSesion,
                mensaje: Mapping[str, Any], ahora: datetime) -> ResultadoDelTurno:
        """Lanza `ViajeAjeno` (`404`) o `AccionNoVigente` (`409`); el resto se responde."""
        usuario = str(usuario_id)
        if "viajeId" in mensaje:
            estado = replace(estado, viaje_id=self._viaje_propio(usuario, mensaje["viajeId"]))
        if "confirmacion" in mensaje:
            return self._confirmacion(usuario, authorization, estado, mensaje, ahora)
        return self._texto(usuario, authorization, estado, mensaje["texto"], ahora)

    def _viaje_propio(self, usuario: str, viaje_id: str) -> str:
        try:
            if self._lector.viaje(usuario, viaje_id) is None:
                raise ViajeAjeno()
        except ItinerarioNoDisponible:
            pass  # cada lectura posterior va en nombre del viajero: un viaje ajeno no se ve igual
        return str(viaje_id)

    def _resultado(self, intencion: str, salida: _Salida, estado: EstadoDeSesion,
                   texto: str, ahora: datetime, no_entendidos: int) -> ResultadoDelTurno:
        accion = estado.accion
        if salida.propuesta is not None:
            accion = salida.propuesta
        viaje_id = salida.viaje_id or estado.viaje_id
        respuesta: dict[str, Any] = {"intencion": intencion, "mensajes": salida.mensajes}
        if viaje_id:
            respuesta["viajeId"] = viaje_id
        if salida.propuesta is not None:
            respuesta["accionPropuesta"] = {k: v for k, v in salida.propuesta.items() if k != "datos"}
        if salida.realizada is not None:
            respuesta["accionRealizada"] = salida.realizada
        nuevo = replace(estado, viaje_id=viaje_id, no_entendidos=no_entendidos, accion=accion)
        return ResultadoDelTurno(respuesta, nuevo, texto)

    # --- confirmaciones (ADR-0038) -----------------------------------------------------------

    def _confirmacion(self, usuario: str, authorization: str, estado: EstadoDeSesion,
                      mensaje: Mapping[str, Any], ahora: datetime) -> ResultadoDelTurno:
        confirmacion = mensaje["confirmacion"]
        accion = estado.accion
        if (accion is None or accion["id"] != str(confirmacion["accionId"])
                or datetime.fromisoformat(accion["venceEn"]) <= ahora):
            raise AccionNoVigente()
        sin_accion = replace(estado, accion=None)
        decision = confirmacion["decision"]
        texto = mensaje.get("texto") or self._m.texto(
            "turno_confirmar" if decision == "confirmar" else "turno_rechazar")
        if decision == "rechazar":
            return self._resultado(CONFIRMACION, _Salida([self._m.texto("rechazada")]), sin_accion,
                                   texto, ahora, estado.no_entendidos)
        if accion["tipo"] == derivacion.DERIVAR:
            salida = self._derivar(authorization, accion)
        else:
            salida = self._cambiar_itinerario(usuario, accion, ahora)
        if salida.restaurar:
            sin_accion = replace(sin_accion, accion=accion)
        no_entendidos = 0 if salida.realizada else estado.no_entendidos
        return self._resultado(CONFIRMACION, salida, sin_accion, texto, ahora, no_entendidos)

    def _derivar(self, authorization: str, accion: Mapping[str, Any]) -> _Salida:
        try:
            caso = derivacion.abrir_caso(self._abridor, authorization, accion["id"], accion["datos"])
        except derivacion.SinAgencia:
            return _Salida([self._m.texto("sin_agencia")])
        except derivacion.ViajeNoEncontrado:
            return _Salida([self._m.texto("viaje_ya_no_esta")])
        except derivacion.SoporteNoDisponible:
            return _Salida([self._m.texto("servicio_no_disponible")], restaurar=True)
        clave = "derivado" if caso["estado"] == "Derivado" else "derivado_pendiente"
        return _Salida([self._m.texto(clave, agencia=caso["agencia"])],
                       realizada={"tipo": derivacion.DERIVAR, "casoId": caso["id"],
                                  "agencia": caso["agencia"]})

    def _cambiar_itinerario(self, usuario: str, accion: Mapping[str, Any],
                            ahora: datetime) -> _Salida:
        datos, tipo = accion["datos"], accion["tipo"]
        try:
            if tipo == acciones.CORREGIR:
                datos = {**datos, "edicion": self._edicion_vigente(usuario, datos)}
            acciones.ejecutar(self._escritor, usuario, tipo, datos)
        except ItinerarioNoDisponible:
            return _Salida([self._m.texto("servicio_no_disponible")], restaurar=True)
        except acciones.EscrituraNoDisponible:
            return _Salida([self._m.texto("servicio_no_disponible")], restaurar=True)
        except acciones.ReservaInexistente:
            return _Salida([self._m.texto("reserva_ya_no_esta")])
        except acciones.ReservaCambiada:
            if tipo == acciones.CORREGIR:
                return self._volver_a_proponer(usuario, accion, ahora)
            clave = "ya_no_por_confirmar" if tipo != acciones.RESOLVER else "conflicto_ya_resuelto"
            return _Salida([self._m.texto(clave)])
        realizada = {"tipo": tipo, "reservaId": datos["reservaId"]}
        textos = {acciones.CORREGIR: "corregida", acciones.CONFIRMAR: "reserva_confirmada",
                  acciones.DESCARTAR: "reserva_descartada", acciones.RESOLVER: "conflicto_resuelto"}
        return _Salida([self._m.texto(textos[tipo], **datos["textos"])], realizada=realizada)

    def _edicion_vigente(self, usuario: str, datos: Mapping[str, Any]) -> dict[str, Any]:
        """La edición de una corrección confirmada, armada recién ahora con la reserva leída de
        `itinerary`: la propuesta guarda solo qué tramo, a qué hora y la `version` que vio el
        viajero, no una copia del itinerario (ADR-0040). Si la reserva cambió desde entonces, es el
        mismo caso que un `409` (ADR-0038)."""
        viaje = self._lector.viaje(usuario, datos["viajeId"])
        reserva = next((r for r in (viaje or {}).get("reservas", [])
                        if r["id"] == datos["reservaId"]), None)
        if reserva is None or acciones.segmento_de(reserva, datos["segmentoId"]) is None:
            raise acciones.ReservaInexistente(datos["reservaId"])
        edicion = acciones.edicion_corregida(reserva, datos["segmentoId"],
                                             _instante(datos["inicio"]))
        if reserva["version"] != datos["version"] or edicion is None:
            raise acciones.ReservaCambiada(datos["reservaId"])
        return edicion

    def _volver_a_proponer(self, usuario: str, accion: Mapping[str, Any],
                           ahora: datetime) -> _Salida:
        """`409` de `PUT /reservas/{id}`: relee la reserva y propone lo mismo con la versión
        actual; nunca pisa un cambio que el viajero no vio."""
        datos = accion["datos"]
        try:
            viaje = self._lector.viaje(usuario, datos["viajeId"])
        except ItinerarioNoDisponible:
            return _Salida([self._m.texto("itinerario_no_disponible")])
        reserva = next((r for r in (viaje or {}).get("reservas", [])
                        if r["id"] == datos["reservaId"]), None)
        segmento = acciones.segmento_de(reserva, datos["segmentoId"]) if reserva else None
        if segmento is None:
            return _Salida([self._m.texto("reserva_ya_no_esta")])
        salida = self._proponer_correccion(reserva, segmento, _instante(datos["inicio"]),
                                           datos["viajeId"], ahora)
        salida.mensajes.insert(0, self._m.texto("reserva_cambio"))
        return salida

    # --- mensajes de texto -------------------------------------------------------------------

    def _texto(self, usuario: str, authorization: str, estado: EstadoDeSesion, texto: str,
               ahora: datetime) -> ResultadoDelTurno:
        ctx = self._leer_contexto(usuario, authorization, estado, ahora)
        estado = ctx.estado  # sin el viaje en foco, si ya no es del viajero
        interpretacion = self._interprete.interpretar(texto, ContextoDelViajero(
            ahora=ahora, viajes=ctx.viajes,
            reservas=ctx.reservas(estado.viaje_id if ctx.viaje(estado.viaje_id) else None),
            por_confirmar=ctx.por_confirmar))
        if interpretacion.confianza < UMBRAL_DE_CONFIANZA:
            interpretacion = Interpretacion(NO_ENTENDIDO, interpretacion.confianza)
        intencion = interpretacion.intencion
        no_entendidos = estado.no_entendidos + 1 if intencion == NO_ENTENDIDO else 0
        primer_no_entendido = (intencion == NO_ENTENDIDO
                               and no_entendidos < derivacion.NO_ENTENDIDOS_PARA_DERIVAR)
        if ctx.panel is None and intencion not in _SIN_ITINERARIO and not primer_no_entendido:
            salida = _Salida([self._m.texto("itinerario_no_disponible")])
        else:
            salida = self._segun_intencion(ctx, interpretacion, texto, no_entendidos)
        return self._resultado(intencion, salida, estado, texto, ahora, no_entendidos)

    def _leer_contexto(self, usuario: str, authorization: str, estado: EstadoDeSesion,
                       ahora: datetime) -> _Contexto:
        """Lee el panel y, si el viaje en foco no está entre los activos, ese viaje. Un viaje en foco
        que ya no existe (o no es del viajero) deja de estar en foco, para no quedar pegado a él."""
        try:
            panel = self._lector.panel(usuario)
            en_foco = None
            if estado.viaje_id and all(v["id"] != estado.viaje_id for v in panel["viajesActivos"]):
                en_foco = self._lector.viaje(usuario, estado.viaje_id)
                if en_foco is None:
                    estado = replace(estado, viaje_id=None)
        except ItinerarioNoDisponible:
            panel, en_foco = None, None
        return _Contexto(usuario, authorization, ahora, estado, panel, en_foco)

    def _segun_intencion(self, ctx: _Contexto, i: Interpretacion, texto: str,
                         no_entendidos: int) -> _Salida:
        if i.intencion == "ayuda" and i.entidades.get("tema") == "caso":
            return _Salida([self._m.texto("seguimiento_del_caso")])
        if i.intencion in ("saludo", "ayuda"):
            return _Salida([self._m.texto(i.intencion)])
        if i.intencion == CONFIRMACION:
            return self._confirmacion_por_texto(ctx)
        if i.intencion == NO_ENTENDIDO:
            disparador = derivacion.disparador(NO_ENTENDIDO, {}, no_entendidos, None)
            if disparador is None:
                return _Salida([self._m.texto("no_entendido")])
            anteriores = [t["texto"] for t in ctx.estado.turnos
                          if t["autor"] == "viajero" and t.get("intencion") == NO_ENTENDIDO]
            pedido = self._m.lista(f"«{t}»" for t in [*anteriores[-1:], texto])
            return self._proponer_derivacion(ctx, disparador, pedido, None,
                                             [self._m.texto("no_entendido_otra_vez")])
        if i.intencion in ("cambioAnteProveedor", "pedirAgencia"):
            disparador = derivacion.disparador(i.intencion, i.entidades, no_entendidos, None)
            reserva = ctx.reserva(i.reserva_id) if i.por_referencia else None
            previos = ([self._m.texto("derivar_cambio_ante_proveedor")]
                       if i.intencion == "cambioAnteProveedor" else [])
            viaje_id = i.viaje_id or (ctx.viaje_de(reserva["id"]) if reserva else None)
            return self._proponer_derivacion(ctx, disparador, texto, reserva, previos, viaje_id)
        if i.intencion == "estadoDelViaje":
            return self._estado_del_viaje(ctx, i, texto)
        if i.intencion == "proximoTramo":
            return self._proximo_tramo(ctx, i, texto)
        if i.intencion == "corregirHorario":
            return self._corregir(ctx, i)
        if i.intencion == "confirmarReserva":
            return self._reserva_por_confirmar(ctx, i)
        return self._conflicto(ctx, i)  # resolverConflicto

    def _confirmacion_por_texto(self, ctx: _Contexto) -> _Salida:
        """Un «sí» escrito no alcanza: la confirmación es explícita, con el `accionId`."""
        accion = ctx.estado.accion
        if accion is None or datetime.fromisoformat(accion["venceEn"]) <= ctx.ahora:
            return _Salida([self._m.texto("nada_para_confirmar")])
        return _Salida([self._m.texto("confirma_con_el_boton", resumen=accion["resumen"])],
                       propuesta=dict(accion))

    # --- consultas (ADR-0038) ----------------------------------------------------------------

    def _elegir_viaje(self, ctx: _Contexto, i: Interpretacion) -> tuple[Mapping[str, Any] | None,
                                                                         _Salida | None]:
        viaje_id = (i.viaje_id or (ctx.viaje_de(i.reserva_id) if i.por_referencia else None)
                    or ctx.estado.viaje_id)
        if viaje_id is None and len(ctx.viajes) == 1:
            viaje_id = ctx.viajes[0]["id"]
        if viaje_id is not None:
            viaje = ctx.viaje(viaje_id)
            return (viaje, None) if viaje else (None, _Salida([self._m.texto("no_encuentro_viaje")]))
        if not ctx.viajes:
            return None, _Salida([self._m.texto("sin_viajes")])
        return None, _Salida([self._m.texto("elegi_viaje", viajes=self._titulos(ctx.viajes))])

    def _titulos(self, viajes: Sequence[Mapping[str, Any]]) -> str:
        return self._m.lista(f"«{v['titulo']}»" for v in viajes)

    @staticmethod
    def _zona_del_viaje(viaje: Mapping[str, Any]) -> str:
        for reserva in viaje["reservas"]:
            for segmento in reserva["segmentos"]:
                return segmento["inicio"]["zonaHoraria"]
        return viaje.get("destinoPrincipal", {}).get("zonaHoraria", "UTC")

    def _estado_del_viaje(self, ctx: _Contexto, i: Interpretacion, texto: str) -> _Salida:
        viaje, salida = self._elegir_viaje(ctx, i)
        if viaje is None:
            return salida
        zona = self._zona_del_viaje(viaje)
        mensajes = [self._m.texto(
            "estado_del_viaje", titulo=viaje["titulo"],
            estado=self._m.texto(f"estados_de_viaje.{viaje['estado']}"),
            desde=self._m.fecha(_instante(viaje["desde"]), zona),
            hasta=self._m.fecha(_instante(viaje["hasta"]), zona), reservas=len(viaje["reservas"]))]
        if ctx.por_confirmar:
            mensajes.append(self._m.texto("estado_por_confirmar", cantidad=len(ctx.por_confirmar)))
        if ctx.panel and ctx.panel["conflictosAbiertos"]:
            mensajes.append(self._m.texto("estado_conflictos",
                                          cantidad=len(ctx.panel["conflictosAbiertos"])))
        for reserva in viaje["reservas"]:
            disrupcion = self._disrupciones(ctx.usuario_id, reserva["id"])
            if disrupcion is not None:
                mensajes.append(self._m.texto("disrupcion", proveedor=disrupcion["proveedor"],
                                              descripcion=disrupcion["descripcion"]))
        salida = _Salida(mensajes, viaje_id=viaje["id"])
        if i.por_referencia:  # pregunta por una reserva: puede tener una disrupción sin salida
            return self._quizas_derivar(ctx, i, texto, ctx.reserva(i.reserva_id), salida)
        return salida

    def _proximo_tramo(self, ctx: _Contexto, i: Interpretacion, texto: str) -> _Salida:
        reserva, segmento = ctx.reserva(i.reserva_id), None
        if reserva is not None:
            segmento = acciones.segmento_de(reserva, i.segmento_id)
        if i.viaje_id and not i.por_referencia:  # «¿cuándo sale el vuelo de Madrid?»
            proximo = proximo_tramo(ctx.reservas(i.viaje_id), ctx.ahora, i.tipo)
            reserva, segmento = proximo if proximo else (None, None)
        if segmento is None:
            return _Salida([self._m.texto("sin_proximo_tramo" if ctx.viajes else "sin_viajes")])
        salida = _Salida([self._describir_tramo(reserva, segmento)],
                         viaje_id=ctx.viaje_de(reserva["id"]))
        disrupcion = self._disrupciones(ctx.usuario_id, reserva["id"])
        if disrupcion is not None:
            salida.mensajes.append(self._m.texto("disrupcion", proveedor=disrupcion["proveedor"],
                                                 descripcion=disrupcion["descripcion"]))
        return self._quizas_derivar(ctx, i, texto, reserva, salida, disrupcion)

    def _describir_tramo(self, reserva: Mapping[str, Any], segmento: Mapping[str, Any]) -> str:
        inicio, zona = _instante(segmento["inicio"]["instante"]), segmento["inicio"]["zonaHoraria"]
        argumentos = {"tipo": self._m.tipo(segmento["tipo"]),
                      "referencia": referencia_de(reserva, segmento),
                      "fecha": self._m.fecha(inicio, zona)}
        if segmento["inicio"]["precision"] == "dia":
            return self._m.texto("proximo_tramo_dia", lugar=segmento["inicio"]["lugar"]["nombre"],
                                 **argumentos)
        return self._m.texto("proximo_tramo", hora=self._m.hora(inicio, zona),
                             comienza=self._m.comienzo(segmento["tipo"]),
                             ciudad=self._m.ciudad(zona), **argumentos)

    def _quizas_derivar(self, ctx: _Contexto, i: Interpretacion, texto: str,
                        reserva: Mapping[str, Any] | None, salida: _Salida,
                        disrupcion: Mapping[str, Any] | None = None) -> _Salida:
        """Disparador de disrupción (ADR-0039): la reserva por la que pregunta tiene una
        disrupción alta. La consulta solo propone; el caso se abre con la confirmación."""
        if reserva is None:
            return salida
        disrupcion = disrupcion or self._disrupciones(ctx.usuario_id, reserva["id"])
        if disrupcion is not None and disrupcion.get("caso_id"):  # ya se derivó: no otro caso
            salida.mensajes.append(self._m.texto("disrupcion_ya_derivada"))
            return salida
        disparador = derivacion.disparador(i.intencion, i.entidades, 0, disrupcion)
        if disparador is None:
            return salida
        derivar = self._proponer_derivacion(ctx, disparador, texto, reserva,
                                            [self._m.texto("derivar_por_disrupcion")],
                                            viaje_id=ctx.viaje_de(reserva["id"]))
        return _Salida(salida.mensajes + derivar.mensajes, propuesta=derivar.propuesta,
                       viaje_id=salida.viaje_id)

    # --- corrección del itinerario (ADR-0038) ------------------------------------------------

    def _corregir(self, ctx: _Contexto, i: Interpretacion) -> _Salida:
        reserva = ctx.reserva(i.reserva_id)
        viaje_id = ctx.viaje_de(i.reserva_id)
        segmento = acciones.segmento_de(reserva, i.segmento_id) if reserva else None
        if segmento is None or viaje_id is None:
            return _Salida([self._m.texto("no_encuentro_reserva")])
        if i.fecha is None and i.hora is None:
            return _Salida([self._m.texto("falta_fecha_u_hora")], viaje_id=viaje_id)
        inicio = acciones.nuevo_inicio(segmento, i.fecha, i.hora)
        return self._proponer_correccion(reserva, segmento, inicio, viaje_id, ctx.ahora)

    def _proponer_correccion(self, reserva: Mapping[str, Any], segmento: Mapping[str, Any],
                             inicio: datetime, viaje_id: str, ahora: datetime) -> _Salida:
        zona = segmento["inicio"]["zonaHoraria"]
        antes = _instante(segmento["inicio"]["instante"])
        textos = {"tipo": self._m.tipo(segmento["tipo"]),
                  "referencia": referencia_de(reserva, segmento),
                  "antes": self._m.fecha_y_hora(antes, zona),
                  "despues": self._m.fecha_y_hora(inicio, zona),
                  "ciudad": self._m.ciudad(zona)}
        edicion = acciones.edicion_corregida(reserva, segmento["id"], inicio)
        if edicion is None:
            return _Salida([self._m.texto("sin_cambio", tipo=textos["tipo"],
                                          referencia=textos["referencia"],
                                          fecha=self._m.fecha(antes, zona),
                                          hora=self._m.hora(antes, zona))], viaje_id=viaje_id)
        datos = {"reservaId": reserva["id"], "viajeId": viaje_id, "segmentoId": segmento["id"],
                 "inicio": inicio.isoformat(), "version": reserva["version"], "textos": textos}
        return self._proponer(acciones.CORREGIR, self._m.texto("propuesta_corregir", **textos),
                              datos, ahora, reserva_id=reserva["id"], viaje_id=viaje_id)

    # --- problemas menores (ADR-0038) --------------------------------------------------------

    def _textos_de_reserva(self, reserva: Mapping[str, Any]) -> dict[str, str]:
        segmento = reserva["segmentos"][0]
        return {"tipo": self._m.tipo(segmento["tipo"]),
                "referencia": referencia_de(reserva, segmento),
                "fecha": self._m.fecha(_instante(segmento["inicio"]["instante"]),
                                       segmento["inicio"]["zonaHoraria"])}

    def _reserva_por_confirmar(self, ctx: _Contexto, i: Interpretacion) -> _Salida:
        pendientes = ctx.por_confirmar
        elegida = next((r for r in pendientes if i.por_referencia and r["id"] == i.reserva_id), None)
        if elegida is None and len(pendientes) == 1:
            elegida = pendientes[0]
        if elegida is None:
            if not pendientes:
                return _Salida([self._m.texto("sin_por_confirmar")])
            return _Salida([self._m.texto("elegi_por_confirmar", cantidad=len(pendientes),
                                          reservas=self._m.lista(referencia_de(r) for r in pendientes))])
        textos = self._textos_de_reserva(elegida)
        decision = i.entidades.get("decision")
        if decision is None:
            return _Salida([self._m.texto("mostrar_por_confirmar", **textos)])
        tipo = acciones.CONFIRMAR if decision == "confirmar" else acciones.DESCARTAR
        clave = "propuesta_confirmar_reserva" if decision == "confirmar" else "propuesta_descartar_reserva"
        return self._proponer(tipo, self._m.texto(clave, **textos),
                              {"reservaId": elegida["id"], "textos": textos}, ctx.ahora,
                              reserva_id=elegida["id"])

    def _conflicto(self, ctx: _Contexto, i: Interpretacion) -> _Salida:
        abiertos = list(ctx.panel["conflictosAbiertos"]) if ctx.panel else []
        elegido = next((c for c in abiertos if i.por_referencia and c["reservaId"] == i.reserva_id),
                       None)
        if elegido is None and len(abiertos) == 1:
            elegido = abiertos[0]
        reserva = ctx.reserva(elegido["reservaId"]) if elegido else None
        if elegido is None or reserva is None:
            if not abiertos:
                return _Salida([self._m.texto("sin_conflictos")])
            referencias = {referencia_de(r) for c in abiertos if (r := ctx.reserva(c["reservaId"]))}
            return _Salida([self._m.texto("elegi_conflicto", cantidad=len(abiertos),
                                          reservas=self._m.lista(sorted(referencias)))])
        conflicto = elegido["conflicto"]
        mio = next((v for v in conflicto["valores"] if v["fuente"] == "manual"),
                   conflicto["valores"][0])
        otro = next(v for v in conflicto["valores"] if v is not mio)
        zona = reserva["segmentos"][0]["inicio"]["zonaHoraria"]
        textos = {**self._textos_de_reserva(reserva),
                  "mio": self._valor(mio["valor"], zona), "otro": self._valor(otro["valor"], zona),
                  "fuente": self._m.fuente(otro["fuente"])}
        eleccion = i.entidades.get("eleccion")
        if eleccion is None:
            return _Salida([self._m.texto("mostrar_conflicto", **textos)],
                           viaje_id=ctx.viaje_de(reserva["id"]))
        clave = "propuesta_mantener" if eleccion == "mantenerFijado" else "propuesta_aceptar"
        datos = {"reservaId": reserva["id"], "conflictoId": conflicto["id"], "eleccion": eleccion,
                 "fuente": otro["fuente"], "textos": textos}
        return self._proponer(acciones.RESOLVER, self._m.texto(clave, **textos), datos, ctx.ahora,
                              reserva_id=reserva["id"], viaje_id=ctx.viaje_de(reserva["id"]))

    def _valor(self, valor: Any, zona: str) -> str:
        """Un valor en disputa para el viajero: los instantes, en la zona del lugar."""
        if isinstance(valor, str):
            try:
                return self._m.fecha_y_hora(_instante(valor), zona)
            except ValueError:
                return valor
        return str(valor)

    # --- derivación (ADR-0039) ---------------------------------------------------------------

    def _proponer_derivacion(self, ctx: _Contexto, disparador: derivacion.Disparador, pedido: str,
                             reserva: Mapping[str, Any] | None, previos: list[str],
                             viaje_id: str | None = None) -> _Salida:
        viaje_id, situacion = derivacion.viaje_para_el_caso(viaje_id or ctx.estado.viaje_id,
                                                            ctx.viajes)
        if situacion == "ninguno":
            return _Salida(previos + [self._m.texto("sin_viaje_para_derivar")])
        if situacion == "varios":
            return _Salida(previos + [self._m.texto("elegi_viaje_para_derivar",
                                                    viajes=self._titulos(ctx.viajes))])
        viaje = ctx.viaje(viaje_id)
        titulo = viaje["titulo"] if viaje else viaje_id
        sintesis = derivacion.sintesis(self._m, disparador, pedido,
                                       self._textos_de_reserva(reserva) if reserva else None)
        datos = {"viajeId": viaje_id, "motivo": disparador.motivo, "descripcion": sintesis,
                 "reservaId": reserva["id"] if reserva else None, "idDeCausa": disparador.id_de_causa}
        salida = self._proponer(derivacion.DERIVAR,
                                self._m.texto("propuesta_derivar", titulo=titulo, sintesis=sintesis),
                                datos, ctx.ahora, reserva_id=datos["reservaId"], viaje_id=viaje_id)
        salida.mensajes[:0] = previos
        return salida

    # --- propuestas --------------------------------------------------------------------------

    def _proponer(self, tipo: str, resumen: str, datos: dict[str, Any], ahora: datetime, *,
                  reserva_id: str | None = None, viaje_id: str | None = None) -> _Salida:
        propuesta: dict[str, Any] = {"id": str(self._nuevo_id()), "tipo": tipo, "resumen": resumen,
                                     "venceEn": (ahora + VIGENCIA_DE_PROPUESTA).isoformat()}
        if reserva_id:
            propuesta["reservaId"] = reserva_id
        if viaje_id:
            propuesta["viajeId"] = viaje_id
        propuesta["datos"] = datos
        return _Salida([resumen], propuesta=propuesta, viaje_id=viaje_id)
