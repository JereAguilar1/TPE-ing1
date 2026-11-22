"""Módulo `programador` (iteración 2 §5.5; RF-05, CRN-09).

Ejecuta las consultas programadas (`sondear`) sobre los adaptadores que declaran `sondeo: true` en
su manifiesto, guardando en PostgreSQL la marca `ultimo_sondeo` por adaptador. Con un
`ProtectorDeProveedores`, cada sondeo pasa por su barrera (ADR-0024): si no pasa o falla de forma
transitoria, queda en `cola_pendientes` y no se repite antes de su espera; al volver el proveedor
se drena con el límite de cuota del drenaje.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.servicios.provider_sync import proteccion
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
SONDEO = "sondear"
# El sondeo siempre consulta desde el último exitoso: un pendiente por adaptador alcanza.
DESDE_EL_ULTIMO = "desde-el-ultimo-sondeo"


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
                  ahora: datetime, protector: proteccion.ProtectorDeProveedores | None = None
                  ) -> list[tuple[str, list[dict[str, Any]]]]:
    """Sondea todos los adaptadores con `sondeo: true`. Si un proveedor falla transitoriamente,
    no detiene a los demás (ADR-0006, QA-06)."""
    resultados: list[tuple[str, list[dict[str, Any]]]] = []
    for adaptador in registro.adaptadores_con_sondeo():
        if protector is None:
            try:
                resultados.append((adaptador.id,
                                   sondear_adaptador(conexion, registro, adaptador.id, ahora)))
            except (ErrorDeAdaptador, ErrorDeContrato):
                continue
            continue
        cambios = _sondear_protegido(conexion, registro, protector, adaptador.id, ahora)
        if cambios is not None:
            resultados.append((adaptador.id, cambios))
    return resultados


def _sondear_protegido(conexion: psycopg.Connection, registro: RegistroDeAdaptadores,
                       protector: proteccion.ProtectorDeProveedores, adaptador_id: str,
                       ahora: datetime) -> list[dict[str, Any]] | None:
    """Un sondeo por la barrera del adaptador. `None` si no se hizo (queda o sigue pendiente)."""
    previo = proteccion.pendiente(conexion, adaptador_id, SONDEO)
    if previo is not None and previo["proximo_intento"] > ahora:
        return None  # respeta la espera del reintento
    try:
        cambios = protector.llamar(
            adaptador_id, "reconciliacion",
            lambda: sondear_adaptador(conexion, registro, adaptador_id, ahora),
            ahora, drenando=previo is not None)
    except proteccion.Reintentable as error:
        proteccion.postergar(conexion, adaptador_id, SONDEO, DESDE_EL_ULTIMO, error, ahora)
        return None
    except (ErrorDeAdaptador, ErrorDeContrato):
        return None  # no reintentable: el próximo sondeo programado lo vuelve a intentar
    if previo is not None:
        proteccion.quitar(conexion, adaptador_id, SONDEO)
    return cambios
