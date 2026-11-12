"""El elemento `itinerary`: arma los módulos de la vista N2 y define las transacciones.

No es un módulo de la vista sino su punto de armado: es el único que conoce a todos (la prueba
de arquitectura lo declara así). Cada comando del usuario y cada evento consumido es **una**
transacción de PostgreSQL (ADR-0012):

1. bloquea al usuario: nada más escribe a la vez para él (partición por usuario, ADR-0018);
2. aplica `gestion_manual` o `ingesta` sobre el repositorio de `reservas`;
3. si hubo cambios, sube `versionUsuario` (contador monótono por usuario, ADR-0018);
4. escribe los eventos en la *outbox* (`publicacion`) y actualiza la lectura (`proyeccion_panel`).

O se confirma todo o no queda nada: no hay eventos sin cambio ni cambios sin evento.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterator, Mapping
from uuid import UUID

import psycopg
from fastapi import FastAPI

from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    crear_esquema,
    guardar_respuesta,
    huella_de_solicitud,
    respuesta_guardada,
    transaccion,
)
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, registro_por_omision
from trotamundos.servicios.itinerary import (
    api,
    gestion_manual,
    ingesta,
    proyeccion_panel,
    publicacion,
)
from trotamundos.servicios.itinerary.fusion.eventos import Causa
from trotamundos.servicios.itinerary.reservas import repositorio

ESQUEMA = "itinerary"
DDL = (
    *repositorio.DDL,
    *proyeccion_panel.DDL,
    """
    CREATE TABLE IF NOT EXISTS usuario_version (
        usuario_id uuid   PRIMARY KEY,
        version    bigint NOT NULL
    );
    """,
)


class Itinerary:
    """Los comandos, lecturas y eventos de `itinerary`, cada uno en su transacción."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, registro: RegistroDeTipos | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._registro = registro or registro_por_omision()
        self._reloj = reloj

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- comandos del usuario (gestion_manual) -------------------------------------------

    def crear_reserva(self, usuario_id: UUID, clave: UUID, cuerpo: Mapping[str, Any], *,
                      traceparent: str | None = None) -> tuple[int, dict[str, Any]]:
        """Alta idempotente por `Idempotency-Key`: la misma clave con la misma solicitud devuelve
        la misma respuesta sin repetir el efecto; con otra solicitud, es un error (ADR-0014)."""
        huella = huella_de_solicitud(cuerpo)
        with self._transaccion(usuario_id) as conexion:
            guardada = respuesta_guardada(conexion, usuario_id, clave)
            if guardada is not None:
                if (guardada.operacion, guardada.huella) != ("crearReserva", huella):
                    raise gestion_manual.SolicitudInvalida(
                        "La Idempotency-Key ya se usó con otra solicitud",
                        [{"campo": "Idempotency-Key", "mensaje": "usar una clave nueva"}])
                return guardada.estado, guardada.cuerpo
            resultado = gestion_manual.crear(self._contexto(conexion, usuario_id, traceparent),
                                             cuerpo, clave)
            respuesta = resultado.cuerpo(self._publicar(conexion, usuario_id, resultado.eventos))
            guardar_respuesta(conexion, usuario_id, clave,
                              RespuestaGuardada("crearReserva", huella, 201, respuesta))
            return 201, respuesta

    def editar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                       traceparent: str | None = None) -> dict[str, Any]:
        return self._comando(usuario_id, traceparent,
                             lambda ctx: gestion_manual.editar(ctx, reserva_id, cuerpo))

    def eliminar_reserva(self, usuario_id: UUID, reserva_id: UUID, *,
                         traceparent: str | None = None) -> None:
        self._comando(usuario_id, traceparent, lambda ctx: gestion_manual.dar_de_baja(ctx, reserva_id))

    def confirmar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                          traceparent: str | None = None) -> dict[str, Any]:
        return self._comando(usuario_id, traceparent,
                             lambda ctx: gestion_manual.confirmar(ctx, reserva_id, cuerpo))

    def resolver_conflicto(self, usuario_id: UUID, reserva_id: UUID, conflicto_id: UUID,
                           cuerpo: Mapping[str, Any], *,
                           traceparent: str | None = None) -> dict[str, Any]:
        return self._comando(usuario_id, traceparent, lambda ctx: gestion_manual.resolver_conflicto(
            ctx, reserva_id, conflicto_id, cuerpo))

    # --- lecturas (proyeccion_panel) -----------------------------------------------------

    def leer_reserva(self, usuario_id: UUID, reserva_id: UUID) -> dict[str, Any] | None:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            return proyeccion_panel.leer_reserva(conexion, usuario_id, reserva_id)

    def tipos_de_segmento(self) -> list[dict[str, Any]]:
        return self._registro.documentos()

    # --- eventos consumidos (ingesta) ----------------------------------------------------

    def consumir(self, evento: Evento) -> list[Evento]:
        """Procesa un `ReservaExtraida` o `ReservaObservada`; devuelve lo que quedó en la outbox.
        Un evento que no cumple el contrato lanza `ErrorDeContrato` sin dejar nada escrito."""
        with self._transaccion(evento.sobre.get("usuarioId", "")) as conexion:
            eventos = ingesta.procesar(
                conexion, evento, repositorio.RepositorioDeReservasPostgres(conexion, self._registro),
                self._contratos, self._reloj(), self._configuracion.region)
            self._publicar(conexion, evento.sobre["usuarioId"], eventos)
            return eventos

    # --- transacciones -------------------------------------------------------------------

    @contextmanager
    def _transaccion(self, usuario_id: UUID | str) -> Iterator[psycopg.Connection]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _contexto(self, conexion: psycopg.Connection, usuario_id: UUID,
                  traceparent: str | None) -> gestion_manual.Contexto:
        return gestion_manual.Contexto(
            repositorio.RepositorioDeReservasPostgres(conexion, self._registro), self._registro,
            usuario_id, self._reloj(),
            Causa(region=self._configuracion.region, traceparent=traceparent))

    def _comando(self, usuario_id: UUID, traceparent: str | None,
                 ejecutar: Callable[[gestion_manual.Contexto], gestion_manual.Resultado]
                 ) -> dict[str, Any]:
        with self._transaccion(usuario_id) as conexion:
            resultado = ejecutar(self._contexto(conexion, usuario_id, traceparent))
            return resultado.cuerpo(self._publicar(conexion, usuario_id, resultado.eventos))

    def _publicar(self, conexion: psycopg.Connection, usuario_id: UUID | str,
                  eventos: list[Evento] | tuple[Evento, ...]) -> int:
        """Outbox y lectura en la misma transacción; devuelve `versionUsuario`."""
        publicacion.registrar(conexion, eventos, self._contratos)
        proyeccion_panel.aplicar(conexion, eventos)
        if not eventos:
            fila = conexion.execute("SELECT version FROM usuario_version WHERE usuario_id = %s",
                                    (str(usuario_id),)).fetchone()
            return fila["version"] if fila else 0
        return conexion.execute(
            """INSERT INTO usuario_version (usuario_id, version) VALUES (%s, 1)
               ON CONFLICT (usuario_id) DO UPDATE SET version = usuario_version.version + 1
               RETURNING version""", (str(usuario_id),)).fetchone()["version"]

    # --- API -----------------------------------------------------------------------------

    def app(self) -> FastAPI:
        """La API interna sobre este elemento; al arrancar crea el esquema si no existe."""
        @asynccontextmanager
        async def al_arrancar(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            yield

        return api.crear_app(self, self._contratos, lifespan=al_arrancar)


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.itinerary.servicio:crear_app`."""
    return Itinerary().app()
