"""Atomicidad, deduplicación y privacidad de booking-extraction contra PostgreSQL."""

import copy
import dataclasses
from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest

from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.booking_extraction.servicio import BookingExtraction

USUARIO = "00000000-0000-4000-8000-0000000000d9"


def mensaje(*, buzon=None, identificador="correo-1", cuerpo="contenido privado inédito"):
    return Evento.nuevo("MensajeDeViajeRecibido", {
        "buzonId": str(buzon or uuid4()), "idDeMensaje": identificador,
        "mensaje": {"remitente": "reservas@desconocido.example", "asunto": "Aviso " + "x" * 100,
                    "recibidoEn": "2026-11-18T14:00:00Z", "cuerpoTexto": cuerpo}},
        productor="mail-ingest", usuario_id=USUARIO, region="AM",
        id_de_correlacion="prueba-paso-9")


@pytest.fixture
def extraccion(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    servicio = BookingExtraction(configuracion, esquema=esquema, contratos=contratos)
    servicio.crear_esquema()
    return servicio


def filas(servicio, consulta):
    with conectar(servicio._configuracion.dsn_postgres, servicio._esquema) as conexion:
        return conexion.execute(consulta).fetchall()


def test_desconocido_publica_una_salida_segura_y_deduplica_evento_y_correo(extraccion, contratos):
    entrada = mensaje()
    extraccion.consumir(entrada)
    extraccion.consumir(entrada)
    repetido = dataclasses.replace(entrada, sobre={**entrada.sobre, "idDeEvento": str(uuid4())})
    extraccion.consumir(repetido)
    salidas = filas(extraccion, "SELECT * FROM bandeja_salida")
    assert len(salidas) == 1
    salida = salidas[0]
    assert salida["tipo"] == "ExtraccionNoReconocida"
    assert salida["carga"]["motivo"] == "formatoDesconocido"
    assert len(salida["carga"]["asuntoTruncado"]) == 80
    assert salida["sobre"]["idDeCausa"] == entrada.id
    assert salida["sobre"]["idDeCorrelacion"] == "prueba-paso-9"
    assert salida["carril"] == "P2"
    Evento(salida["tipo"], salida["sobre"], salida["carga"]).validar(contratos)
    for tabla in ("bandeja_entrada", "mensaje_procesado", "bandeja_salida", "evento_rechazado"):
        datos = json.dumps(filas(extraccion, f"SELECT * FROM {tabla}"), default=str)
        assert "contenido privado inédito" not in datos
        assert "cuerpoTexto" not in datos


def test_correo_invalido_no_se_marca_como_procesado(extraccion):
    entrada = mensaje()
    entrada.carga["mensaje"].pop("remitente")
    with pytest.raises(ErrorDeContrato):
        extraccion.consumir(entrada)
    assert filas(extraccion, "SELECT * FROM bandeja_entrada") == []
    assert filas(extraccion, "SELECT * FROM mensaje_procesado") == []
    assert filas(extraccion, "SELECT * FROM bandeja_salida") == []


def test_falla_de_outbox_revierte_inbox_deduplicacion_y_calidad(extraccion, monkeypatch):
    from trotamundos.servicios.booking_extraction import publicacion

    entrada = mensaje()
    calidad_previa = copy.deepcopy(vars(extraccion.motor.calidad))
    registrar = publicacion.registrar

    def fallar(*args):
        raise RuntimeError("caída antes del commit")

    monkeypatch.setattr(publicacion, "registrar", fallar)
    with pytest.raises(RuntimeError):
        extraccion.consumir(entrada)
    assert vars(extraccion.motor.calidad) == calidad_previa
    for tabla in ("bandeja_entrada", "mensaje_procesado", "bandeja_salida"):
        assert filas(extraccion, f"SELECT * FROM {tabla}") == []
    monkeypatch.setattr(publicacion, "registrar", registrar)
    extraccion.consumir(entrada)
    assert len(filas(extraccion, "SELECT * FROM bandeja_salida")) == 1


def test_dos_buzones_con_mismo_id_son_dos_correos(extraccion):
    extraccion.consumir(mensaje())
    extraccion.consumir(mensaje())
    assert len(filas(extraccion, "SELECT * FROM mensaje_procesado")) == 2
    assert len(filas(extraccion, "SELECT * FROM bandeja_salida")) == 2


@pytest.mark.parametrize('rotulo,estado', [('Localizador', 'Confirmada'),
                                          ('Localizador tentativo', 'PorConfirmar')])
def test_reserva_extraida_llega_al_panel_segun_su_banda(extraccion, rotulo, estado):
    from uuid import UUID
    from tests.booking_extraction.test_extraccion import carga
    from trotamundos.servicios.itinerary.servicio import Itinerary

    datos = carga()
    datos['mensaje']['cuerpoTexto'] = datos['mensaje']['cuerpoTexto'].replace('Localizador:', rotulo + ':')
    entrada = Evento.nuevo('MensajeDeViajeRecibido', datos, productor='mail-ingest',
                           usuario_id=USUARIO, region='AM')
    extraccion.consumir(entrada)
    [salida] = filas(extraccion, 'SELECT * FROM bandeja_salida')
    # Esquema efímero compartido solo en esta prueba; en Compose son esquemas distintos.
    itinerary = Itinerary(extraccion._configuracion, esquema=extraccion._esquema,
                          reloj=lambda: datetime(2026, 11, 18, tzinfo=timezone.utc))
    itinerary.crear_esquema()
    evento = Evento(salida['tipo'], salida['sobre'], salida['carga'])
    itinerary.consumir(evento)
    itinerary.consumir(evento)
    panel = itinerary.leer_panel(UUID(USUARIO))
    reservas = panel['porConfirmar'] if estado == 'PorConfirmar' else [
        r for viaje in panel['viajesActivos'] for r in viaje['reservas']]
    assert len(reservas) == 1 and reservas[0]['estado'] == estado
    assert len(panel['porConfirmar']) == (1 if estado == 'PorConfirmar' else 0)
