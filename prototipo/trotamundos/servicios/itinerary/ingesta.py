"""Módulo `ingesta` (vista N2): consume `ReservaExtraida` y `ReservaObservada` (UC-1, UC-2).

Es uno de los dos puntos de entrada del elemento (regla I2) y solo depende de `fusion`. Cada
evento se procesa dentro de la transacción de quien lo llama:

1. se valida contra el contrato AsyncAPI (un evento que no lo cumple no entra);
2. se registra en la bandeja de entrada `(itinerary, idDeEvento)`: si ya estaba, no hace nada
   (ADR-0014). Si la transacción falla, la entrada se deshace con todo lo demás y el evento se
   puede volver a procesar;
3. la observación pasa por la fusión y se guarda;
4. devuelve los eventos de dominio que hay que publicar.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg

from trotamundos.comun.contratos import Contratos, ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import Fuente, ObservacionCanonica
from trotamundos.comun.persistencia import registrar_en_bandeja_de_entrada
from trotamundos.servicios.itinerary.fusion.eventos import Causa, eventos_del_cambio
from trotamundos.servicios.itinerary.fusion.identidad import (
    RepositorioDeReservas,
    ingerir_observacion,
    persistir,
)

CONSUMIDOR = "itinerary"
# Qué fuente trae cada evento: el correo lo extrae booking-extraction y el proveedor lo observa
# provider-sync (iteración 2 §5.10).
FUENTE_POR_EVENTO = {"ReservaExtraida": Fuente.CORREO, "ReservaObservada": Fuente.PROVEEDOR}


def procesar(conexion: psycopg.Connection, evento: Evento, repositorio: RepositorioDeReservas,
             contratos: Contratos, ahora: datetime, region: str | None = None) -> list[Evento]:
    """Aplica el evento y devuelve los eventos a publicar (ninguno si ya se había procesado)."""
    if evento.tipo not in FUENTE_POR_EVENTO:
        raise ErrorDeContrato(evento.tipo, [f"itinerary no consume {evento.tipo}"])
    evento.validar(contratos)
    observacion = ObservacionCanonica.desde_dict(evento.carga["observacion"])
    if observacion.fuente != FUENTE_POR_EVENTO[evento.tipo]:
        raise ErrorDeContrato(evento.tipo, [
            f"$.observacion.fuente: {evento.tipo} trae observaciones de fuente "
            f"{FUENTE_POR_EVENTO[evento.tipo]}, no {observacion.fuente}"])

    if not registrar_en_bandeja_de_entrada(conexion, CONSUMIDOR, evento):
        return []

    banda = evento.carga.get("banda")
    confianza = evento.carga["confianza"]["global"] if "confianza" in evento.carga else None
    resultado = ingerir_observacion(repositorio, UUID(evento.sobre["usuarioId"]), observacion,
                                    ahora, banda=banda, confianza=confianza)
    persistir(repositorio, resultado)

    causa = Causa(region=region, traceparent=evento.sobre.get("traceparent"),
                  id_de_correlacion=evento.sobre.get("idDeCorrelacion"),
                  id_de_causa=evento.sobre.get("idDeCausa"))
    return eventos_del_cambio(
        resultado.reserva, resultado.consolidacion, observacion.fuente, causa, ahora,
        hubo_cambio=resultado.creada or resultado.aplicada or bool(resultado.unificadas),
        creada=resultado.creada, unificadas=resultado.unificadas)
