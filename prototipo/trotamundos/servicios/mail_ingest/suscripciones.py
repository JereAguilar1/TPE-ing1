"""Módulo `suscripciones` (vista N2, §3; ADR-0004).

Lleva lo que `mail-ingest` sabe de cada buzón, a partir de `EstadoDeBuzonCambiado`: cuando pasa a
`Activo`, lo da de alta y crea la suscripción de avisos; en cualquier otro estado deja de
atenderlo y la cancela (iteración 2 §5.7). También renueva las suscripciones antes de que venzan y
detecta las que se cayeron: ante una caída **fuerza una reconciliación**, porque los avisos que se
perdieron mientras tanto solo los recupera el sondeo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping
from uuid import UUID

import psycopg

from trotamundos.servicios.mail_ingest import cola
from trotamundos.servicios.mail_ingest.interfaz_de_correo import (
    AdaptadorDeCorreo,
    SuscripcionFallida,
)

# Se renueva con este margen antes del vencimiento, para no quedar nunca sin avisos.
MARGEN_DE_RENOVACION = timedelta(hours=24)

_registro_de_errores = logging.getLogger(__name__)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS buzon_ingesta (
        buzon_id               uuid        PRIMARY KEY,
        usuario_id             uuid        NOT NULL,
        region                 text,
        via                    text        NOT NULL,
        proveedor              text,
        alias_reenvio          text        UNIQUE,
        correo_titular         text,
        activo                 boolean     NOT NULL,
        soporta_push           boolean     NOT NULL,
        suscripcion_id         text,
        suscripcion_expira_en  timestamptz,
        cursor_de_lectura      text,
        proxima_reconciliacion timestamptz,
        actualizado_en         timestamptz NOT NULL
    );
    CREATE INDEX IF NOT EXISTS buzon_ingesta_por_suscripcion ON buzon_ingesta (suscripcion_id);
    CREATE INDEX IF NOT EXISTS buzon_ingesta_por_usuario ON buzon_ingesta (usuario_id);
    """,
)


@dataclass(frozen=True)
class Buzon:
    buzon_id: UUID
    usuario_id: UUID
    region: str | None
    via: str
    proveedor: str | None
    alias_reenvio: str | None
    correo_titular: str | None
    activo: bool
    cursor: str | None

    @classmethod
    def desde_fila(cls, fila: Mapping[str, Any]) -> Buzon:
        return cls(fila["buzon_id"], fila["usuario_id"], fila["region"], fila["via"],
                   fila["proveedor"], fila["alias_reenvio"], fila["correo_titular"],
                   fila["activo"], fila["cursor_de_lectura"])


# El adaptador de cada buzón: lo resuelve quien arma el servicio (los complementos).
ResolverAdaptador = Callable[[str, str | None], AdaptadorDeCorreo | None]


def aplicar_estado(conexion: psycopg.Connection, adaptador_para: ResolverAdaptador,
                   usuario_id: UUID, region: str | None, carga: Mapping[str, Any],
                   ahora: datetime, primera_reconciliacion: Callable[[UUID, bool], datetime]
                   ) -> None:
    """Refleja un `EstadoDeBuzonCambiado`. Con `Activo` trae vía, proveedor, alias y correo del
    titular (AsyncAPI 1.4)."""
    buzon_id = UUID(carga["buzonId"])
    actual = conexion.execute("SELECT * FROM buzon_ingesta WHERE buzon_id = %s",
                              (buzon_id,)).fetchone()
    if carga["estadoNuevo"] != "Activo":
        if actual is not None:
            _cancelar(adaptador_para(actual["via"], actual["proveedor"]), actual)
            conexion.execute(
                """UPDATE buzon_ingesta SET activo = false, suscripcion_id = NULL,
                       suscripcion_expira_en = NULL, proxima_reconciliacion = NULL,
                       actualizado_en = %s WHERE buzon_id = %s""", (ahora, buzon_id))
            cola.quitar(conexion, buzon_id)
        return

    via, proveedor = carga.get("via", actual["via"] if actual else None), carga.get("proveedor")
    if via is None:
        _registro_de_errores.warning("Buzón %s activo sin vía: no se puede atender", buzon_id)
        return
    adaptador = adaptador_para(via, proveedor)
    soporta_push = bool(adaptador is not None and adaptador.soporta_push)
    # El reenvío no se lee de ningún lado: lo entrega el servidor de correo propio.
    proxima = primera_reconciliacion(buzon_id, soporta_push) if adaptador is not None else None
    conexion.execute(
        """INSERT INTO buzon_ingesta (buzon_id, usuario_id, region, via, proveedor, alias_reenvio,
                                      correo_titular, activo, soporta_push,
                                      proxima_reconciliacion, actualizado_en)
           VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s)
           ON CONFLICT (buzon_id) DO UPDATE SET
               region = EXCLUDED.region, via = EXCLUDED.via, proveedor = EXCLUDED.proveedor,
               alias_reenvio = EXCLUDED.alias_reenvio, correo_titular = EXCLUDED.correo_titular,
               activo = true, soporta_push = EXCLUDED.soporta_push,
               proxima_reconciliacion = EXCLUDED.proxima_reconciliacion,
               actualizado_en = EXCLUDED.actualizado_en""",
        (buzon_id, usuario_id, region, via, proveedor, carga.get("aliasReenvio"),
         carga.get("correoDelTitular"), soporta_push, proxima, ahora))
    if soporta_push:
        _suscribir(conexion, adaptador, buzon_id, usuario_id, ahora)
    if adaptador is not None:
        # Lo que llegó antes de activarse (o mientras estuvo pausado) se lee ya.
        cola.encolar(conexion, buzon_id, usuario_id, "reconciliacion", ahora)


