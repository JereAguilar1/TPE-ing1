"""Capa de aterrizaje de eventos crudos del plano analítico (P3 de ADR-0016; ADR-0003, ADR-0030).

Retiene los eventos de dominio inmutables para poder reconstruir el esquema en estrella si cambia
el modelo dimensional, sin tocar jamás el plano operacional (regla R6). Ninguna fila guarda
`usuario_id` ni datos personales directos: el identificador operacional se reemplaza en la entrada
por su `seudonimo_analitico` determinista.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Mapping

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import instante_desde_texto

DDL = (
    """
    CREATE TABLE IF NOT EXISTS evento_crudo (
        orden               bigserial    PRIMARY KEY,
        evento_id           uuid        NOT NULL UNIQUE,
        tipo                text        NOT NULL,
        seudonimo_analitico varchar(64) NOT NULL,
        region              varchar(2)  NOT NULL,
        ocurrido_en         timestamptz NOT NULL,
        productor           text        NOT NULL,
        carga               jsonb       NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS evento_crudo_por_seudonimo
        ON evento_crudo (seudonimo_analitico);
    """,
)


@dataclass(frozen=True)
class EventoCrudo:
    orden: int
    evento_id: str
    tipo: str
    seudonimo_analitico: str
    region: str
    ocurrido_en: datetime
    productor: str
    carga: dict[str, Any]


def seudonimo_de_usuario(usuario_id: str) -> str:
    """Seudónimo analítico determinista derivado de `usuario_id` sin guardar el UUID operacional."""
    if usuario_id.startswith("seu_"):
        return usuario_id
    digest = hashlib.sha256(f"analitica:{usuario_id}".encode("utf-8")).hexdigest()[:24]
    return f"seu_{digest}"


def _sanitizar_carga(carga: Mapping[str, Any]) -> dict[str, Any]:
    """Remueve cualquier referencia a `usuarioId` si viniera dentro de la carga."""
    limpia: dict[str, Any] = {}
    for clave, valor in carga.items():
        if clave == "usuarioId":
            continue
        if isinstance(valor, Mapping):
            limpia[clave] = _sanitizar_carga(valor)
        elif isinstance(valor, list):
            limpia[clave] = [
                _sanitizar_carga(item) if isinstance(item, Mapping) else item
                for item in valor
            ]
        else:
            limpia[clave] = valor
    return limpia


def registrar_crudo(conexion: psycopg.Connection, evento: Evento) -> EventoCrudo:
    if evento.tipo == "CuentaSuprimida":
        seudonimo = str(evento.carga["seudonimoAnalitico"])
    else:
        seudonimo = seudonimo_de_usuario(str(evento.sobre["usuarioId"]))

    region = str(evento.sobre.get("regionOrigen") or "AM")
    ocurrido_en = instante_desde_texto(str(evento.sobre["ocurridoEn"]))
    carga_limpia = _sanitizar_carga(evento.carga)

    fila = conexion.execute(
        """
        INSERT INTO evento_crudo (
            evento_id, tipo, seudonimo_analitico, region, ocurrido_en, productor, carga
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (evento_id) DO UPDATE
        SET tipo = EXCLUDED.tipo
        RETURNING orden, evento_id, tipo, seudonimo_analitico, region, ocurrido_en, productor, carga
        """,
        (
            evento.id,
            evento.tipo,
            seudonimo,
            region,
            ocurrido_en,
            str(evento.sobre["productor"]),
            Jsonb(carga_limpia),
        ),
    ).fetchone()
    assert fila is not None
    return EventoCrudo(
        orden=int(fila["orden"]),
        evento_id=str(fila["evento_id"]),
        tipo=str(fila["tipo"]),
        seudonimo_analitico=str(fila["seudonimo_analitico"]),
        region=str(fila["region"]),
        ocurrido_en=fila["ocurrido_en"],
        productor=str(fila["productor"]),
        carga=dict(fila["carga"]),
    )


def listar_crudos(conexion: psycopg.Connection) -> list[EventoCrudo]:
    filas = conexion.execute(
        """
        SELECT orden, evento_id, tipo, seudonimo_analitico, region, ocurrido_en, productor, carga
        FROM evento_crudo
        ORDER BY orden
        """
    ).fetchall()
    return [
        EventoCrudo(
            orden=int(f["orden"]),
            evento_id=str(f["evento_id"]),
            tipo=str(f["tipo"]),
            seudonimo_analitico=str(f["seudonimo_analitico"]),
            region=str(f["region"]),
            ocurrido_en=f["ocurrido_en"],
            productor=str(f["productor"]),
            carga=dict(f["carga"]),
        )
        for f in filas
    ]
