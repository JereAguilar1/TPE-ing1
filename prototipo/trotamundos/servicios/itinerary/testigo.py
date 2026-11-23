"""Módulo `testigo`: el registro testigo transregional de los comandos manuales (ADR-0018, QA-05).

Antes de responder `2xx` a un comando manual, `itinerary-escritura` de la región primaria deja una
entrada compacta en la base de la **región de respaldo**: la operación, sus argumentos y los
**ids e instantes que generó**. Si el testigo no responde, el comando no se confirma (`503`): así
ningún comando confirmado queda solo en la región que se puede caer (`RPO = 0`).

La región de respaldo reproduce las entradas pendientes de un usuario la primera vez que lo
atiende, antes de responderle (lo que ADR-0018 llama «aplicar el registro testigo antes de abrir
escrituras locales»). Solo lo atiende si el *gateway* conmutó porque su región primaria cayó. La
reproducción usa la misma `Cinta`: el reloj y los ids salen de la entrada y no del azar, de modo
que la reserva queda con el mismo id, los mismos instantes y la misma `versionUsuario` que en la
región primaria, y `X-Min-Version` sigue sirviendo.

Simplificación del prototipo: lo ingerido por correo o por proveedores no se replica (en
producción, la replicación asíncrona continua de ADR-0018). Si una entrada no se puede reproducir
(por ejemplo, edita una reserva ingerida que la región de respaldo no tiene), queda registrada con
su error y no frena a las siguientes.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator, Sequence
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ESQUEMA = "testigo"
DDL = (
    """
    CREATE TABLE IF NOT EXISTS registro_testigo (
        secuencia     bigserial   PRIMARY KEY,
        usuario_id    uuid        NOT NULL,
        region_origen text        NOT NULL,
        operacion     text        NOT NULL,
        argumentos    jsonb       NOT NULL,
        ids           jsonb       NOT NULL,
        instantes     jsonb       NOT NULL,
        registrado_en timestamptz NOT NULL DEFAULT now(),
        aplicado_en   timestamptz,
        error         text
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS testigo_pendiente ON registro_testigo (usuario_id, secuencia)
        WHERE aplicado_en IS NULL;
    """,
)
# El testigo está en otra región: si no contesta en este tiempo, el comando no se confirma.
ESPERA_DE_CONEXION_S = 2

_registro_de_errores = logging.getLogger(__name__)


class RespaldoNoDisponible(Exception):
    """No se pudo escribir la entrada en la región de respaldo."""


# --- la cinta: los ids y los instantes de un comando ------------------------------------------

@dataclass
class Cinta:
    """Lo que un comando tomó del reloj y del generador de ids, en orden. Al grabar se llena;
    al reproducir se lee (y si se agota, sigue con los reales)."""

    ids: list[str] = field(default_factory=list)
    instantes: list[str] = field(default_factory=list)
    reproduciendo: bool = False
    _proximo_id: int = 0
    _proximo_instante: int = 0

    def id(self, real: Callable[[], UUID]) -> UUID:
        if self.reproduciendo and self._proximo_id < len(self.ids):
            self._proximo_id += 1
            return UUID(self.ids[self._proximo_id - 1])
        valor = real()
        if not self.reproduciendo:
            self.ids.append(str(valor))
        return valor

    def instante(self, real: Callable[[], datetime]) -> datetime:
        if self.reproduciendo and self._proximo_instante < len(self.instantes):
            self._proximo_instante += 1
            return datetime.fromisoformat(self.instantes[self._proximo_instante - 1])
        valor = real()
        if not self.reproduciendo:
            self.instantes.append(valor.isoformat())
        return valor


_cinta: ContextVar[Cinta | None] = ContextVar("cinta_del_testigo", default=None)


@contextmanager
def con_cinta(cinta: Cinta) -> Iterator[Cinta]:
    marca = _cinta.set(cinta)
    try:
        yield cinta
    finally:
        _cinta.reset(marca)


def reloj_con_cinta(real: Callable[[], datetime]) -> Callable[[], datetime]:
    def reloj() -> datetime:
        cinta = _cinta.get()
        return real() if cinta is None else cinta.instante(real)
    return reloj


def ids_con_cinta(real: Callable[[], UUID]) -> Callable[[], UUID]:
    def nuevo_id() -> UUID:
        cinta = _cinta.get()
        return real() if cinta is None else cinta.id(real)
    return nuevo_id


@contextmanager
def en_orden(dsn: str, usuario_id: UUID | str) -> Iterator[None]:
    """Serializa, en la región primaria, cada comando manual del usuario junto con su entrada en
    el testigo. Es un bloqueo consultivo de sesión con otra clave que el de las transacciones de
    `itinerary` (que dura solo cada transacción) y que el de la reproducción."""
    clave = f"testigo-orden:{usuario_id}"
    with psycopg.connect(dsn, autocommit=True) as conexion:
        conexion.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (clave,))
        try:
            yield
        finally:
            conexion.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (clave,))


def a_json(argumentos: Sequence[Any]) -> list[Any]:
    """Los argumentos de un comando: ids (como texto) y cuerpos JSON."""
    return [str(a) if isinstance(a, UUID) else a for a in argumentos]


def de_json(argumentos: Sequence[Any]) -> list[Any]:
    return [UUID(a) if isinstance(a, str) else a for a in argumentos]


# --- el registro ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entrada:
    secuencia: int
    operacion: str
    argumentos: list[Any]
    cinta: Cinta


class RegistroTestigo:
    """La tabla `registro_testigo` de una región, en el esquema `testigo` de su base."""

    def __init__(self, dsn: str, esquema: str = ESQUEMA):
        self._dsn, self._esquema = dsn, esquema
        self._creado = False

    def _conectar(self, **opciones: Any) -> psycopg.Connection:
        return psycopg.connect(self._dsn, row_factory=dict_row,
                               connect_timeout=ESPERA_DE_CONEXION_S,
                               options=f"-c search_path={self._esquema}", **opciones)

    def crear_esquema(self) -> None:
        with self._conectar() as conexion:
            conexion.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(self._esquema)))
            for sentencia in DDL:
                conexion.execute(sentencia)
        self._creado = True

    # --- en la región primaria: grabar ---

    def registrar(self, usuario_id: UUID, region_origen: str, operacion: str,
                  argumentos: Sequence[Any], cinta: Cinta) -> None:
        """Escribe la entrada y vuelve recién cuando la región de respaldo la confirmó."""
        try:
            if not self._creado:
                self.crear_esquema()
            with self._conectar() as conexion:
                conexion.execute(
                    """INSERT INTO registro_testigo
                           (usuario_id, region_origen, operacion, argumentos, ids, instantes)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (str(usuario_id), region_origen, operacion, Jsonb(a_json(argumentos)),
                     Jsonb(cinta.ids), Jsonb(cinta.instantes)))
        except psycopg.Error as error:
            raise RespaldoNoDisponible(str(error)) from error

    def borrar_usuario(self, usuario_id: UUID) -> int:
        """Supresión de fase 1 (ADR-0030): el testigo también guarda datos del usuario."""
        try:
            with self._conectar() as conexion:
                return conexion.execute("DELETE FROM registro_testigo WHERE usuario_id = %s",
                                        (str(usuario_id),)).rowcount
        except psycopg.errors.UndefinedTable:
            return 0

    # --- en la región de respaldo: reproducir ---

    def aplicar_pendientes(self, usuario_id: UUID,
                           reproducir: Callable[[Entrada], None],
                           es_error_de_comando: Callable[[Exception], bool]) -> int:
        """Reproduce en orden las entradas pendientes del usuario; devuelve cuántas aplicó.

        Un bloqueo consultivo por usuario (distinto del de las transacciones de `itinerary`) evita
        que dos procesos de la región reproduzcan la misma entrada."""
        with self._conectar(autocommit=True) as conexion:
            try:
                hay = conexion.execute(
                    "SELECT 1 FROM registro_testigo WHERE usuario_id = %s AND aplicado_en IS NULL "
                    "LIMIT 1", (str(usuario_id),)).fetchone()
            except psycopg.errors.UndefinedTable:
                return 0
            if hay is None:
                return 0
            clave = f"testigo:{usuario_id}"
            conexion.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (clave,))
            try:
                filas = conexion.execute(
                    """SELECT secuencia, operacion, argumentos, ids, instantes
                       FROM registro_testigo WHERE usuario_id = %s AND aplicado_en IS NULL
                       ORDER BY secuencia""", (str(usuario_id),)).fetchall()
                for fila in filas:
                    entrada = Entrada(fila["secuencia"], fila["operacion"],
                                      de_json(fila["argumentos"]),
                                      Cinta(list(fila["ids"]), list(fila["instantes"]), True))
                    error = None
                    try:
                        reproducir(entrada)
                    except Exception as falla:
                        if not es_error_de_comando(falla):
                            raise  # la base no responde: se reintenta en el próximo pedido
                        error = f"{type(falla).__name__}: {falla}"
                        _registro_de_errores.warning(
                            "No se pudo reproducir la entrada %s del testigo: %s",
                            entrada.secuencia, error)
                    conexion.execute(
                        "UPDATE registro_testigo SET aplicado_en = now(), error = %s "
                        "WHERE secuencia = %s", (error, entrada.secuencia))
                return len(filas)
            finally:
                conexion.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (clave,))