def obtener(conexion: psycopg.Connection, buzon_id: UUID | str) -> Buzon | None:
    fila = conexion.execute("SELECT * FROM buzon_ingesta WHERE buzon_id = %s",
                            (str(buzon_id),)).fetchone()
    return Buzon.desde_fila(fila) if fila else None


def por_suscripcion(conexion: psycopg.Connection, suscripcion_id: str) -> Buzon | None:
    fila = conexion.execute(
        "SELECT * FROM buzon_ingesta WHERE suscripcion_id = %s AND activo",
        (suscripcion_id,)).fetchone()
    return Buzon.desde_fila(fila) if fila else None


def por_alias(conexion: psycopg.Connection, alias: str) -> Buzon | None:
    fila = conexion.execute(
        "SELECT * FROM buzon_ingesta WHERE lower(alias_reenvio) = lower(%s) AND activo",
        (alias,)).fetchone()
    return Buzon.desde_fila(fila) if fila else None


def guardar_cursor(conexion: psycopg.Connection, buzon_id: UUID | str, cursor: str | None) -> None:
    conexion.execute("UPDATE buzon_ingesta SET cursor_de_lectura = %s WHERE buzon_id = %s",
                     (cursor, str(buzon_id)))


def renovar(conexion: psycopg.Connection, adaptador_para: ResolverAdaptador,
            ahora: datetime) -> int:
    """Renueva las suscripciones que vencen dentro del margen y rehace las caídas (sin
    suscripción o ya vencidas). Cada caída fuerza una reconciliación. Devuelve cuántas tocó."""
    filas = conexion.execute(
        """SELECT * FROM buzon_ingesta
           WHERE activo AND soporta_push
             AND (suscripcion_id IS NULL OR suscripcion_expira_en <= %s)
           FOR UPDATE SKIP LOCKED""", (ahora + MARGEN_DE_RENOVACION,)).fetchall()
    for fila in filas:
        adaptador = adaptador_para(fila["via"], fila["proveedor"])
        if adaptador is None:
            continue
        vigente = fila["suscripcion_id"] is not None and fila["suscripcion_expira_en"] > ahora
        if vigente:
            try:
                nueva = adaptador.renovar(str(fila["buzon_id"]), fila["suscripcion_id"], ahora)
                conexion.execute(
                    "UPDATE buzon_ingesta SET suscripcion_expira_en = %s WHERE buzon_id = %s",
                    (nueva.expira_en, fila["buzon_id"]))
                continue
            except SuscripcionFallida:
                pass  # se cayó: se trata como las demás caídas
        cola.encolar(conexion, fila["buzon_id"], fila["usuario_id"], "suscripcionCaida", ahora)
        _suscribir(conexion, adaptador, fila["buzon_id"], fila["usuario_id"], ahora)
    return len(filas)


def _suscribir(conexion: psycopg.Connection, adaptador: AdaptadorDeCorreo, buzon_id: UUID,
               usuario_id: UUID, ahora: datetime) -> None:
    try:
        suscripcion = adaptador.suscribir(str(buzon_id), ahora)
    except SuscripcionFallida:
        # Sin avisos: la próxima renovación lo vuelve a intentar y, mientras, el buzón entra a
        # la cola por reconciliación.
        conexion.execute(
            """UPDATE buzon_ingesta SET suscripcion_id = NULL, suscripcion_expira_en = NULL
               WHERE buzon_id = %s""", (buzon_id,))
        cola.encolar(conexion, buzon_id, usuario_id, "suscripcionCaida", ahora)
        return
    conexion.execute(
        """UPDATE buzon_ingesta SET suscripcion_id = %s, suscripcion_expira_en = %s
           WHERE buzon_id = %s""", (suscripcion.id, suscripcion.expira_en, buzon_id))


def _cancelar(adaptador: AdaptadorDeCorreo | None, fila: Mapping[str, Any]) -> None:
    if adaptador is None or not fila["suscripcion_id"]:
        return
    try:
        adaptador.cancelar(str(fila["buzon_id"]), fila["suscripcion_id"])
    except Exception:  # el proveedor la da de baja sola al vencer: no frena la revocación
        _registro_de_errores.exception("No se pudo cancelar la suscripción de %s", fila["buzon_id"])
