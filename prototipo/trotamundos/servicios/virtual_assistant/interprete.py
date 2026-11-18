"""Módulo `interprete` del asistente: qué quiso decir el viajero (ADR-0037).

El resto del asistente depende solo del puerto `InterpreteDeIntenciones`: recibe el texto y el
contexto del viajero (sus viajes y reservas) y devuelve una `Interpretacion` con la intención (el enum
`Intencion` de `virtual-assistant.yaml`), las entidades y una confianza entre 0 y 1. Ningún otro
módulo sabe cómo se interpreta un texto.

`InterpretePorReglas` es la implementación del prototipo: patrones del catálogo del idioma, fechas y
horas relativas a la zona del tramo, y la reserva por su código o, si no se nombra, el próximo tramo.
El adaptador de modelo de lenguaje, detrás del mismo puerto, queda diseñado y no construido.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from trotamundos.servicios.virtual_assistant import catalogo

NO_ENTENDIDO = "noEntendido"


@dataclass(frozen=True)
class ContextoDelViajero:
    """Lo que el intérprete puede usar para encontrar entidades: viajes y reservas del viajero
    (`Viaje` y `Reserva` de `comun.yaml`) y el instante actual. Las reservas por confirmar se
    encuentran por su código, pero nunca son «el próximo tramo»: no están en ningún viaje."""

    ahora: datetime
    viajes: Sequence[Mapping[str, Any]] = ()
    reservas: Sequence[Mapping[str, Any]] = ()
    por_confirmar: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class Interpretacion:
    intencion: str
    confianza: float
    reserva_id: str | None = None
    segmento_id: str | None = None
    por_referencia: bool = False  # la reserva se nombró por su código (no es el próximo tramo)
    tipo: str | None = None
    viaje_id: str | None = None
    fecha: date | None = None
    hora: time | None = None
    entidades: dict[str, str] = field(default_factory=dict)  # motivo, decision, eleccion


class InterpreteDeIntenciones(Protocol):
    def interpretar(self, texto: str, contexto: ContextoDelViajero) -> Interpretacion: ...


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: los patrones del catálogo se escriben así."""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _compacto(texto: str) -> str:
    return re.sub(r"[\s-]", "", _normalizar(texto))


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


def _nombra(normal: str, codigo: str | None) -> bool:
    """El texto nombra el código como palabra entera, con o sin espacios o guiones en el medio
    («AR1402», «ar 1402»). Un código de menos de 3 caracteres no se busca: aparecería en cualquier
    hora o fecha."""
    if not codigo:
        return False
    caracteres = _compacto(codigo)
    if len(caracteres) < 3:
        return False
    patron = r"[\s-]?".join(re.escape(c) for c in caracteres)
    return re.search(rf"(?<![a-z0-9]){patron}(?![a-z0-9])", normal) is not None


def proximo_tramo(reservas: Sequence[Mapping[str, Any]], ahora: datetime,
                  tipo: str | None = None) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """La reserva y el tramo que empiezan antes desde `ahora` (del `tipo`, si se pide)."""
    candidatos = [(_instante(s["inicio"]["instante"]), r, s) for r in reservas
                  for s in r.get("segmentos", [])
                  if (tipo is None or s["tipo"] == tipo)
                  and _instante(s["inicio"]["instante"]) >= ahora]
    if not candidatos:
        return None
    _, reserva, segmento = min(candidatos, key=lambda c: c[0])
    return reserva, segmento


def referencia_de(reserva: Mapping[str, Any], segmento: Mapping[str, Any] | None = None) -> str:
    """El código con que el viajero conoce la reserva: el del tramo o el primer identificador."""
    if segmento is not None and segmento.get("referencia"):
        return segmento["referencia"]
    for tramo in reserva.get("segmentos", []):
        if tramo.get("referencia"):
            return tramo["referencia"]
    identificadores = reserva.get("identificadores") or [{"codigo": ""}]
    return identificadores[0]["codigo"]


