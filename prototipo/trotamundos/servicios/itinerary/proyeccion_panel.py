"""Módulo `proyeccion-panel` (vista N2): modelos de lectura mantenidos por eventos internos.

No importa lógica de dominio (regla I3): lee las cargas de los eventos, que ya tienen la forma
del contrato. Por eso la lectura se puede desplegar sola, en `itinerary-lectura` (ADR-0021).

* `reserva_lectura`: la reserva consolidada (`ReservaActualizada`) y su viaje (`ViajeArmado`).
  Las descartadas, dadas de baja o absorbidas salen.
* `viaje_lectura`: el viaje (`ViajeArmado`). Los eliminados salen.
* `panel_usuario`: el panel completo del usuario, en una fila, para leerlo en un solo acceso
  (UC-3, QA-02). Se rearma con cada evento del usuario.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.eventos import Evento
from trotamundos.comun.modelo import instante_a_texto, instante_desde_texto

DDL = (
    """
    CREATE TABLE IF NOT EXISTS reserva_lectura (
        usuario_id uuid   NOT NULL,
        reserva_id uuid   NOT NULL,
        version    bigint NOT NULL,
        datos      jsonb  NOT NULL,
        PRIMARY KEY (usuario_id, reserva_id)
    );
    ALTER TABLE reserva_lectura ADD COLUMN IF NOT EXISTS viaje_id uuid;
    """,
    """
    CREATE TABLE IF NOT EXISTS viaje_lectura (
        usuario_id uuid        NOT NULL,
        viaje_id   uuid        NOT NULL,
        estado     text        NOT NULL,
        desde      timestamptz NOT NULL,
        version    bigint      NOT NULL,
        datos      jsonb       NOT NULL,
        PRIMARY KEY (usuario_id, viaje_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS panel_usuario (
        usuario_id      uuid   PRIMARY KEY,
        version_usuario bigint NOT NULL,
        datos           jsonb  NOT NULL
    );
    """,
)

# El panel no incluye viajes Completado, Archivado ni Eliminado (comun.yaml, `Panel`; RF-08).
VISIBLES_EN_EL_PANEL = ("Planificado", "EnCurso", "Cancelado")


def aplicar(conexion: psycopg.Connection, eventos: Iterable[Evento],
            version_usuario: int | None = None) -> None:
    """Actualiza las lecturas con los eventos y rearma el panel de cada usuario afectado."""
    usuarios = []
    for evento in eventos:
        usuario = evento.sobre["usuarioId"]
        if evento.tipo == "ReservaActualizada":
            _reserva(conexion, usuario, evento.carga)
        elif evento.tipo == "ViajeArmado":
            _viaje(conexion, usuario, evento.carga)
        else:
            continue
        if usuario not in usuarios:
            usuarios.append(usuario)
    for usuario in usuarios:
        _rearmar_panel(conexion, usuario, version_usuario)


def _reserva(conexion: psycopg.Connection, usuario: str, carga: dict[str, Any]) -> None:
    reserva = carga["reserva"]
    for absorbida in carga.get("unificadaCon", []):
        _borrar(conexion, "reserva_lectura", usuario, "reserva_id", absorbida)
    if reserva["estado"] == "Descartada":
        _borrar(conexion, "reserva_lectura", usuario, "reserva_id", reserva["id"])
        return
    # Una versión vieja que llegue tarde no pisa a una nueva; el viaje no lo toca este evento.
    conexion.execute(
        """INSERT INTO reserva_lectura (usuario_id, reserva_id, version, datos)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (usuario_id, reserva_id) DO UPDATE
               SET version = EXCLUDED.version, datos = EXCLUDED.datos
               WHERE reserva_lectura.version < EXCLUDED.version""",
        (usuario, reserva["id"], reserva["version"], Jsonb(reserva)))


def _viaje(conexion: psycopg.Connection, usuario: str, carga: dict[str, Any]) -> None:
    viaje_id = carga["viajeId"]
    conexion.execute("UPDATE reserva_lectura SET viaje_id = NULL WHERE usuario_id = %s AND viaje_id = %s",
                     (usuario, viaje_id))
    if carga["estado"] == "Eliminado":
        _borrar(conexion, "viaje_lectura", usuario, "viaje_id", viaje_id)
        return
    conexion.execute(
        "UPDATE reserva_lectura SET viaje_id = %s WHERE usuario_id = %s AND reserva_id = ANY(%s::uuid[])",
        (viaje_id, usuario, carga["reservaIds"]))
    conexion.execute(
        """INSERT INTO viaje_lectura (usuario_id, viaje_id, estado, desde, version, datos)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (usuario_id, viaje_id) DO UPDATE
               SET estado = EXCLUDED.estado, desde = EXCLUDED.desde,
                   version = EXCLUDED.version, datos = EXCLUDED.datos
               WHERE viaje_lectura.version < EXCLUDED.version""",
        (usuario, viaje_id, carga["estado"], carga["desde"], carga.get("version", 0), Jsonb(carga)))


def _borrar(conexion: psycopg.Connection, tabla: str, usuario: str, columna: str, valor: str) -> None:
    conexion.execute(f"DELETE FROM {tabla} WHERE usuario_id = %s AND {columna} = %s",
                     (usuario, valor))


# --- lecturas --------------------------------------------------------------------------------

def leer_reserva(conexion: psycopg.Connection, usuario_id: UUID | str,
                 reserva_id: UUID | str) -> dict[str, Any] | None:
    fila = conexion.execute(
        "SELECT datos, viaje_id FROM reserva_lectura WHERE usuario_id = %s AND reserva_id = %s",
        (str(usuario_id), str(reserva_id))).fetchone()
    return _con_viaje(fila) if fila else None


def leer_viaje(conexion: psycopg.Connection, usuario_id: UUID | str,
               viaje_id: UUID | str) -> dict[str, Any] | None:
    """`Viaje` de `comun.yaml`, con sus reservas completas."""
    fila = conexion.execute("SELECT datos FROM viaje_lectura WHERE usuario_id = %s AND viaje_id = %s",
                            (str(usuario_id), str(viaje_id))).fetchone()
    if fila is None:
        return None
    return _viaje_completo(fila["datos"], _reservas(conexion, str(usuario_id)))


def leer_viajes(conexion: psycopg.Connection, usuario_id: UUID | str, ahora: datetime, *,
                estado: str | None = None, cursor: str | None = None,
                limite: int = 20) -> tuple[list[dict[str, Any]], str | None]:
    """Página de `ViajeResumen`, del más reciente al más antiguo. El cursor es opaco."""
    condiciones, parametros = ["usuario_id = %s"], [str(usuario_id)]
    if estado is not None:
        condiciones.append("estado = %s")
        parametros.append(estado)
    if cursor is not None:
        desde, viaje_id = _leer_cursor(cursor)
        condiciones.append("(desde, viaje_id) < (%s, %s)")
        parametros += [desde, viaje_id]
    filas = conexion.execute(
        f"""SELECT viaje_id, desde, datos FROM viaje_lectura WHERE {' AND '.join(condiciones)}
            ORDER BY desde DESC, viaje_id DESC LIMIT %s""", (*parametros, limite + 1)).fetchall()
    reservas = _reservas(conexion, str(usuario_id))
    pagina = [_resumen(f["datos"], reservas, ahora) for f in filas[:limite]]
    siguiente = (_escribir_cursor(filas[limite - 1]["desde"], filas[limite - 1]["viaje_id"])
                 if len(filas) > limite else None)
    return pagina, siguiente


def leer_panel(conexion: psycopg.Connection, usuario_id: UUID | str) -> dict[str, Any]:
    fila = conexion.execute("SELECT datos FROM panel_usuario WHERE usuario_id = %s",
                            (str(usuario_id),)).fetchone()
    if fila is None:
        return {"viajesActivos": [], "porConfirmar": [], "conflictosAbiertos": [],
                "versionUsuario": 0}
    return fila["datos"]


# --- armado ----------------------------------------------------------------------------------

def _con_viaje(fila: dict[str, Any]) -> dict[str, Any]:
    datos = dict(fila["datos"])
    if fila["viaje_id"] is not None:
        datos["viajeId"] = str(fila["viaje_id"])
    return datos


def _reservas(conexion: psycopg.Connection, usuario: str) -> dict[str, dict[str, Any]]:
    filas = conexion.execute("SELECT reserva_id, datos, viaje_id FROM reserva_lectura WHERE usuario_id = %s",
                             (usuario,)).fetchall()
    return {str(f["reserva_id"]): _con_viaje(f) for f in filas}


def _viaje_completo(carga: dict[str, Any], reservas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    viaje = {"id": carga["viajeId"], "titulo": carga["titulo"], "estado": carga["estado"],
             "desde": carga["desde"], "hasta": carga["hasta"], "version": carga.get("version", 0),
             "reservas": [reservas[r] for r in carga["reservaIds"] if r in reservas]}
    if "destinoPrincipal" in carga:
        viaje["destinoPrincipal"] = carga["destinoPrincipal"]
    return viaje


def _resumen(carga: dict[str, Any], reservas: dict[str, dict[str, Any]],
             ahora: datetime) -> dict[str, Any]:
    """`ViajeResumen`: con el próximo tramo confirmado, si lo hay."""
    propias = [reservas[r] for r in carga["reservaIds"] if r in reservas]
    resumen = {"id": carga["viajeId"], "titulo": carga["titulo"], "estado": carga["estado"],
               "desde": carga["desde"], "hasta": carga["hasta"], "cantidadReservas": len(propias)}
    if "destinoPrincipal" in carga:
        resumen["destinoPrincipal"] = carga["destinoPrincipal"]["nombre"]
    proximos = [s for r in propias for s in r["segmentos"]
                if s["estado"] == "confirmado" and instante_desde_texto(s["inicio"]["instante"]) >= ahora]
    if proximos:
        resumen["proximoSegmento"] = min(proximos, key=lambda s: s["inicio"]["instante"])
    return resumen


def _rearmar_panel(conexion: psycopg.Connection, usuario: str, version_usuario: int | None) -> None:
    if version_usuario is None:
        version_usuario = leer_panel(conexion, usuario)["versionUsuario"]
    reservas = _reservas(conexion, usuario)
    filas = conexion.execute(
        """SELECT datos FROM viaje_lectura WHERE usuario_id = %s AND estado = ANY(%s)
           ORDER BY desde, viaje_id""", (usuario, list(VISIBLES_EN_EL_PANEL))).fetchall()
    viajes = [_viaje_completo(f["datos"], reservas) for f in filas]
    por_confirmar = sorted((r for r in reservas.values() if r["estado"] == "PorConfirmar"),
                           key=lambda r: r["id"])
    visibles = [r for v in viajes for r in v["reservas"]] + por_confirmar
    panel = {
        "viajesActivos": viajes,
        "porConfirmar": por_confirmar,
        "conflictosAbiertos": [{"reservaId": r["id"], "conflicto": c}
                               for r in visibles for c in r.get("conflictosAbiertos", [])],
        "versionUsuario": version_usuario,
    }
    conexion.execute(
        """INSERT INTO panel_usuario (usuario_id, version_usuario, datos) VALUES (%s, %s, %s)
           ON CONFLICT (usuario_id) DO UPDATE
               SET version_usuario = EXCLUDED.version_usuario, datos = EXCLUDED.datos""",
        (usuario, version_usuario, Jsonb(panel)))


def _escribir_cursor(desde: datetime, viaje_id: UUID) -> str:
    texto = json.dumps([instante_a_texto(desde), str(viaje_id)])
    return base64.urlsafe_b64encode(texto.encode()).decode()


def _leer_cursor(cursor: str) -> tuple[datetime, str]:
    """Lanza `ValueError` si el cursor no es uno que haya emitido este módulo."""
    try:
        desde, viaje_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return instante_desde_texto(desde), str(UUID(viaje_id))
    except Exception as error:  # cualquier forma de cursor mal formado
        raise ValueError(f"Cursor inválido: {cursor!r}") from error
