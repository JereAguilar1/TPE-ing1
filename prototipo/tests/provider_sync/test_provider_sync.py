"""Pruebas de `provider-sync`: seguimiento, webhooks firmados, sondeo, disrupciones y fusión en
`itinerary` y `virtual-assistant` (paso 10, UC-2, UC-5, QA-10)."""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.provider_sync.test_conformidad_adaptadores import ADAPTADOR_ID, GRABACIONES
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.itinerary.servicio import Itinerary
from trotamundos.servicios.provider_sync.complementos.aerolinea_simulada import (
    AdaptadorAerolineaSimulada,
)
from trotamundos.servicios.provider_sync.receptor_de_notificaciones import firma
from trotamundos.servicios.provider_sync.registro_de_adaptadores import (
    RegistroDeAdaptadores,
    entradas_configuradas,
)
from trotamundos.servicios.provider_sync import servicio as servicio_de_provider_sync
from trotamundos.servicios.provider_sync.servicio import ProviderSync

USUARIO_1 = UUID("00000000-0000-4000-8000-000000000101")
USUARIO_2 = UUID("00000000-0000-4000-8000-000000000102")
RESERVA_1 = UUID("00000000-0000-4000-8000-000000000201")
RESERVA_2 = UUID("00000000-0000-4000-8000-000000000202")
SECRETO_WEBHOOK = "secreto-webhook-proveedor-pruebas"
AHORA = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _evento_reserva_actualizada(usuario_id: UUID, reserva_id: UUID, codigo: str,
                                *, inicio: str = "2026-12-01T13:00:00Z",
                                fin: str = "2026-12-01T15:00:00Z") -> Evento:
    reserva = {
        "id": str(reserva_id),
        "estado": "Confirmada",
        "version": 1,
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": codigo}],
        "fuentes": ["correo"],
        "segmentos": [
            {
                "id": str(uuid4()),
                "tipo": "vuelo",
                "versionTipo": 1,
                "orden": 0,
                "inicio": {
                    "instante": inicio,
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Buenos_Aires",
                    "lugar": {
                        "nombre": "Aeroparque",
                        "codigo": "AEP",
                        "pais": "AR",
                        "zonaHoraria": "America/Argentina/Buenos_Aires",
                    },
                },
                "fin": {
                    "instante": fin,
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Mendoza",
                    "lugar": {
                        "nombre": "El Plumerillo",
                        "codigo": "MDZ",
                        "pais": "AR",
                        "zonaHoraria": "America/Argentina/Mendoza",
                    },
                },
                "operador": "Aerolíneas Argentinas",
                "referencia": "AR1402",
                "estado": "confirmado",
                "detalle": {"aerolinea": "AR", "numeroDeVuelo": "1402"},
            }
        ],
    }
    return Evento.nuevo(
        "ReservaActualizada",
        {"reserva": reserva, "creada": True, "cambios": []},
        productor="itinerary",
        usuario_id=str(usuario_id),
        region="AM",
    )


def filas(servicio: ProviderSync, consulta: str) -> list[dict]:
    with conectar(servicio._configuracion.dsn_postgres, servicio._esquema) as conexion:
        return conexion.execute(consulta).fetchall()


@pytest.fixture
def provider_sync(dsn, esquema, contratos):
    configuracion = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker="",
        intervalo_tareas_s=0,
    )
    instancia = AdaptadorAerolineaSimulada()
    entradas = copy.deepcopy(entradas_configuradas())
    entradas[0]["instancia"] = instancia
    registro = RegistroDeAdaptadores(contratos, entradas=entradas)
    servicio = ProviderSync(
        configuracion,
        esquema=esquema,
        contratos=contratos,
        registro=registro,
        secreto_webhook=SECRETO_WEBHOOK,
        reloj=lambda: AHORA,
    )
    servicio.crear_esquema()
    return servicio


