"""Módulo `seguimiento` (iteración 2 §5.5; vista de adaptadores §1; RF-05, RF-10).

Mantiene el índice `(adaptador_id, referencia) → (usuario_id, reserva_id)` de las reservas activas
que sigue cada adaptador. Se alimenta al consumir `ReservaActualizada` y `ReservaCancelada` de
`itinerary`, o por registro explícito.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from uuid import UUID

import psycopg

from trotamundos.comun.modelo import limites_del_extremo

DDL = (
    """
    CREATE TABLE IF NOT EXISTS reserva_seguida (
        adaptador_id text NOT NULL,
        referencia text NOT NULL,
        usuario_id uuid NOT NULL,
        reserva_id uuid NOT NULL,
        inicio_proximo timestamptz,
        fin_ultimo timestamptz,
        actualizado_en timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (adaptador_id, referencia, usuario_id, reserva_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS reserva_seguida_por_referencia
        ON reserva_seguida (adaptador_id, referencia);
    """,
)

_ESTADOS_ACTIVOS = frozenset({"Confirmada", "PorConfirmar"})


@dataclass(frozen=True)
class ReservaSeguida:
    adaptador_id: str
    referencia: str
    usuario_id: str
    reserva_id: str
    inicio_proximo: datetime | None = None
    fin_ultimo: datetime | None = None


def _limites_de_segmentos(segmentos: Iterable[Mapping[str, Any]]
                          ) -> tuple[datetime | None, datetime | None]:
    inicios: list[datetime] = []
    fines: list[datetime] = []
    for seg in segmentos:
        if seg.get("estado") == "cancelado":
            continue
        inicio, _ = limites_del_extremo(seg["inicio"])
        _, fin = limites_del_extremo(seg["fin"])
        inicios.append(inicio)
        fines.append(fin)
    if not inicios:
        return None, None
    return min(inicios), max(fines)


def registrar(conexion: psycopg.Connection, adaptador_id: str, referencia: str,
              usuario_id: UUID | str, reserva_id: UUID | str, *,
              inicio_proximo: datetime | None = None,
              fin_ultimo: datetime | None = None,
              ahora: datetime | None = None) -> None:
    instante = ahora or datetime.now(timezone.utc)
    conexion.execute(
        """
        INSERT INTO reserva_seguida (
            adaptador_id, referencia, usuario_id, reserva_id,
            inicio_proximo, fin_ultimo, actualizado_en
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (adaptador_id, referencia, usuario_id, reserva_id) DO UPDATE
        SET inicio_proximo = EXCLUDED.inicio_proximo,
            fin_ultimo = EXCLUDED.fin_ultimo,
            actualizado_en = EXCLUDED.actualizado_en
        """,
        (adaptador_id, referencia, str(usuario_id), str(reserva_id),
         inicio_proximo, fin_ultimo, instante),
    )


def baja_reserva(conexion: psycopg.Connection, usuario_id: UUID | str,
                 reserva_id: UUID | str) -> None:
    conexion.execute(
        "DELETE FROM reserva_seguida WHERE usuario_id = %s AND reserva_id = %s",
        (str(usuario_id), str(reserva_id)),
    )


def actualizar_desde_reserva(conexion: psycopg.Connection, usuario_id: UUID | str,
                             reserva: Mapping[str, Any],
                             adaptadores_para_emisor: Callable[[str], Iterable[str]],
                             ahora: datetime | None = None, *,
                             unificada_con: Iterable[UUID | str] = ()) -> None:
    reserva_id = str(reserva["id"])
    baja_reserva(conexion, usuario_id, reserva_id)
    for absorbida_id in unificada_con:
        baja_reserva(conexion, usuario_id, absorbida_id)
    if reserva.get("estado") not in _ESTADOS_ACTIVOS:
        return

    inicio_proximo, fin_ultimo = _limites_de_segmentos(reserva.get("segmentos") or ())
    instante = ahora or datetime.now(timezone.utc)
    for ident in reserva.get("identificadores") or ():
        emisor = str(ident["emisor"])
        codigo = str(ident["codigo"])
        for adaptador_id in adaptadores_para_emisor(emisor):
            registrar(
                conexion, adaptador_id, codigo, usuario_id, reserva_id,
                inicio_proximo=inicio_proximo, fin_ultimo=fin_ultimo, ahora=instante,
            )


def resolver(conexion: psycopg.Connection, adaptador_id: str,
             referencia: str) -> list[ReservaSeguida]:
    filas = conexion.execute(
        """
        SELECT adaptador_id, referencia, usuario_id, reserva_id, inicio_proximo, fin_ultimo
        FROM reserva_seguida
        WHERE adaptador_id = %s AND referencia = %s
        ORDER BY usuario_id, reserva_id
        """,
        (adaptador_id, referencia),
    ).fetchall()
    return [
        ReservaSeguida(
            adaptador_id=f["adaptador_id"],
            referencia=f["referencia"],
            usuario_id=str(f["usuario_id"]),
            reserva_id=str(f["reserva_id"]),
            inicio_proximo=f["inicio_proximo"],
            fin_ultimo=f["fin_ultimo"],
        )
        for f in filas
    ]
