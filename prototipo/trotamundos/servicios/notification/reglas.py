"""Módulo `reglas` de `notification`: qué evento merece qué aviso (iteración 2 §5.7, RF-10).

| Severidad | Disparadores |
|---|---|
| crítica | cancelación; cambio de un campo declarado crítico por el descriptor del tipo (por ejemplo, el
  horario más allá de su umbral, o la puerta o el andén); `DisrupcionDetectada` alta |
| informativa | reserva agregada o por confirmar; cambios menores; disrupción media o baja; caso
  derivado; viaje completado |
| administrativa | buzón que requiere reautorización; extracción no reconocida; conflicto abierto |

Los cambios que hizo el propio viajero (fuente `manual`) no se le avisan. Ningún tipo de segmento
aparece en este módulo: lo relevante de cada tipo lo dice su descriptor (ADR-0011, QA-15).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import Severidad
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, TipoNoRegistrado

CRITICA, INFORMATIVA, ADMINISTRATIVA = "critica", "informativa", "administrativa"
_CAMPO_DE_SEGMENTO = re.compile(r"^segmentos\[(\d+)\]\.(.+)$")


@dataclass(frozen=True)
class Aviso:
    usuario_id: str
    severidad: str
    motivo: str               # qué pasó, para la bandeja interna (sin datos personales)
    viaje_id: str | None = None
    id_de_causa: str | None = None


def _minutos_entre(anterior: Any, nuevo: Any) -> float | None:
    try:
        return abs((datetime.fromisoformat(str(nuevo).replace("Z", "+00:00"))
                    - datetime.fromisoformat(str(anterior).replace("Z", "+00:00"))).total_seconds()) / 60
    except ValueError:
        return None


def _es_critico(reserva: Mapping[str, Any], cambio: Mapping[str, Any],
                registro: RegistroDeTipos) -> bool:
    if cambio["campo"] == "estado" and cambio.get("nuevo") == "Cancelada":
        return True
    coincide = _CAMPO_DE_SEGMENTO.match(cambio["campo"])
    if not coincide or int(coincide[1]) >= len(reserva.get("segmentos", [])):
        return False
    segmento = reserva["segmentos"][int(coincide[1])]
    try:
        descriptor = registro.obtener(segmento["tipo"], segmento.get("versionTipo"))
    except TipoNoRegistrado:
        return False
    for relevante in descriptor.campos_relevantes:
        if relevante.campo != coincide[2] or relevante.severidad != Severidad.CRITICA:
            continue
        if relevante.umbral_minutos is None:
            return True
        minutos = _minutos_entre(cambio.get("anterior"), cambio.get("nuevo"))
        return minutos is not None and minutos >= relevante.umbral_minutos
    return False


def avisos_de(evento: Evento, registro: RegistroDeTipos) -> list[Aviso]:
    """Los avisos que corresponden a un evento (ninguno, uno, o uno por viajero afectado)."""
    carga, sobre = evento.carga, evento.sobre
    usuario, causa = sobre.get("usuarioId"), sobre.get("idDeCausa")

    if evento.tipo == "ReservaActualizada":
        reserva = carga["reserva"]
        ajenos = [c for c in carga["cambios"] if c.get("fuente") != "manual"]
        if carga["cambios"] and not ajenos:
            return []  # lo cambió o lo cargó el propio viajero
        critico = any(_es_critico(reserva, c, registro) for c in ajenos)
        if critico:
            motivo = "cambioCritico"
        elif carga.get("creada"):
            motivo = "reservaPorConfirmar" if reserva.get("estado") == "PorConfirmar" else "reservaAgregada"
        else:
            motivo = "cambioMenor"
        return [Aviso(usuario, CRITICA if critico else INFORMATIVA, motivo, reserva.get("viajeId"),
                      causa)]
    if evento.tipo == "ReservaCancelada":
        if carga.get("fuente") == "manual":
            return []
        return [Aviso(usuario, CRITICA, "reservaCancelada", carga.get("viajeId"), causa)]
    if evento.tipo == "DisrupcionDetectada":
        severidad = CRITICA if carga["severidad"] == "alta" else INFORMATIVA
        return [Aviso(a["usuarioId"], severidad, "disrupcion", None, carga["disrupcionId"])
                for a in carga["afectados"]]
    if evento.tipo == "ConflictoDeFuentesDetectado":
        return [Aviso(usuario, ADMINISTRATIVA, "conflictoAbierto", None, causa)]
    if evento.tipo == "ExtraccionNoReconocida":
        return [Aviso(usuario, ADMINISTRATIVA, "extraccionNoReconocida")]
    if evento.tipo == "EstadoDeBuzonCambiado":
        if carga["estadoNuevo"] != "RequiereReautorizacion":
            return []
        return [Aviso(usuario, ADMINISTRATIVA, "buzonRequiereReautorizacion")]
    if evento.tipo == "CasoDerivado":
        return [Aviso(usuario, INFORMATIVA, "casoDerivado", carga["viajeId"], causa)]
    if evento.tipo == "ViajeCompletado":
        return [Aviso(usuario, INFORMATIVA, "viajeCompletado", carga["viajeId"])]
    return []