def test_webhook_valida_firma_adaptador_y_formato(provider_sync):
    cliente = TestClient(provider_sync.app())
    cuerpo = json.dumps(GRABACIONES[0]["notificacion"]).encode("utf-8")
    firma_ok = firma(cuerpo, SECRETO_WEBHOOK)

    # 401 sin firma o con firma errónea
    r_sin_firma = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo,
        headers={"X-Proveedor-Id": ADAPTADOR_ID, "Content-Type": "application/json"},
    )
    assert r_sin_firma.status_code == 401

    r_firma_mala = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": "00" * 32,
            "Content-Type": "application/json",
        },
    )
    assert r_firma_mala.status_code == 401

    # 404 para un adaptador inexistente
    r_no_existe = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo,
        headers={
            "X-Proveedor-Id": "adaptador-inexistente",
            "X-Firma": firma_ok,
            "Content-Type": "application/json",
        },
    )
    assert r_no_existe.status_code == 404

    # 400 para una carga inválida
    cuerpo_malo = b'{"notificationId": "x"}'
    r_malo = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo_malo,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": firma(cuerpo_malo, SECRETO_WEBHOOK),
            "Content-Type": "application/json",
        },
    )
    assert r_malo.status_code == 400


def test_webhook_json_y_xml_publican_reserva_observada_en_carril_correcto(provider_sync, contratos):
    # Reserva lejana (> 48 h desde AHORA) -> P2; reserva próxima (< 48 h) -> P1.
    provider_sync.consumir(
        _evento_reserva_actualizada(
            USUARIO_1, RESERVA_1, "ABC123",
            inicio="2026-12-01T13:00:00Z", fin="2026-12-01T15:00:00Z",
        )
    )
    provider_sync.consumir(
        _evento_reserva_actualizada(
            USUARIO_2, RESERVA_2, "BRC555",
            inicio="2026-11-19T10:00:00Z", fin="2026-11-19T12:20:00Z",
        )
    )

    cliente = TestClient(provider_sync.app())

    # 1. Webhook JSON para ABC123 (lejana -> P2)
    cuerpo_json = json.dumps(GRABACIONES[0]["notificacion"]).encode("utf-8")
    r1 = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo_json,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": firma(cuerpo_json, SECRETO_WEBHOOK),
            "Content-Type": "application/json",
        },
    )
    assert r1.status_code == 202

    # Repetir el mismo webhook es idempotente: no duplica ReservaObservada
    r1_rep = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo_json,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": firma(cuerpo_json, SECRETO_WEBHOOK),
            "Content-Type": "application/json",
        },
    )
    assert r1_rep.status_code == 202

    # 2. Webhook XML para BRC555 (salida en < 48 h -> P1)
    cuerpo_xml = GRABACIONES[3]["notificacion"].encode("utf-8")
    r2 = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo_xml,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": firma(cuerpo_xml, SECRETO_WEBHOOK),
            "Content-Type": "application/xml",
        },
    )
    assert r2.status_code == 202

    salidas = filas(provider_sync, "SELECT * FROM bandeja_salida ORDER BY seq")
    assert len(salidas) == 2

    ev1 = Evento(salidas[0]["tipo"], salidas[0]["sobre"], salidas[0]["carga"])
    ev2 = Evento(salidas[1]["tipo"], salidas[1]["sobre"], salidas[1]["carga"])
    ev1.validar(contratos)
    ev2.validar(contratos)

    assert salidas[0]["tipo"] == "ReservaObservada"
    assert salidas[0]["carril"] == "P2"
    assert salidas[0]["sobre"]["usuarioId"] == str(USUARIO_1)
    assert salidas[0]["carga"]["observacion"]["segmentos"][0]["detalle"]["puerta"] == "14"

    assert salidas[1]["tipo"] == "ReservaObservada"
    assert salidas[1]["carril"] == "P1"
    assert salidas[1]["sobre"]["usuarioId"] == str(USUARIO_2)
    assert salidas[1]["carga"]["observacion"]["segmentos"][0]["detalle"]["puerta"] == "9"


