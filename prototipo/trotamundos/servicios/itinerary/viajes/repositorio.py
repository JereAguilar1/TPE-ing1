"""Repositorio PostgreSQL del agregado `Viaje` (ADR-0012, iteración 2 §5.8).

* `viaje`: estado, versión, marcas del ciclo de vida, lo derivado de sus reservas y
  `proxima_transicion`, que le dice al trabajo programado cuándo volver a mirarlo.
* `viaje_reserva`: la membresía. `fijada` indica una asignación del usuario. La restricción
  `reserva_en_un_viaje` hace que una reserva pertenezca a lo sumo a un viaje (ADR-0010).

Cumple el puerto `RepositorioDeViajes` por su forma. Dentro de una transacción devuelve siempre el
mismo objeto para el mismo viaje.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.itinerary.viajes import (
    GRACIA_DE_ARCHIVADO,
    EstadoViaje,
    Miembro,
    ResumenDeReserva,
    Viaje,
)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS viaje (
        usuario_id         uuid        NOT NULL,
        viaje_id           uuid        NOT NULL,
        estado             text        NOT NULL,
        version            bigint      NOT NULL,
        creado_en          timestamptz NOT NULL,
        completado_en      timestamptz,
        archivado_en       timestamptz,
        motivo_de_archivo  text,
        eliminado          boolean     NOT NULL,
        derivados          jsonb       NOT NULL,
        proxima_transicion timestamptz,
        PRIMARY KEY (usuario_id, viaje_id)
    );
    CREATE INDEX IF NOT EXISTS viaje_por_transicion
        ON viaje (proxima_transicion) WHERE proxima_transicion IS NOT NULL;
    """,
    """
    CREATE TABLE IF NOT EXISTS viaje_reserva (
        usuario_id uuid    NOT NULL,
        viaje_id   uuid    NOT NULL,
        reserva_id uuid    NOT NULL,
        fijada     boolean NOT NULL,
        resumen    jsonb   NOT NULL,
        PRIMARY KEY (usuario_id, viaje_id, reserva_id),
        CONSTRAINT reserva_en_un_viaje UNIQUE (usuario_id, reserva_id),
        FOREIGN KEY (usuario_id, viaje_id) REFERENCES viaje ON DELETE CASCADE
    );
    """,
)