class InterpretePorReglas:
    """Interpretación determinista con los patrones del catálogo del idioma."""

    def __init__(self, idioma: str = catalogo.IDIOMA_POR_OMISION):
        datos = catalogo.patrones(idioma)
        self._intenciones = [
            (intencion, [(re.compile(p["patron"]), float(p["confianza"])) for p in patrones])
            for intencion, patrones in datos["intenciones"].items()]
        entidades = datos["entidades"]
        self._grupos = {nombre: [(valor, re.compile(patron)) for valor, patron
                                 in entidades[nombre].items()]
                        for nombre in ("motivo", "decision", "eleccion", "tipos")}
        # Los relativos más largos primero: «pasado mañana» antes que «mañana».
        self._relativos = sorted(entidades["dias_relativos"].items(), key=lambda r: -len(r[0]))
        self._dias = entidades["dias_de_la_semana"]
        self._franjas = [(re.compile(f["patron"]), int(f["suma"]))
                         for f in entidades["franjas_del_dia"]]
        self._meses = entidades["meses"]

    # --- puerto ------------------------------------------------------------------------------

    def interpretar(self, texto: str, contexto: ContextoDelViajero) -> Interpretacion:
        normal = _normalizar(texto)
        intencion, confianza = self._intencion(normal)
        if intencion == NO_ENTENDIDO:
            return Interpretacion(NO_ENTENDIDO, 0.0)
        entidades = {nombre: valor for nombre in ("motivo", "decision", "eleccion")
                     if (valor := self._primero(nombre, normal)) is not None}
        tipo = self._primero("tipos", normal)
        reserva, segmento, por_referencia = self._reserva(texto, contexto, tipo)
        zona = ZoneInfo(segmento["inicio"]["zonaHoraria"] if segmento else "UTC")
        hoy = contexto.ahora.astimezone(zona).date()
        dia_del_tramo = _instante(segmento["inicio"]["instante"]).astimezone(zona).date() \
            if segmento else None
        sin_franjas, franja = self._franja(normal)
        return Interpretacion(
            intencion, confianza,
            reserva_id=reserva["id"] if reserva else None,
            segmento_id=segmento["id"] if segmento else None,
            por_referencia=por_referencia, tipo=tipo,
            viaje_id=self._viaje(normal, contexto),
            fecha=self._fecha(sin_franjas, hoy, dia_del_tramo),
            hora=self._hora(sin_franjas, franja), entidades=entidades)

    # --- intención ---------------------------------------------------------------------------

    def _intencion(self, normal: str) -> tuple[str, float]:
        mejor, confianza = NO_ENTENDIDO, 0.0
        for intencion, patrones in self._intenciones:
            for patron, valor in patrones:
                if valor > confianza and patron.search(normal):
                    mejor, confianza = intencion, valor
        return mejor, confianza

    def _primero(self, grupo: str, normal: str) -> str | None:
        return next((valor for valor, patron in self._grupos[grupo] if patron.search(normal)), None)

    # --- entidades ---------------------------------------------------------------------------

    def _reserva(self, texto: str, contexto: ContextoDelViajero, tipo: str | None
                 ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, bool]:
        normal = _normalizar(texto)
        for reserva in [*contexto.reservas, *contexto.por_confirmar]:
            for segmento in reserva.get("segmentos", []):
                if _nombra(normal, segmento.get("referencia")):
                    return reserva, segmento, True
            for identificador in reserva.get("identificadores", []):
                if _nombra(normal, identificador["codigo"]):
                    proximo = proximo_tramo([reserva], contexto.ahora)
                    return reserva, (proximo[1] if proximo else reserva["segmentos"][0]), True
        proximo = proximo_tramo(contexto.reservas, contexto.ahora, tipo)
        return (proximo[0], proximo[1], False) if proximo else (None, None, False)

    def _viaje(self, normal: str, contexto: ContextoDelViajero) -> str | None:
        for viaje in contexto.viajes:
            nombres = [viaje.get("titulo", "")]
            if viaje.get("destinoPrincipal"):
                nombres.append(viaje["destinoPrincipal"]["nombre"])
            if any(len(n) >= 4 and _normalizar(n) in normal for n in nombres):
                return viaje["id"]
        return None

    def _franja(self, normal: str) -> tuple[str, int]:
        """Saca del texto la franja del día («de la mañana», «de la noche»), para que «mañana» no
        se lea como el día siguiente, y devuelve cuántas horas suma a una hora de 1 a 11."""
        for patron, suma in self._franjas:
            if patron.search(normal):
                return patron.sub(" ", normal), suma
        return normal, 0

    def _fecha(self, normal: str, hoy: date, dia_del_tramo: date | None) -> date | None:
        for nombre, dias in self._relativos:
            if re.search(rf"\b{nombre}\b", normal):
                return hoy + timedelta(days=int(dias))
        if (m := re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b", normal)):
            return self._dia_del_mes(hoy, int(m[1]), int(m[2]), m[3])
        if (m := re.search(rf"\b(\d{{1,2}}) de ({'|'.join(self._meses)})\b", normal)):
            return self._dia_del_mes(hoy, int(m[1]), self._meses.index(m[2]) + 1, None)
        for numero, dia in enumerate(self._dias):
            if re.search(rf"\b{dia}\b", normal):
                return self._dia_de_la_semana(numero, hoy, dia_del_tramo)
        return None

    @staticmethod
    def _dia_de_la_semana(numero: int, hoy: date, dia_del_tramo: date | None) -> date:
        """Sobre un tramo, el día más cercano a su fecha («me pasaron el vuelo del jueves 3/12 al
        sábado» es el 5/12, como en ADR-0038), sin caer antes de hoy. Sin tramo, el próximo
        después de hoy."""
        if dia_del_tramo is None:
            return hoy + timedelta(days=(numero - hoy.weekday() - 1) % 7 + 1)
        corrimiento = (numero - dia_del_tramo.weekday()) % 7
        fecha = dia_del_tramo + timedelta(days=corrimiento if corrimiento <= 3 else corrimiento - 7)
        while fecha < hoy:
            fecha += timedelta(days=7)
        return fecha

    @staticmethod
    def _dia_del_mes(hoy: date, dia: int, mes: int, anio: str | None) -> date | None:
        """Sin año, la próxima vez que llega esa fecha (hoy incluido)."""
        try:
            if anio:
                return date(int(anio) + (2000 if len(anio) == 2 else 0), mes, dia)
            fecha = date(hoy.year, mes, dia)
            return fecha if fecha >= hoy else date(hoy.year + 1, mes, dia)
        except ValueError:
            return None

    @staticmethod
    def _hora(normal: str, franja: int = 0) -> time | None:
        if (m := re.search(r"\b(\d{1,2})[:.](\d{2})\b", normal)):
            hora, minutos = int(m[1]), int(m[2])
        elif (m := re.search(r"\ba las (\d{1,2})( y media| y cuarto)?\b", normal)) \
                or (m := re.search(r"\b(\d{1,2}) ?(hs|h)\b", normal)):
            hora = int(m[1])
            minutos = {" y media": 30, " y cuarto": 15}.get(m[2] or "", 0)
        else:
            return None
        if 1 <= hora <= 11:
            hora += franja  # «a las 9 de la noche» son las 21
        return time(hora, minutos) if hora < 24 and minutos < 60 else None