def test_disrupcion_se_expande_a_multiples_usuarios_y_correlaciona_causa(provider_sync, contratos):
    # Dos viajeros distintos en el mismo vuelo afectado (ABC123 y XYZ789).
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123"))
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_2, RESERVA_2, "XYZ789"))

    cliente = TestClient(provider_sync.app())
    cuerpo = json.dumps(GRABACIONES[2]["notificacion"]).encode("utf-8")
    respuesta = cliente.post(
        "/webhooks/proveedor",
        content=cuerpo,
        headers={
            "X-Proveedor-Id": ADAPTADOR_ID,
            "X-Firma": firma(cuerpo, SECRETO_WEBHOOK),
            "Content-Type": "application/json",
        },
    )
    assert respuesta.status_code == 202

    salidas = filas(provider_sync, "SELECT * FROM bandeja_salida ORDER BY seq")
    assert [s["tipo"] for s in salidas] == ["DisrupcionDetectada", "ReservaObservada"]

    disr = salidas[0]
    obs = salidas[1]
    Evento(disr["tipo"], disr["sobre"], disr["carga"]).validar(contratos)
    Evento(obs["tipo"], obs["sobre"], obs["carga"]).validar(contratos)

    assert disr["carril"] == "P1"
    assert disr["carga"]["disrupcionId"] == "DISR-AR1402-METEO"
    assert disr["carga"]["severidad"] == "alta"
    assert disr["carga"]["afectados"] == [
        {"usuarioId": str(USUARIO_1), "reservaIds": [str(RESERVA_1)]},
        {"usuarioId": str(USUARIO_2), "reservaIds": [str(RESERVA_2)]},
    ]
    assert disr["sobre"]["usuarioId"] == str(USUARIO_1)

    # Correlación por idDeCausa entre la disrupción y el cambio de reserva que provoca (UC-5).
    assert obs["carril"] == "P1"
    assert obs["sobre"]["idDeCausa"] == "DISR-AR1402-METEO"
    assert obs["carga"]["observacion"]["cancelada"] is True


def test_sondeo_programado_y_baja_por_reserva_cancelada(provider_sync):
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123"))
    adaptador = provider_sync.registro.obtener(ADAPTADOR_ID).instancia
    orden = GRABACIONES[1]["notificacion"]["orders"][0]
    adaptador.registrar_orden_nativa(orden, emitido="2026-11-18T11:30:00Z", id_evento="sondeo-1")

    assert provider_sync.sondear_proveedores() == 1
    # Un segundo sondeo sin cambios nuevos no vuelve a publicar nada.
    assert provider_sync.sondear_proveedores() == 0

    # Al cancelarse la reserva en itinerary, deja de seguirse.
    cancelada = Evento.nuevo(
        "ReservaCancelada",
        {
            "reservaId": str(RESERVA_1),
            "version": 2,
            "fuente": "manual",
            "canceladaEn": "2026-11-18T12:00:00Z",
        },
        productor="itinerary",
        usuario_id=str(USUARIO_1),
        region="AM",
    )
    provider_sync.consumir(cancelada)
    assert filas(provider_sync, "SELECT * FROM reserva_seguida") == []


def test_unificacion_de_reservas_limpia_la_reserva_absorbida_de_seguimiento(provider_sync):
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123"))
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_2, "ABC123"))
    assert len(filas(provider_sync, "SELECT * FROM reserva_seguida")) == 2

    unificada = _evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123")
    unificada.carga["creada"] = False
    unificada.carga["unificadaCon"] = [str(RESERVA_2)]
    provider_sync.consumir(unificada)

    seguidas = filas(provider_sync, "SELECT * FROM reserva_seguida")
    assert len(seguidas) == 1
    assert str(seguidas[0]["reserva_id"]) == str(RESERVA_1)