class RepositorioDeViajesPostgres:
    def __init__(self, conexion: psycopg.Connection, registro: RegistroDeTipos,
                 gracia: timedelta = GRACIA_DE_ARCHIVADO):
        self._conexion, self._registro, self._gracia = conexion, registro, gracia
        self._cargados: dict[UUID, Viaje] = {}

    # --- lectura -------------------------------------------------------------------------

    def obtener(self, usuario_id: UUID, viaje_id: UUID) -> Viaje | None:
        viaje_id = UUID(str(viaje_id))
        if viaje_id in self._cargados:
            cargado = self._cargados[viaje_id]
            return cargado if str(cargado.usuario_id) == str(usuario_id) else None
        fila = self._conexion.execute("SELECT * FROM viaje WHERE usuario_id = %s AND viaje_id = %s",
                                      (str(usuario_id), str(viaje_id))).fetchone()
        if fila is None:
            return None
        viaje = self._reconstruir(fila)
        self._cargados[viaje_id] = viaje
        return viaje

    def de_reserva(self, usuario_id: UUID, reserva_id: UUID) -> Viaje | None:
        for viaje in self._cargados.values():  # lo cargado puede tener cambios sin guardar
            if str(viaje.usuario_id) == str(usuario_id) and UUID(str(reserva_id)) in viaje.miembros:
                return viaje
        fila = self._conexion.execute(
            "SELECT viaje_id FROM viaje_reserva WHERE usuario_id = %s AND reserva_id = %s",
            (str(usuario_id), str(reserva_id))).fetchone()
        if fila is None:
            return None
        viaje = self.obtener(usuario_id, fila["viaje_id"])
        # Si en memoria ya salió de ese viaje (se movió en esta operación), no está en ninguno.
        return viaje if viaje is not None and UUID(str(reserva_id)) in viaje.miembros else None

    def activos(self, usuario_id: UUID) -> list[Viaje]:
        filas = self._conexion.execute(
            "SELECT viaje_id FROM viaje WHERE usuario_id = %s AND estado = ANY(%s) ORDER BY creado_en",
            (str(usuario_id), [EstadoViaje.PLANIFICADO.value, EstadoViaje.EN_CURSO.value])).fetchall()
        return [v for f in filas if (v := self.obtener(usuario_id, f["viaje_id"])) is not None]

    def con_transicion_vencida(self, ahora: datetime, limite: int = 500) -> list[tuple[UUID, UUID]]:
        """Pares (usuario, viaje) que el trabajo programado tiene que avanzar."""
        filas = self._conexion.execute(
            """SELECT usuario_id, viaje_id FROM viaje WHERE proxima_transicion <= %s
               ORDER BY proxima_transicion LIMIT %s""", (ahora, limite)).fetchall()
        return [(f["usuario_id"], f["viaje_id"]) for f in filas]

    # --- escritura -----------------------------------------------------------------------

    def guardar(self, viaje: Viaje) -> None:
        c, u, v = self._conexion, str(viaje.usuario_id), str(viaje.id)
        proxima = viaje.proxima_transicion(self._registro, self._gracia) if viaje.miembros else None
        c.execute(
            """INSERT INTO viaje (usuario_id, viaje_id, estado, version, creado_en, completado_en,
                                  archivado_en, motivo_de_archivo, eliminado, derivados,
                                  proxima_transicion)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (usuario_id, viaje_id) DO UPDATE SET
                   estado = EXCLUDED.estado, version = EXCLUDED.version,
                   completado_en = EXCLUDED.completado_en, archivado_en = EXCLUDED.archivado_en,
                   motivo_de_archivo = EXCLUDED.motivo_de_archivo, eliminado = EXCLUDED.eliminado,
                   derivados = EXCLUDED.derivados, proxima_transicion = EXCLUDED.proxima_transicion""",
            (u, v, viaje.estado.value, viaje.version, viaje.creado_en, viaje.completado_en,
             viaje.archivado_en, viaje.motivo_de_archivo, viaje.eliminado,
             Jsonb(viaje.derivados), proxima))
        # Una reserva movida a este viaje sale de donde estaba, aunque ese viaje se guarde después.
        miembros = [str(r) for r in viaje.miembros]
        c.execute("""DELETE FROM viaje_reserva WHERE usuario_id = %s
                     AND (viaje_id = %s OR reserva_id = ANY(%s::uuid[]))""", (u, v, miembros))
        for reserva_id, miembro in viaje.miembros.items():
            c.execute("""INSERT INTO viaje_reserva (usuario_id, viaje_id, reserva_id, fijada, resumen)
                         VALUES (%s, %s, %s, %s, %s)""",
                      (u, v, str(reserva_id), miembro.fijada, Jsonb(miembro.resumen.a_dict())))
        self._cargados[viaje.id] = viaje

    # --- reconstrucción ------------------------------------------------------------------

    def _reconstruir(self, fila: Mapping[str, Any]) -> Viaje:
        miembros = self._conexion.execute(
            "SELECT * FROM viaje_reserva WHERE usuario_id = %s AND viaje_id = %s",
            (fila["usuario_id"], fila["viaje_id"])).fetchall()
        return Viaje(
            id=fila["viaje_id"], usuario_id=fila["usuario_id"], creado_en=fila["creado_en"],
            version=fila["version"], estado=EstadoViaje(fila["estado"]),
            miembros={m["reserva_id"]: Miembro(ResumenDeReserva.desde_dict(m["resumen"]), m["fijada"])
                      for m in miembros},
            completado_en=fila["completado_en"], archivado_en=fila["archivado_en"],
            motivo_de_archivo=fila["motivo_de_archivo"], eliminado=fila["eliminado"],
            derivados=fila["derivados"])
