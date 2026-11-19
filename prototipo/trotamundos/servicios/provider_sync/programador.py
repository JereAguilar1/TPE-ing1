"""Módulo `programador` (iteración 2 §5.5; RF-05, CRN-09).

Ejecuta las consultas programadas (`sondear`) sobre los adaptadores que declaran `sondeo: true` en
su manifiesto, guardando en PostgreSQL la marca `ultimo_sondeo` por adaptador.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import ErrorDeAdaptador
from trotamundos.servicios.provider_sync.registro_de_adaptadores import RegistroDeAdaptadores

DDL = (
    """
    CREATE TABLE IF NOT EXISTS estado_sondeo (
        adaptador_id text PRIMARY KEY,
        ultimo_sondeo timestamptz NOT NULL
    );
    """,
)

VENTANA_INICIAL = timedelta(hours=24)


def _isoformat_utc(instante: datetime) -> str:
    return instante.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sondear_adaptador(conexion: psycopg.Connection, registro: RegistroDeAdaptadores,
                      adaptador_id: str, ahora: datetime
                      ) -> list[dict[str, Any]]:
    fila = conexion.execute(
        "SELECT ultimo_sondeo FROM estado_sondeo WHERE adaptador_id = %s",
        (adaptador_id,),
    ).fetchone()
    desde = fila["ultimo_sondeo"] if fila is not None else (ahora - VENTANA_INICIAL)
    cambios = registro.sondear(adaptador_id, _isoformat_utc(desde))
    conexion.execute(
        """
        INSERT INTO estado_sondeo (adaptador_id, ultimo_sondeo)
        VALUES (%s, %s)
        ON CONFLICT (adaptador_id) DO UPDATE
        SET ultimo_sondeo = EXCLUDED.ultimo_sondeo
        """,
        (adaptador_id, ahora),
    )
    return cambios


def sondear_todos(conexion: psycopg.Connection, registro: RegistroDeAdaptadores,
                  ahora: datetime
                  ) -> list[tuple[str, list[dict[str, Any]]]]:
    """Sondea todos los adaptadores con `sondeo: true`. Si un proveedor falla transitoriamente,
    no detiene a los demás (ADR-0006, QA-06)."""
    resultados: list[tuple[str, list[dict[str, Any]]]] = []
    for adaptador in registro.adaptadores_con_sondeo():
        try:
            cambios = sondear_adaptador(conexion, registro, adaptador.id, ahora)
        except (ErrorDeAdaptador, ErrorDeContrato):
            continue
        resultados.append((adaptador.id, cambios))
    return resultados