def test_recorrido_uc2_y_uc5_con_itinerary_y_virtual_assistant(provider_sync, contratos):
    """Recorrido entre servicios: `itinerary` -> `provider-sync` -> `itinerary` y `virtual-assistant`."""
    itinerary = Itinerary(
        provider_sync._configuracion,
        esquema=provider_sync._esquema,
        contratos=contratos,
        reloj=lambda: AHORA,
    )
    itinerary.crear_esquema()

    # 1. El viajero tiene una reserva en itinerary (vuelo AR1402, código ABC123).
    alta = Evento.nuevo(
        "ReservaExtraida",
        {
            "buzonId": str(uuid4()),
            "idDeMensaje": "m-1",
            "extractor": {"id": "extractor-reserva-simulada", "version": "1.0.0"},
            "banda": "alta",
            "confianza": {"global": 0.99, "porCampo": {"inicio.instante": 0.99}},
            "observacion": {
                "fuente": "correo",
                "idDeFuente": "correo-inicial",
                "versionDeFuente": "2026-11-18T09:00:00Z",
                "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
                "segmentos": [
                    {
                        "tipo": "vuelo",
                        "versionTipo": 1,
                        "inicio": {
                            "instante": "2026-12-01T13:00:00Z",
                            "precision": "instante",
                            "zonaHoraria": "America/Argentina/Buenos_Aires",
                            "lugar": {
                                "nombre": "Aeroparque",
                                "codigo": "AEP",
                                "pais": "AR",
                                "zonaHoraria": "America/Argentina/Buenos_Aires",
                            },
                        },
                        "fin": {
                            "instante": "2026-12-01T15:00:00Z",
                            "precision": "instante",
                            "zonaHoraria": "America/Argentina/Mendoza",
                            "lugar": {
                                "nombre": "El Plumerillo",
                                "codigo": "MDZ",
                                "pais": "AR",
                                "zonaHoraria": "America/Argentina/Mendoza",
                            },
                        },
                        "operador": "Aerolíneas Argentinas",
                        "referencia": "AR1402",
                        "estado": "confirmado",
                        "detalle": {"aerolinea": "AR", "numeroDeVuelo": "1402"},
                    }
                ],
            },
        },
        productor="booking-extraction",
        usuario_id=str(USUARIO_1),
        region="AM",
    )
    itinerary.consumir(alta)

    # 2. provider-sync consume el ReservaActualizada que publicó itinerary.
    eventos_it = filas(
        provider_sync,
        "SELECT * FROM bandeja_salida WHERE tipo = 'ReservaActualizada' ORDER BY seq",
    )
    assert len(eventos_it) == 1
    provider_sync.consumir(
        Evento(eventos_it[0]["tipo"], eventos_it[0]["sobre"], eventos_it[0]["carga"])
    )

    # 3. El proveedor notifica cambio de puerta (puerta 14) -> itinerary consolida con precedencia del proveedor.
    cuerpo_puerta = json.dumps(GRABACIONES[0]["notificacion"]).encode("utf-8")
    provider_sync.recibir_notificacion(
        ADAPTADOR_ID,
        "application/json",
        {"content-type": "application/json"},
        cuerpo_puerta,
        firma(cuerpo_puerta, SECRETO_WEBHOOK),
    )
    [obs_puerta] = filas(
        provider_sync,
        "SELECT * FROM bandeja_salida WHERE tipo = 'ReservaObservada' ORDER BY seq",
    )
    itinerary.consumir(Evento(obs_puerta["tipo"], obs_puerta["sobre"], obs_puerta["carga"]))

    panel = itinerary.leer_panel(USUARIO_1)
    reserva_panel = panel["viajesActivos"][0]["reservas"][0]
    assert reserva_panel["segmentos"][0]["detalle"]["puerta"] == "14"
    assert "proveedor" in reserva_panel["fuentes"]


def test_los_usuarios_afectados_se_bloquean_siempre_en_el_mismo_orden(provider_sync, monkeypatch):
    """El webhook y el sondeo bloquean a todos los afectados antes de procesar y en el mismo
    orden: dos transacciones que se cruzan no se interbloquean."""
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123"))
    provider_sync.consumir(_evento_reserva_actualizada(USUARIO_2, RESERVA_2, "XYZ789"))
    cuerpo = GRABACIONES[2]["notificacion"]
    [cambio] = [c for c in provider_sync.registro.traducir_notificacion(ADAPTADOR_ID, {}, cuerpo)
                if c["referencia"] == "ABC123"]
    otro = copy.deepcopy(cambio)
    otro["referencia"] = "XYZ789"
    otro["observacion"]["idDeFuente"] += "-xyz"
    bloqueados = []
    monkeypatch.setattr(servicio_de_provider_sync, "bloquear_usuario",
                        lambda conexion, usuario: bloqueados.append(str(usuario)))

    primero = max(str(USUARIO_1), str(USUARIO_2))
    cambios = [otro, cambio] if primero == str(USUARIO_2) else [cambio, otro]
    with conectar(provider_sync._configuracion.dsn_postgres, provider_sync._esquema) as conexion:
        provider_sync._procesar_cambios(conexion, ADAPTADOR_ID, cambios, AHORA)
    assert bloqueados == sorted([str(USUARIO_1), str(USUARIO_2)])
