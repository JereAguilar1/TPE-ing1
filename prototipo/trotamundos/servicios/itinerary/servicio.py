"""El elemento `itinerary`: arma los módulos de la vista N2 y define las transacciones.

No es un módulo de la vista sino su punto de armado: es el único que conoce a todos (la prueba
de arquitectura lo declara así). Toda transacción (ADR-0012):

1. bloquea al usuario: nada más escribe a la vez para él (partición por usuario, ADR-0018);
2. aplica el cambio sobre **un solo agregado**: `Reserva` o `Viaje`, nunca los dos (ADR-0010);
3. si hubo cambios, sube `versionUsuario` (contador monótono por usuario, ADR-0018);
4. escribe los eventos en la *outbox* (`publicacion`) y actualiza las lecturas
   (`proyeccion_panel`). O se confirma todo o no queda nada.

Con un *broker* configurado, el elemento también publica su *outbox* y consume `ReservaExtraida`
y `ReservaObservada` por carriles de prioridad (`comun.publicador`, `comun.consumidor`; ADR-0012,
ADR-0014, ADR-0020).

`Reserva` y `Viaje` se coordinan por eventos internos (ADR-0010): cada `ReservaActualizada` queda
también en `evento_interno`, en la misma transacción que el cambio, y `viajes` la procesa en una
segunda transacción. Un comando espera a las dos para responder con el viaje (la mitigación que
prevé ADR-0010). Si la segunda falla, el evento sigue en la cola y lo procesa el trabajo
periódico, que además avanza el ciclo de vida de los viajes (RF-08) y purga lo vencido.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterator, Mapping
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI
from psycopg.types.json import Jsonb

from trotamundos.comun.carriles import Carril, asegurar_topicos, carriles_posibles, topico
from trotamundos.comun.config import Configuracion
from trotamundos.comun.consumidor import DDL_RECHAZADOS, ConsumidorConCarriles
from trotamundos.comun.contratos import Contratos, contratos_por_omision
from trotamundos.comun.eventos import Causa, Evento
from trotamundos.comun.modelo import instante_a_texto
from trotamundos.comun.persistencia import (
    RespuestaGuardada,
    bloquear_usuario,
    crear_esquema,
    guardar_respuesta,
    huella_de_solicitud,
    purgar,
    reemplazar_respuesta,
    respuesta_guardada,
    transaccion,
)
from trotamundos.comun.publicador import PublicadorDeOutbox
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos, registro_por_omision
from trotamundos.servicios.itinerary import (
    api,
    gestion_manual,
    ingesta,
    proyeccion_panel,
    publicacion,
)
from trotamundos.servicios.itinerary.reservas import repositorio as reservas
from trotamundos.servicios.itinerary.viajes import operaciones as viajes
from trotamundos.servicios.itinerary.viajes import repositorio as repositorio_de_viajes

ESQUEMA = "itinerary"
DDL = (
    *reservas.DDL,
    *repositorio_de_viajes.DDL,
    *proyeccion_panel.DDL,
    *DDL_RECHAZADOS,
    """
    CREATE TABLE IF NOT EXISTS usuario_version (
        usuario_id uuid   PRIMARY KEY,
        version    bigint NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS evento_interno (
        usuario_id uuid        NOT NULL,
        seq        bigserial   NOT NULL,
        evento_id  uuid        NOT NULL,
        tipo       text        NOT NULL,
        sobre      jsonb       NOT NULL,
        carga      jsonb       NOT NULL,
        creado_en  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (usuario_id, seq),
        UNIQUE (usuario_id, evento_id)
    );
    """,
)
# Lo que `viajes` necesita saber de `reservas` (ADR-0010: se coordinan por eventos internos).
PARA_VIAJES = frozenset({"ReservaActualizada"})
GRUPO = "itinerary"  # grupo de consumidores en el broker
PAUSA_DEL_PUBLICADOR_S = 0.5

_registro_de_errores = logging.getLogger(__name__)


class Itinerary:
    """Los comandos, lecturas y eventos de `itinerary`, cada uno en sus transacciones."""

    def __init__(self, configuracion: Configuracion | None = None, *, esquema: str = ESQUEMA,
                 contratos: Contratos | None = None, registro: RegistroDeTipos | None = None,
                 reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 nuevo_id: Callable[[], UUID] = uuid4):
        self._configuracion = configuracion or Configuracion.desde_entorno()
        self._esquema = esquema
        self._contratos = contratos or contratos_por_omision()
        self._registro = registro or registro_por_omision()
        self._reloj = reloj
        self._nuevo_id = nuevo_id

    def crear_esquema(self) -> None:
        crear_esquema(self._configuracion.dsn_postgres, self._esquema, DDL)

    # --- comandos sobre reservas: la reserva y después sus viajes --------------------------

    def crear_reserva(self, usuario_id: UUID, clave: UUID, cuerpo: Mapping[str, Any], *,
                      traceparent: str | None = None) -> tuple[int, dict[str, Any]]:
        """Alta idempotente por `Idempotency-Key`: la misma clave con la misma solicitud devuelve
        la misma respuesta sin repetir el efecto; con otra solicitud, es un error (ADR-0014).
        Con `viajeId`, la reserva queda en ese viaje, fijada."""
        huella = huella_de_solicitud(cuerpo)
        viaje_pedido = UUID(cuerpo["viajeId"]) if "viajeId" in cuerpo else None
        with self._transaccion(usuario_id) as conexion:
            guardada = respuesta_guardada(conexion, usuario_id, clave)
            if guardada is not None:
                if (guardada.operacion, guardada.huella) != ("crearReserva", huella):
                    raise gestion_manual.SolicitudInvalida(
                        "La Idempotency-Key ya se usó con otra solicitud",
                        [{"campo": "Idempotency-Key", "mensaje": "usar una clave nueva"}])
                return guardada.estado, guardada.cuerpo
            if viaje_pedido is not None and proyeccion_panel.leer_viaje(
                    conexion, usuario_id, viaje_pedido) is None:
                raise gestion_manual.SolicitudInvalida(
                    "El viaje indicado no existe", [{"campo": "viajeId", "mensaje": "no existe"}])
            resultado = gestion_manual.crear(self._contexto(conexion, usuario_id, traceparent),
                                             cuerpo, clave)
            version = self._publicar(conexion, usuario_id, resultado.eventos)
            guardar_respuesta(conexion, usuario_id, clave, RespuestaGuardada(
                "crearReserva", huella, 201, resultado.cuerpo(version)))

        asignar = (resultado.reserva.id, viaje_pedido) if viaje_pedido else None
        with self._transaccion(usuario_id) as conexion:
            _, version, viaje_id = self._reaccionar_viajes(conexion, usuario_id, traceparent,
                                                           resultado.reserva.id, asignar)
            respuesta = _con_viaje(resultado.cuerpo(version), viaje_id)
            reemplazar_respuesta(conexion, usuario_id, clave, respuesta)
        return 201, respuesta

    def editar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                       traceparent: str | None = None) -> dict[str, Any]:
        return self._comando_de_reserva(usuario_id, traceparent,
                                        lambda ctx: gestion_manual.editar(ctx, reserva_id, cuerpo))

    def eliminar_reserva(self, usuario_id: UUID, reserva_id: UUID, *,
                         traceparent: str | None = None) -> None:
        self._comando_de_reserva(usuario_id, traceparent,
                                 lambda ctx: gestion_manual.dar_de_baja(ctx, reserva_id))

    def confirmar_reserva(self, usuario_id: UUID, reserva_id: UUID, cuerpo: Mapping[str, Any], *,
                          traceparent: str | None = None) -> dict[str, Any]:
        return self._comando_de_reserva(usuario_id, traceparent,
                                        lambda ctx: gestion_manual.confirmar(ctx, reserva_id, cuerpo))

    def resolver_conflicto(self, usuario_id: UUID, reserva_id: UUID, conflicto_id: UUID,
                           cuerpo: Mapping[str, Any], *,
                           traceparent: str | None = None) -> dict[str, Any]:
        return self._comando_de_reserva(usuario_id, traceparent, lambda ctx: (
            gestion_manual.resolver_conflicto(ctx, reserva_id, conflicto_id, cuerpo)))

    # --- comandos sobre viajes: una transacción, solo viajes -----------------------------

    def mover_reserva(self, usuario_id: UUID, viaje_id: UUID, reserva_id: UUID, *,
                      traceparent: str | None = None) -> None:
        self._comando_de_viaje(usuario_id, traceparent,
                               lambda sesion: gestion_manual.mover_reserva(sesion, reserva_id, viaje_id))

    def archivar_viaje(self, usuario_id: UUID, viaje_id: UUID, *,
                       traceparent: str | None = None) -> None:
        self._comando_de_viaje(usuario_id, traceparent,
                               lambda sesion: gestion_manual.archivar_viaje(sesion, viaje_id))

    def eliminar_viaje(self, usuario_id: UUID, viaje_id: UUID, *,
                       traceparent: str | None = None) -> None:
        self._comando_de_viaje(usuario_id, traceparent,
                               lambda sesion: gestion_manual.eliminar_viaje(sesion, viaje_id))

    # --- lecturas (proyeccion_panel) -----------------------------------------------------

    def leer_panel(self, usuario_id: UUID) -> dict[str, Any]:
        with self._lectura() as conexion:
            return proyeccion_panel.leer_panel(conexion, usuario_id)

    def leer_reserva(self, usuario_id: UUID, reserva_id: UUID) -> dict[str, Any] | None:
        with self._lectura() as conexion:
            return proyeccion_panel.leer_reserva(conexion, usuario_id, reserva_id)

    def leer_viaje(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None:
        with self._lectura() as conexion:
            return proyeccion_panel.leer_viaje(conexion, usuario_id, viaje_id)

    def leer_instantanea(self, usuario_id: UUID, viaje_id: UUID) -> dict[str, Any] | None:
        """El viaje tal como está ahora, con el instante de la consulta (UC-7)."""
        viaje = self.leer_viaje(usuario_id, viaje_id)
        return None if viaje is None else {"viaje": viaje, "tomadaEn": instante_a_texto(self._reloj())}

    def leer_viajes(self, usuario_id: UUID, *, estado: str | None = None, cursor: str | None = None,
                    limite: int = 20) -> dict[str, Any]:
        with self._lectura() as conexion:
            pagina, siguiente = proyeccion_panel.leer_viajes(
                conexion, usuario_id, self._reloj(), estado=estado, cursor=cursor, limite=limite)
        return {"viajes": pagina, "siguienteCursor": siguiente}

    def tipos_de_segmento(self) -> list[dict[str, Any]]:
        return self._registro.documentos()

    # --- eventos consumidos (ingesta) ----------------------------------------------------

    def consumir(self, evento: Evento) -> list[Evento]:
        """Procesa un `ReservaExtraida` o `ReservaObservada`; devuelve lo que quedó en la outbox.
        Un evento que no cumple el contrato lanza `ErrorDeContrato` sin dejar nada escrito."""
        with self._transaccion(evento.sobre.get("usuarioId", "")) as conexion:
            eventos = ingesta.procesar(
                conexion, evento, reservas.RepositorioDeReservasPostgres(conexion, self._registro),
                self._contratos, self._reloj(), self._configuracion.region)
            self._publicar(conexion, evento.sobre["usuarioId"], eventos)
        if eventos:
            usuario = UUID(evento.sobre["usuarioId"])
            with self._transaccion(usuario) as conexion:
                eventos += self._reaccionar_viajes(conexion, usuario, None)[0]
        return eventos

    # --- trabajo periódico ---------------------------------------------------------------

    def tareas_periodicas(self) -> None:
        """Lo que corre cada `intervalo_tareas_s`: los eventos internos que quedaron sin
        procesar, las transiciones por tiempo de los viajes (RF-08) y la purga de la bandeja
        de entrada y las claves de idempotencia (ADR-0014)."""
        ahora = self._reloj()
        with self._lectura() as conexion:
            pendientes = [f["usuario_id"] for f in conexion.execute(
                "SELECT DISTINCT usuario_id FROM evento_interno").fetchall()]
            vencidos = repositorio_de_viajes.RepositorioDeViajesPostgres(
                conexion, self._registro).con_transicion_vencida(ahora)
        for usuario in pendientes:
            with self._transaccion(usuario) as conexion:
                self._reaccionar_viajes(conexion, usuario, None)
        for usuario, viaje_id in vencidos:
            with self._transaccion(usuario) as conexion:
                repositorio = repositorio_de_viajes.RepositorioDeViajesPostgres(conexion, self._registro)
                viaje = repositorio.obtener(usuario, viaje_id)
                if viaje is None:
                    continue
                sesion = self._sesion(repositorio, usuario, Causa(region=self._configuracion.region))
                viajes.avanzar(sesion, viaje)
                self._publicar(conexion, usuario, sesion.cerrar())
                repositorio.guardar(viaje)  # también si no cambió: recalcula la próxima transición
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            purgar(conexion, ahora)

    # --- API -----------------------------------------------------------------------------

    def app(self) -> FastAPI:
        """La API interna sobre este elemento, en el modo configurado (ADR-0021).

        `itinerary-lectura` solo atiende las lecturas, servidas por `proyeccion_panel`.
        `itinerary-escritura` atiende los comandos y además corre el trabajo periódico (cada
        `intervalo_tareas_s`; 0 lo apaga) y, con un broker configurado, el publicador de la outbox
        y el consumidor. `completo` hace las dos cosas. Al arrancar, todos crean el esquema si
        no existe."""
        intervalo = self._configuracion.intervalo_tareas_s
        escribe = "comando" in api.MODOS[self._configuracion.modo]

        @asynccontextmanager
        async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
            self.crear_esquema()
            tareas = [asyncio.create_task(self._bucle(intervalo))] if escribe and intervalo > 0 else []
            async with self.con_broker(escribe) as en_marcha:
                tareas += en_marcha
                yield
                for tarea in tareas:
                    tarea.cancel()
                for tarea in tareas:
                    with contextlib.suppress(asyncio.CancelledError):
                        await tarea

        return api.crear_app(self, self._contratos, lifespan=ciclo_de_vida,
                             modo=self._configuracion.modo)

    # --- broker (ADR-0012, ADR-0014, ADR-0020) -------------------------------------------

    def topicos(self) -> tuple[list[str], dict[Carril, list[str]]]:
        """Los tópicos que publica y, por carril, los que consume."""
        prefijo = self._configuracion.prefijo_topicos
        publica = [topico(self._contratos, tipo, carril, prefijo)
                   for tipo in sorted(publicacion.PUBLICA)
                   for carril in carriles_posibles(self._contratos, tipo)]
        consume: dict[Carril, list[str]] = {}
        for tipo in sorted(ingesta.FUENTE_POR_EVENTO):
            for carril in carriles_posibles(self._contratos, tipo):
                consume.setdefault(carril, []).append(
                    topico(self._contratos, tipo, carril, prefijo))
        return publica, consume

    def publicador(self) -> PublicadorDeOutbox:
        c = self._configuracion
        return PublicadorDeOutbox(c.dsn_postgres, self._esquema, c.broker, self._contratos,
                                         c.prefijo_topicos)

    def consumidor(self) -> ConsumidorConCarriles:
        c = self._configuracion
        return ConsumidorConCarriles(c.broker, GRUPO, self.topicos()[1], self.consumir,
                                            c.dsn_postgres, self._esquema)

    @contextlib.asynccontextmanager
    async def con_broker(self, escribe: bool = True) -> AsyncIterator[list[asyncio.Task]]:
        """Arranca el publicador y el consumidor (si hay broker y el modo escribe) y los detiene
        al salir."""
        servidores = self._configuracion.broker
        if not servidores or not escribe:
            yield []
            return
        publica, consume = self.topicos()
        await asegurar_topicos(servidores, publica + [t for ts in consume.values() for t in ts])
        publicador, consumidor = self.publicador(), self.consumidor()
        await publicador.iniciar()
        await consumidor.iniciar()
        detener = asyncio.Event()
        # Referencias propias: el bucle de eventos solo guarda referencias débiles a las tareas.
        publicando = asyncio.create_task(self._publicar_siempre(publicador, detener))
        consumiendo = asyncio.create_task(consumidor.correr(detener))
        try:
            yield [publicando, consumiendo]
        finally:
            detener.set()
            await consumidor.detener()
            await publicador.detener()

    async def _publicar_siempre(self, publicador: PublicadorDeOutbox,
                                detener: asyncio.Event) -> None:
        while not detener.is_set():
            try:
                if await publicador.publicar_pendientes() == 0:
                    await asyncio.sleep(PAUSA_DEL_PUBLICADOR_S)
            except Exception:  # el broker o la base no responden: se reintenta
                _registro_de_errores.exception("Falló la publicación de la outbox de itinerary")
                await asyncio.sleep(PAUSA_DEL_PUBLICADOR_S)

    async def _bucle(self, intervalo: float) -> None:
        while True:
            await asyncio.sleep(intervalo)
            try:
                await asyncio.to_thread(self.tareas_periodicas)
            except Exception:  # el trabajo sigue en la próxima vuelta
                _registro_de_errores.exception("Falló el trabajo periódico de itinerary")

    # --- transacciones -------------------------------------------------------------------

    @contextmanager
    def _transaccion(self, usuario_id: UUID | str) -> Iterator[psycopg.Connection]:
        with transaccion(self._configuracion.dsn_postgres, self._esquema) as conexion:
            bloquear_usuario(conexion, usuario_id)
            yield conexion

    def _lectura(self):
        return transaccion(self._configuracion.dsn_postgres, self._esquema)

    def _contexto(self, conexion: psycopg.Connection, usuario_id: UUID,
                  traceparent: str | None) -> gestion_manual.Contexto:
        return gestion_manual.Contexto(
            reservas.RepositorioDeReservasPostgres(conexion, self._registro), self._registro,
            usuario_id, self._reloj(), Causa(region=self._configuracion.region,
                                             traceparent=traceparent), self._nuevo_id)

    def _sesion(self, repositorio: viajes.RepositorioDeViajes, usuario_id: UUID,
                causa: Causa) -> viajes.Sesion:
        return viajes.Sesion(repositorio, self._registro, usuario_id, self._reloj(), causa,
                             self._nuevo_id)

    def _comando_de_reserva(self, usuario_id: UUID, traceparent: str | None,
                            ejecutar: Callable[[gestion_manual.Contexto], gestion_manual.Resultado]
                            ) -> dict[str, Any]:
        with self._transaccion(usuario_id) as conexion:
            resultado = ejecutar(self._contexto(conexion, usuario_id, traceparent))
            self._publicar(conexion, usuario_id, resultado.eventos)
        with self._transaccion(usuario_id) as conexion:
            _, version, viaje_id = self._reaccionar_viajes(conexion, usuario_id, traceparent,
                                                           resultado.reserva.id)
        return _con_viaje(resultado.cuerpo(version), viaje_id)

    def _comando_de_viaje(self, usuario_id: UUID, traceparent: str | None,
                          ejecutar: Callable[[viajes.Sesion], list[Evento]]) -> None:
        with self._transaccion(usuario_id) as conexion:
            # Primero lo pendiente: la reserva que se mueve puede estar todavía en la cola.
            self._reaccionar_viajes(conexion, usuario_id, traceparent)
            repositorio = repositorio_de_viajes.RepositorioDeViajesPostgres(conexion, self._registro)
            sesion = self._sesion(repositorio, usuario_id,
                                  Causa(region=self._configuracion.region, traceparent=traceparent))
            self._publicar(conexion, usuario_id, ejecutar(sesion))

    def _reaccionar_viajes(self, conexion: psycopg.Connection, usuario_id: UUID,
                           traceparent: str | None, reserva_id: UUID | None = None,
                           asignar: tuple[UUID, UUID] | None = None
                           ) -> tuple[list[Evento], int, UUID | None]:
        """La segunda transacción: `viajes` procesa los eventos internos pendientes del
        usuario (y, en un alta con `viajeId`, la asignación fijada). Devuelve los eventos
        publicados, `versionUsuario` y el viaje en que quedó `reserva_id`."""
        repositorio = repositorio_de_viajes.RepositorioDeViajesPostgres(conexion, self._registro)
        filas = conexion.execute(
            "SELECT seq, tipo, sobre, carga FROM evento_interno WHERE usuario_id = %s ORDER BY seq",
            (str(usuario_id),)).fetchall()
        publicados: list[Evento] = []
        for fila in filas:
            interno = Evento(fila["tipo"], fila["sobre"], fila["carga"])
            sesion = self._sesion(repositorio, usuario_id,
                                  Causa.de_evento(interno, self._configuracion.region))
            viajes.aplicar_reserva(sesion, interno.carga["reserva"],
                                   interno.carga.get("unificadaCon", []))
            publicados += sesion.cerrar()
        conexion.execute("DELETE FROM evento_interno WHERE seq = ANY(%s)", ([f["seq"] for f in filas],))
        if asignar is not None:
            sesion = self._sesion(repositorio, usuario_id,
                                  Causa(region=self._configuracion.region, traceparent=traceparent))
            publicados += gestion_manual.mover_reserva(sesion, *asignar)
        version = self._publicar(conexion, usuario_id, publicados)
        viaje = repositorio.de_reserva(usuario_id, reserva_id) if reserva_id else None
        return publicados, version, (viaje.id if viaje is not None else None)

    def _publicar(self, conexion: psycopg.Connection, usuario_id: UUID | str,
                  eventos: list[Evento] | tuple[Evento, ...]) -> int:
        """Outbox, cola interna y lecturas en la misma transacción; devuelve `versionUsuario`."""
        publicacion.registrar(conexion, eventos, self._contratos, self._reloj())
        for evento in eventos:
            if evento.tipo in PARA_VIAJES:
                conexion.execute(
                    """INSERT INTO evento_interno (usuario_id, evento_id, tipo, sobre, carga)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (str(usuario_id), evento.id, evento.tipo, Jsonb(evento.sobre), Jsonb(evento.carga)))
        if eventos:
            version = conexion.execute(
                """INSERT INTO usuario_version (usuario_id, version) VALUES (%s, 1)
                   ON CONFLICT (usuario_id) DO UPDATE SET version = usuario_version.version + 1
                   RETURNING version""", (str(usuario_id),)).fetchone()["version"]
        else:
            fila = conexion.execute("SELECT version FROM usuario_version WHERE usuario_id = %s",
                                    (str(usuario_id),)).fetchone()
            version = fila["version"] if fila else 0
        proyeccion_panel.aplicar(conexion, eventos, version)
        return version


def _con_viaje(cuerpo: dict[str, Any], viaje_id: UUID | None) -> dict[str, Any]:
    """`ResultadoComandoReserva` con el viaje en que quedó la reserva, si está en uno."""
    if viaje_id is not None:
        cuerpo["viajeId"] = str(viaje_id)
        cuerpo["reserva"]["viajeId"] = str(viaje_id)
    return cuerpo


def crear_app() -> FastAPI:
    """Fábrica para Uvicorn: `uvicorn --factory trotamundos.servicios.itinerary.servicio:crear_app`."""
    return Itinerary().app()
