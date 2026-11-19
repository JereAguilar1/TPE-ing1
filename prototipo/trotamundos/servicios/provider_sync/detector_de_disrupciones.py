"""Módulo `detector-de-disrupciones` (iteración 2 §5.5; UC-5, QA-04).

Reconoce si un `CambioObservado` forma parte de una disrupción (invocando `detectarDisrupcion`
del adaptador a través de `registro_de_adaptadores`) y la expande a todos los usuarios y reservas
afectados usando `seguimiento`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

import psycopg

from trotamundos.servicios.provider_sync import seguimiento
from trotamundos.servicios.provider_sync.registro_de_adaptadores import RegistroDeAdaptadores

DDL = (
    """
    CREATE TABLE IF NOT EXISTS disrupcion_emitida (
        adaptador_id text NOT NULL,
        disrupcion_id text NOT NULL,
        emitida_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (adaptador_id, disrupcion_id)
    );
    """,
)


@dataclass(frozen=True)
class DisrupcionExpandida:
    disrupcion_id: str
    proveedor: str
    severidad: str
    descripcion: str
    primer_usuario_id: str
    afectados: list[dict[str, Any]]

    def a_carga(self) -> dict[str, Any]:
        return {
            "disrupcionId": self.disrupcion_id,
            "proveedor": self.proveedor,
            "severidad": self.severidad,
            "descripcion": self.descripcion,
            "afectados": self.afectados,
        }


def detectar_y_expandir(conexion: psycopg.Connection, registro: RegistroDeAdaptadores,
                        adaptador_id: str, cambios: Iterable[Mapping[str, Any]],
                        ahora: datetime
                        ) -> tuple[list[DisrupcionExpandida], dict[str, str]]:
    """Devuelve las disrupciones expandidas a usuarios afectados y el mapa `referencia -> disrupcionId`
    para correlacionar los `ReservaObservada` mediante `idDeCausa` (iteración 2 §5.7, UC-5)."""
    disrupciones: list[DisrupcionExpandida] = []
    causas_por_referencia: dict[str, str] = {}
    vistas_en_lote: set[str] = set()

    for cambio in cambios:
        disrupcion = registro.detectar_disrupcion(adaptador_id, cambio)
        if disrupcion is None:
            continue

        disrupcion_id = str(disrupcion["id"])
        referencias = list(dict.fromkeys([
            *(str(r) for r in disrupcion["referenciasAfectadas"]),
            str(cambio["referencia"]),
        ]))
        for ref in referencias:
            causas_por_referencia.setdefault(ref, disrupcion_id)

        if disrupcion_id in vistas_en_lote:
            continue
        vistas_en_lote.add(disrupcion_id)

        reservas_por_usuario: dict[str, list[str]] = {}
        for ref in referencias:
            for seguida in seguimiento.resolver(conexion, adaptador_id, ref):
                lista = reservas_por_usuario.setdefault(seguida.usuario_id, [])
                if seguida.reserva_id not in lista:
                    lista.append(seguida.reserva_id)

        if not reservas_por_usuario:
            continue

        nueva = conexion.execute(
            """
            INSERT INTO disrupcion_emitida (adaptador_id, disrupcion_id, emitida_en)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING disrupcion_id
            """,
            (adaptador_id, disrupcion_id, ahora),
        ).fetchone()
        if nueva is None:
            continue

        afectados = [
            {"usuarioId": uid, "reservaIds": sorted(rids)}
            for uid, rids in sorted(reservas_por_usuario.items())
        ]
        disrupciones.append(
            DisrupcionExpandida(
                disrupcion_id=disrupcion_id,
                proveedor=adaptador_id,
                severidad=str(disrupcion["severidad"]),
                descripcion=str(disrupcion["descripcion"]),
                primer_usuario_id=afectados[0]["usuarioId"],
                afectados=afectados,
            )
        )

    return disrupciones, causas_por_referencia


def purgar_emitidas(conexion: psycopg.Connection, ahora: datetime,
                    retencion: timedelta) -> int:
    return conexion.execute(
        "DELETE FROM disrupcion_emitida WHERE emitida_en < %s",
        (ahora - retencion,),
    ).rowcount
