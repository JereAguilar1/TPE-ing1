"""La cola «buzones con cambios», donde convergen los dos caminos de ADR-0004 (vista N2, §3).

El aviso del proveedor (`receptor`) y el sondeo (`reconciliador`) encolan lo mismo: «este buzón
puede tener mensajes nuevos». Encolar un buzón que ya está en la cola no agrega nada: dos avisos
seguidos, o un aviso y un sondeo, se atienden con una sola lectura del buzón.

Para atender un buzón primero se lo **reclama**: sale de la cola en una transacción corta y
recién después se lo lee. Así, un aviso que llega mientras se lo lee lo vuelve a encolar en
lugar de perderse, y la cola no queda bloqueada mientras se habla con el proveedor.

Si la lectura falla, el buzón vuelve con una espera creciente (ADR-0024: `5 s × 2^n`, con tope
de 15 min): un proveedor caído no recibe un reintento por vuelta.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable
from uuid import UUID

import psycopg

ESPERA_INICIAL = timedelta(seconds=5)
ESPERA_MAXIMA = timedelta(minutes=15)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS cola_buzones (
        buzon_id    uuid        PRIMARY KEY,
        usuario_id  uuid        NOT NULL,
        origen      text        NOT NULL,
        encolado_en timestamptz NOT NULL
    );
    ALTER TABLE cola_buzones ADD COLUMN IF NOT EXISTS intentos integer NOT NULL DEFAULT 0;
    ALTER TABLE cola_buzones ADD COLUMN IF NOT EXISTS no_antes_de timestamptz;
    CREATE INDEX IF NOT EXISTS cola_buzones_por_antiguedad ON cola_buzones (encolado_en);
    """,
)


def encolar(conexion: psycopg.Connection, buzon_id: UUID | str, usuario_id: UUID | str,
            origen: str, ahora: datetime) -> None:
    """`origen` es `aviso`, `reconciliacion` o `suscripcionCaida` (para saber por qué entró).
    Si ya está en la cola, queda como estaba (también su espera, si venía fallando)."""
    conexion.execute(
        """INSERT INTO cola_buzones (buzon_id, usuario_id, origen, encolado_en)
           VALUES (%s, %s, %s, %s) ON CONFLICT (buzon_id) DO NOTHING""",
        (str(buzon_id), str(usuario_id), origen, ahora))


def reclamar(conexion: psycopg.Connection, ahora: datetime,
             excluir: Iterable[UUID] = ()) -> dict[str, Any] | None:
    """Saca de la cola el buzón más antiguo que ya puede atenderse (salvo los de `excluir`) y lo
    devuelve. Dos procesos que atiendan la cola a la vez nunca reclaman el mismo (`SKIP LOCKED`)."""
    return conexion.execute(
        """DELETE FROM cola_buzones WHERE buzon_id = (
               SELECT buzon_id FROM cola_buzones
               WHERE buzon_id <> ALL(%s::uuid[])
                 AND (no_antes_de IS NULL OR no_antes_de <= %s)
               ORDER BY encolado_en, buzon_id LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING buzon_id, usuario_id, origen, intentos""",
        ([str(b) for b in excluir], ahora)).fetchone()


def reintentar(conexion: psycopg.Connection, reclamado: dict[str, Any], ahora: datetime) -> None:
    """Devuelve a la cola un buzón cuya lectura falló, con la espera que le toca."""
    intentos = reclamado["intentos"] + 1
    espera = min(ESPERA_INICIAL * 2 ** (intentos - 1), ESPERA_MAXIMA)
    conexion.execute(
        """INSERT INTO cola_buzones (buzon_id, usuario_id, origen, encolado_en, intentos,
                                     no_antes_de)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (buzon_id) DO UPDATE SET intentos = EXCLUDED.intentos,
               no_antes_de = EXCLUDED.no_antes_de""",
        (str(reclamado["buzon_id"]), str(reclamado["usuario_id"]), reclamado["origen"], ahora,
         intentos, ahora + espera))


def quitar(conexion: psycopg.Connection, buzon_id: UUID | str) -> None:
    conexion.execute("DELETE FROM cola_buzones WHERE buzon_id = %s", (str(buzon_id),))
