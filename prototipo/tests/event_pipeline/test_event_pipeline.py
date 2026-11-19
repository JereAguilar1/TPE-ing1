"""Pruebas de `event-pipeline` y `analytics_store` (paso 14, ADR-0003, ADR-0016, ADR-0030, QA-09, QA-15)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import dataclasses
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.event_pipeline.aterrizaje import seudonimo_de_usuario
from trotamundos.servicios.event_pipeline.servicio import EventPipeline
from trotamundos.servicios.itinerary.servicio import Itinerary

USUARIO_1 = UUID("00000000-0000-4000-8000-000000000e11")
USUARIO_2 = UUID("00000000-0000-4000-8000-000000000e12")
RESERVA_1 = UUID("00000000-0000-4000-8000-000000000f11")
RESERVA_2 = UUID("00000000-0000-4000-8000-000000000f12")
VIAJE_1 = UUID("00000000-0000-4000-8000-000000000a11")


def _reserva_actualizada(usuario_id: UUID, reserva_id: UUID, *,
                         tipo: str = "vuelo",
                         creada: bool = True,
                         fuente: str = "correo",
                         detalle: dict | None = None) -> Evento:
    lugar_origen = {
        "nombre": "Aeroparque",
        "codigo": "AEP",
        "esquemaDeCodigo": "IATA",
        "pais": "AR",
        "zonaHoraria": "America/Argentina/Buenos_Aires",
    }
    lugar_destino = {
        "nombre": "El Plumerillo",
        "codigo": "MDZ",
        "esquemaDeCodigo": "IATA",
        "pais": "AR",
        "zonaHoraria": "America/Argentina/Mendoza",
    }
    reserva = {
        "id": str(reserva_id),
        "estado": "Confirmada",
        "version": 1,
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
        "fuentes": [fuente],
        "segmentos": [
            {
                "id": str(uuid4()),
                "tipo": tipo,
                "versionTipo": 1,
                "orden": 0,
                "inicio": {
                    "instante": "2026-12-01T13:00:00Z",
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Buenos_Aires",
                    "lugar": lugar_origen,
                },
                "fin": {
                    "instante": "2026-12-01T15:00:00Z",
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Mendoza",
                    "lugar": lugar_destino,
                },
                "operador": "Aerolíneas Argentinas",
                "referencia": "AR1402",
                "estado": "confirmado",
                "detalle": detalle or {"aerolinea": "AR", "numeroDeVuelo": "1402", "clase": "economica"},
            }
        ],
    }
    return Evento.nuevo(
        "ReservaActualizada",
        {
            "reserva": reserva,
            "creada": creada,
            "cambios": [{"campo": "inicio.instante", "fuente": fuente}],
        },
        productor="itinerary",
        usuario_id=str(usuario_id),
        region="AM",
    )


def _viaje_armado(usuario_id: UUID, viaje_id: UUID, reserva_id: UUID) -> Evento:
    return Evento.nuevo(
        "ViajeArmado",
        {
            "viajeId": str(viaje_id),
            "titulo": "Viaje a El Plumerillo",
            "estado": "Planificado",
            "desde": "2026-12-01T13:00:00Z",
            "hasta": "2026-12-05T18:00:00Z",
            "destinoPrincipal": {
                "nombre": "Mendoza",
                "codigo": "MDZ",
                "esquemaDeCodigo": "IATA",
                "pais": "AR",
                "zonaHoraria": "America/Argentina/Mendoza",
            },
            "reservaIds": [str(reserva_id)],
            "version": 1,
        },
        productor="itinerary",
        usuario_id=str(usuario_id),
        region="AM",
    )


def filas(pipeline: EventPipeline, consulta: str) -> list[dict]:
    with conectar(pipeline._configuracion.dsn_postgres, pipeline._esquema) as conexion:
        return conexion.execute(consulta).fetchall()


@pytest.fixture
def pipeline(dsn, esquema, contratos):
    configuracion = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker="",
        intervalo_tareas_s=0,
    )
    servicio = EventPipeline(configuracion, esquema=esquema, contratos=contratos)
    servicio.crear_esquema()
    return servicio


def test_aterrizaje_modelo_dimensional_y_ausencia_de_pii(pipeline):
    ev_reserva = _reserva_actualizada(USUARIO_1, RESERVA_1)
    ev_viaje = _viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1)
    ev_conflicto = Evento.nuevo(
        "ConflictoDeFuentesDetectado",
        {
            "reservaId": str(RESERVA_1),
            "conflicto": {
                "id": str(uuid4()),
                "campo": "segmentos[0].inicio.instante",
                "estado": "Abierto",
                "detectadoEn": "2026-11-18T12:00:00Z",
                "valores": [
                    {"fuente": "manual", "valor": "2026-12-01T13:00:00Z"},
                    {"fuente": "proveedor", "valor": "2026-12-01T15:00:00Z"},
                ],
            },
        },
        productor="itinerary",
        usuario_id=str(USUARIO_1),
        region="AM",
    )
    ev_cancelada = Evento.nuevo(
        "ReservaCancelada",
        {
            "reservaId": str(RESERVA_1),
            "viajeId": str(VIAJE_1),
            "version": 2,
            "fuente": "proveedor",
            "canceladaEn": "2026-11-18T14:00:00Z",
        },
        productor="itinerary",
        usuario_id=str(USUARIO_1),
        region="AM",
    )
    ev_completado = Evento.nuevo(
        "ViajeCompletado",
        {"viajeId": str(VIAJE_1), "completadoEn": "2026-12-06T12:00:00Z"},
        productor="itinerary",
        usuario_id=str(USUARIO_1),
        region="AM",
    )
    ev_archivado = Evento.nuevo(
        "ViajeArchivado",
        {"viajeId": str(VIAJE_1), "archivadoEn": "2026-12-09T12:00:00Z", "motivo": "automatico"},
        productor="itinerary",
        usuario_id=str(USUARIO_1),
        region="AM",
    )

    for ev in (ev_reserva, ev_viaje, ev_conflicto, ev_cancelada, ev_completado, ev_archivado):
        pipeline.consumir(ev)
        # Entrega repetida: la bandeja de entrada evita duplicar el efecto (ADR-0014).
        pipeline.consumir(ev)

    tendencias = pipeline.consultar_tendencias()
    assert len(tendencias) == 1
    assert tendencias[0]["tipo"] == "vuelo"
    assert tendencias[0]["total"] == 2  # creada + cancelada

    destinos = pipeline.consultar_destinos()
    assert destinos == [{"pais": "AR", "ciudad": "Mendoza", "viajes": 1}]

    cancelaciones = pipeline.consultar_cancelaciones()
    assert len(cancelaciones) == 1
    assert cancelaciones[0]["nombre"] == "Aerolíneas Argentinas"
    assert cancelaciones[0]["total"] == 1

    hechos_viaje = filas(pipeline, "SELECT * FROM v_hecho_viaje")
    assert len(hechos_viaje) == 1
    assert hechos_viaje[0]["reservas"] == 1
    assert hechos_viaje[0]["duracion_dias"] == 4
    assert hechos_viaje[0]["conflictos"] == 1
    assert hechos_viaje[0]["cancelaciones"] == 1
    assert hechos_viaje[0]["fecha_completado_id"] == 20261206
    assert hechos_viaje[0]["fecha_archivado_id"] == 20261209

    # Revisión de privacidad (ADR-0016, ADR-0030): ninguna tabla analítica guarda el usuario_id
    # operacional; solo el seudónimo analítico.
    for tabla in ("evento_crudo", "dim_usuario", "hecho_cambio_reserva", "hecho_viaje"):
        volcado = json.dumps(filas(pipeline, f"SELECT * FROM {tabla}"), default=str)
        assert str(USUARIO_1) not in volcado
    usuarios = filas(pipeline, "SELECT * FROM dim_usuario")
    assert len(usuarios) == 1
    assert usuarios[0]["seudonimo_analitico"] == seudonimo_de_usuario(str(USUARIO_1))


def test_reconstruccion_desde_eventos_crudos_produce_el_mismo_resultado(pipeline):
    """Confirmación de ADR-0016: regenerar los hechos desde `evento_crudo` produce el mismo
    resultado."""
    pipeline.consumir(_reserva_actualizada(USUARIO_1, RESERVA_1))
    pipeline.consumir(_viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1))

    cambios_antes = filas(pipeline, "SELECT * FROM hecho_cambio_reserva ORDER BY id_de_evento")
    viajes_antes = filas(pipeline, "SELECT * FROM hecho_viaje ORDER BY viaje_clave")

    procesados = pipeline.reconstruir()
    assert procesados == 2

    cambios_despues = filas(pipeline, "SELECT * FROM hecho_cambio_reserva ORDER BY id_de_evento")
    viajes_despues = filas(pipeline, "SELECT * FROM hecho_viaje ORDER BY viaje_clave")
    assert cambios_despues == cambios_antes
    assert viajes_despues == viajes_antes


def test_cuenta_suprimida_excluye_al_usuario_de_las_vistas_analiticas(pipeline):
    """ADR-0030 (fase 2): `CuentaSuprimida` inserta el seudónimo en `lista_supresion_analitica` y
    las vistas `v_hecho_cambio_reserva` y `v_hecho_viaje` lo excluyen desde el primer minuto."""
    pipeline.consumir(_reserva_actualizada(USUARIO_1, RESERVA_1))
    pipeline.consumir(_viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1))
    pipeline.consumir(_reserva_actualizada(USUARIO_2, RESERVA_2))

    assert pipeline.consultar_tendencias()[0]["total"] == 2
    assert len(pipeline.consultar_destinos()) == 1

    seudonimo_1 = seudonimo_de_usuario(str(USUARIO_1))
    baja = Evento.nuevo(
        "CuentaSuprimida",
        {"seudonimoAnalitico": seudonimo_1, "suprimidaEn": "2026-11-18T18:00:00Z"},
        productor="identity-access",
        usuario_id=None,
    )
    pipeline.consumir(baja)

    # El usuario 1 desaparece de las vistas de consulta; el usuario 2 sigue intacto.
    assert pipeline.consultar_tendencias()[0]["total"] == 1
    assert pipeline.consultar_destinos() == []


def test_qa15_descriptor_nuevo_agrega_fila_en_dim_tipo_segmento_sin_tocar_esquema(pipeline, contratos):
    """Confirmación de ADR-0016 y QA-15: un nuevo medio de transporte es una fila nueva en
    `dim_tipo_segmento`, sin modificar ninguna columna SQL."""
    descriptor_barco = {
        "tipo": "barco",
        "version": 1,
        "rolEnViaje": "traslado",
        "esquemaDeDetalle": {
            "type": "object",
            "required": ["naviera", "camarote"],
            "additionalProperties": False,
            "properties": {
                "naviera": {"type": "string"},
                "camarote": {"type": "string"},
            },
        },
        "camposRelevantes": [
            {"campo": "inicio.instante", "severidad": "critica", "umbralMinutos": 30}
        ],
        "presentacion": {
            "icono": "barco",
            "titulo": "{operador}",
            "filas": ["naviera", "camarote"],
        },
        "dimension": {"atributos": ["operador", "naviera"]},
    }
    descriptores_ampliados = [
        *contratos.descriptores(),
        ("tipos-de-segmento/barco.v1.yaml", descriptor_barco),
    ]
    registro_ampliado = RegistroDeTipos(contratos, descriptores_ampliados)

    nuevos = pipeline.sincronizar_tipos(registro_ampliado)
    assert nuevos == 1

    fila_barco = filas(
        pipeline, "SELECT * FROM dim_tipo_segmento WHERE tipo = 'barco' AND version_tipo = 1"
    )
    assert len(fila_barco) == 1
    assert fila_barco[0]["rol_en_viaje"] == "traslado"


def test_qa09_aislamiento_entre_consultas_analiticas_y_lectura_del_panel(dsn, contratos):
    """Confirmación de ADR-0003 y QA-09: el plano analítico vive en su propio esquema separado
    del plano operacional, y ejecutar consultas analíticas pesadas concurrentemente con lecturas
    de `GET /panel` produce 0 fallos operacionales."""
    esquema_op = f"prueba_op_{uuid4().hex[:8]}"
    esquema_an = f"prueba_an_{uuid4().hex[:8]}"
    configuracion = dataclasses.replace(
        Configuracion.desde_entorno(),
        dsn_postgres=dsn,
        broker="",
        intervalo_tareas_s=0,
    )
    try:
        itinerary = Itinerary(
            configuracion,
            esquema=esquema_op,
            contratos=contratos,
            reloj=lambda: datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc),
        )
        itinerary.crear_esquema()

        pipeline = EventPipeline(configuracion, esquema=esquema_an, contratos=contratos)
        pipeline.crear_esquema()

        # Cargamos datos en ambos planos (cada uno en su esquema independiente).
        for i in range(15):
            pipeline.consumir(_reserva_actualizada(USUARIO_1, uuid4()))
        pipeline.consumir(_viaje_armado(USUARIO_1, VIAJE_1, RESERVA_1))

        # Verificamos que el esquema operacional no contiene tablas analíticas y viceversa.
        with conectar(dsn, esquema_op) as con_op:
            assert con_op.execute("SELECT to_regclass('hecho_cambio_reserva') AS t").fetchone()["t"] is None
        with conectar(dsn, esquema_an) as con_an:
            assert con_an.execute("SELECT to_regclass('panel_usuario') AS t").fetchone()["t"] is None

        # Ejecutamos lecturas operacionales del panel en paralelo con consultas y reconstrucciones analíticas.
        def tarea_operacional() -> int:
            leidos = 0
            for _ in range(20):
                panel = itinerary.leer_panel(USUARIO_1)
                assert "viajesActivos" in panel
                leidos += 1
            return leidos

        def tarea_analitica() -> None:
            for _ in range(10):
                assert pipeline.consultar_tendencias()[0]["total"] == 15
                assert len(pipeline.consultar_destinos()) == 1
            pipeline.reconstruir()

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_op1 = pool.submit(tarea_operacional)
            f_op2 = pool.submit(tarea_operacional)
            f_an = pool.submit(tarea_analitica)
            assert f_op1.result() == 20
            assert f_op2.result() == 20
            f_an.result()
    finally:
        with psycopg.connect(dsn, autocommit=True) as conexion:
            for nombre in (esquema_op, esquema_an):
                conexion.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(nombre))
                )
