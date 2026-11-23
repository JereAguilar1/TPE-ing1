"""Cortacircuitos, mamparo, cuota y `cola_pendientes` de `provider-sync` (ADR-0024, QA-06).

Las primeras pruebas usan un reloj simulado y no necesitan nada levantado. La última es la prueba
de inyección de falla de ADR-0024 contra PostgreSQL: el proveedor cae, el trabajo queda retenido
con su espera y, al volver, converge.
"""

from __future__ import annotations

import copy
import dataclasses
import threading
from datetime import datetime, timedelta, timezone

import pytest

from tests.provider_sync.test_conformidad_adaptadores import ADAPTADOR_ID, GRABACIONES
from tests.provider_sync.test_provider_sync import (
    RESERVA_1,
    USUARIO_1,
    _evento_reserva_actualizada,
    filas,
)
from trotamundos.comun.config import Configuracion
from trotamundos.comun.persistencia import transaccion
from trotamundos.servicios.provider_sync import proteccion
from trotamundos.servicios.provider_sync.complementos.aerolinea_simulada import (
    AdaptadorAerolineaSimulada,
)
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CuotaExcedida,
    NoEncontrada,
    ProveedorNoDisponible,
)
from trotamundos.servicios.provider_sync.registro_de_adaptadores import (
    RegistroDeAdaptadores,
    entradas_configuradas,
)
from trotamundos.servicios.provider_sync.servicio import ProviderSync

T0 = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
PROVEEDOR = "adaptador-prueba"


def _protector(cuota: int = 600) -> proteccion.ProtectorDeProveedores:
    return proteccion.ProtectorDeProveedores({PROVEEDOR: cuota})


def _falla():
    raise ProveedorNoDisponible("503")


def _intentar(protector, ahora, llamada=_falla, prioridad="vivo", **opciones):
    try:
        return protector.llamar(PROVEEDOR, prioridad, llamada, ahora, **opciones)
    except proteccion.Reintentable as error:
        return error


# --- cortacircuitos -----------------------------------------------------------------------------

def test_cinco_fallas_seguidas_abren_el_cortacircuitos_en_menos_de_25_s():
    protector = _protector()
    for segundo in range(0, 25, 5):  # una llamada cada 5 s: la quinta, a los 20 s
        assert isinstance(_intentar(protector, T0 + timedelta(seconds=segundo)),
                          proteccion.FallaTransitoria)
    assert protector.estado(PROVEEDOR) == proteccion.ABIERTO
    llamadas = []
    resultado = _intentar(protector, T0 + timedelta(seconds=21), lambda: llamadas.append(1))
    assert isinstance(resultado, proteccion.CortacircuitosAbierto) and llamadas == []


def test_la_mitad_de_fallas_en_la_ventana_tambien_lo_abre():
    protector = _protector()
    for i in range(10):  # 10 llamadas en 10 s, alternando: 50 % de fallas, nunca 5 seguidas
        llamada = _falla if i % 2 else (lambda: "ok")
        _intentar(protector, T0 + timedelta(seconds=i), llamada)
    assert protector.estado(PROVEEDOR) == proteccion.ABIERTO


def test_semiabierto_tras_30_s_y_tres_sondas_lo_cierran():
    protector = _protector()
    for i in range(5):
        _intentar(protector, T0 + timedelta(seconds=i))
    abierto = T0 + timedelta(seconds=4)
    assert isinstance(_intentar(protector, abierto + timedelta(seconds=29), lambda: "ok"),
                      proteccion.CortacircuitosAbierto)
    for i in range(3):
        assert _intentar(protector, abierto + timedelta(seconds=30 + i), lambda: "ok") == "ok"
    assert protector.estado(PROVEEDOR) == proteccion.CERRADO


def test_una_falla_en_semiabierto_lo_vuelve_a_abrir():
    protector = _protector()
    for i in range(5):
        _intentar(protector, T0 + timedelta(seconds=i))
    _intentar(protector, T0 + timedelta(seconds=40))  # la sonda falla
    assert protector.estado(PROVEEDOR) == proteccion.ABIERTO


def test_un_error_no_reintentable_pasa_y_no_cuenta_como_falla_de_salud():
    protector = _protector()
    for i in range(6):
        with pytest.raises(NoEncontrada):
            protector.llamar(PROVEEDOR, "vivo", lambda: (_ for _ in ()).throw(NoEncontrada("x")),
                             T0 + timedelta(seconds=i))
    assert protector.estado(PROVEEDOR) == proteccion.CERRADO


# --- cuota y freno ------------------------------------------------------------------------------

def test_un_429_frena_hasta_retry_after_sin_abrir_el_cortacircuitos():
    protector = _protector()
    def limitado():
        raise CuotaExcedida(retry_after=10)
    assert isinstance(_intentar(protector, T0, limitado), proteccion.SinCuota)
    assert isinstance(_intentar(protector, T0 + timedelta(seconds=9), lambda: "ok"),
                      proteccion.SinCuota)
    assert _intentar(protector, T0 + timedelta(seconds=10), lambda: "ok") == "ok"
    assert protector.estado(PROVEEDOR) == proteccion.CERRADO


def test_la_cuota_es_el_80_por_ciento_repartido_por_prioridad():
    protector = _protector(cuota=100)  # 80 por minuto: 48 vivo, 20 futuro, 12 reconciliación
    hechas = [_intentar(protector, T0, lambda: "ok", "reconciliacion") for _ in range(13)]
    assert hechas.count("ok") == 12 and isinstance(hechas[-1], proteccion.SinCuota)
    assert _intentar(protector, T0, lambda: "ok", "vivo") == "ok"  # otra prioridad, otro cupo
    assert _intentar(protector, T0 + timedelta(minutes=1), lambda: "ok", "reconciliacion") == "ok"


def test_el_drenaje_de_atrasos_usa_como_mucho_la_mitad_de_la_cuota():
    protector = _protector(cuota=100)  # 80 por minuto: el drenaje, hasta 40
    hechas = [_intentar(protector, T0, lambda: "ok", "vivo", drenando=True) for _ in range(45)]
    assert hechas.count("ok") == 40
    assert _intentar(protector, T0, lambda: "ok", "vivo") == "ok"  # el tráfico nuevo sigue pasando


def _lentas(protector, cantidad, instante):
    """`cantidad` llamadas que quedan adentro hasta que se suelta `liberar`."""
    liberar, adentro = threading.Event(), threading.Semaphore(0)

    def lenta():
        adentro.release()
        liberar.wait(5)
        return "ok"

    hilos = [threading.Thread(target=_intentar, args=(protector, instante, lenta))
             for _ in range(cantidad)]
    for hilo in hilos:
        hilo.start()
    for _ in range(cantidad):
        assert adentro.acquire(timeout=5)
    return liberar, hilos


def test_semiabierto_deja_pasar_solo_las_tres_sondas():
    """ADR-0024: en semiabierto salen 3 sondas, no todo el tráfico que espera al proveedor."""
    protector = _protector(cuota=10_000)
    for i in range(5):
        _intentar(protector, T0 + timedelta(seconds=i))
    semiabierto = T0 + timedelta(seconds=40)
    liberar, hilos = _lentas(protector, 3, semiabierto)
    try:
        assert isinstance(_intentar(protector, semiabierto, lambda: "ok"),
                          proteccion.CortacircuitosAbierto)
    finally:
        liberar.set()
        for hilo in hilos:
            hilo.join(5)
    assert protector.estado(PROVEEDOR) == proteccion.CERRADO


def test_con_el_mamparo_lleno_no_se_gasta_cuota():
    protector = _protector(cuota=10_000)
    liberar, hilos = _lentas(protector, proteccion.MAMPARO, T0)
    try:
        usadas = sum(protector._cuotas[PROVEEDOR].usadas.values())
        for _ in range(5):
            assert isinstance(_intentar(protector, T0, lambda: "ok"), proteccion.MamparoLleno)
        assert sum(protector._cuotas[PROVEEDOR].usadas.values()) == usadas
    finally:
        liberar.set()
        for hilo in hilos:
            hilo.join(5)


def test_el_mamparo_admite_50_llamadas_simultaneas():
    protector = _protector(cuota=10_000)
    liberar, adentro = threading.Event(), threading.Semaphore(0)

    def lenta():
        adentro.release()
        liberar.wait(5)
        return "ok"

    hilos = [threading.Thread(target=_intentar, args=(protector, T0, lenta)) for _ in range(50)]
    for hilo in hilos:
        hilo.start()
    for _ in range(50):
        assert adentro.acquire(timeout=5)
    try:
        assert isinstance(_intentar(protector, T0, lambda: "ok"), proteccion.MamparoLleno)
    finally:
        liberar.set()
        for hilo in hilos:
            hilo.join(5)
    assert _intentar(protector, T0, lambda: "ok") == "ok"


@pytest.mark.parametrize("intentos, segundos", [(1, 5), (2, 10), (3, 20), (8, 640), (9, 900),
                                                (20, 900)])
def test_espera_exponencial_con_tope_y_variacion(intentos, segundos):
    assert proteccion.espera(intentos, lambda: 0.5) == timedelta(seconds=segundos)
    assert proteccion.espera(intentos, lambda: 0.0) == timedelta(seconds=segundos * 0.7)
    assert proteccion.espera(intentos, lambda: 1.0) == timedelta(seconds=segundos * 1.3)


# --- inyección de falla (ADR-0024, confirmación) ------------------------------------------------

def test_qa06_proveedor_caido_retiene_el_trabajo_y_converge_al_volver(dsn, esquema, contratos):
    reloj = {"ahora": T0}
    instancia = AdaptadorAerolineaSimulada()
    entradas = copy.deepcopy(entradas_configuradas())
    entradas[0]["instancia"] = instancia
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    servicio = ProviderSync(configuracion, esquema=esquema, contratos=contratos,
                            registro=RegistroDeAdaptadores(contratos, entradas=entradas),
                            secreto_webhook="secreto", reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.consumir(_evento_reserva_actualizada(USUARIO_1, RESERVA_1, "ABC123"))
    instancia.registrar_orden_nativa(GRABACIONES[1]["notificacion"]["orders"][0],
                                     emitido="2026-11-18T11:30:00Z", id_evento="cambio")

    llamadas = []
    original = instancia.sondear
    instancia.sondear = lambda *a, **k: llamadas.append(reloj["ahora"]) or original(*a, **k)
    instancia.simular_fallo(ProveedorNoDisponible("503"))

    assert servicio.sondear_proveedores() == 0  # el proveedor cae: no se publica nada…
    (pendiente,) = filas(servicio, f"SELECT * FROM cola_pendientes WHERE adaptador_id = '{ADAPTADOR_ID}'")  # …pero queda retenido
    assert pendiente["adaptador_id"] == ADAPTADOR_ID and pendiente["intentos"] == 1
    assert timedelta(seconds=3.5) <= pendiente["proximo_intento"] - T0 <= timedelta(seconds=6.5)

    reloj["ahora"] = T0 + timedelta(seconds=2)  # antes de la espera, no se le insiste
    servicio.sondear_proveedores()
    assert len(llamadas) == 1

    reloj["ahora"] = T0 + timedelta(seconds=7)  # vence la espera: reintenta y vuelve a fallar
    servicio.sondear_proveedores()
    (pendiente,) = filas(servicio, f"SELECT * FROM cola_pendientes WHERE adaptador_id = '{ADAPTADOR_ID}'")
    assert len(llamadas) == 2 and pendiente["intentos"] == 2

    instancia.simular_fallo(None)  # el proveedor vuelve
    reloj["ahora"] = T0 + timedelta(seconds=30)
    assert servicio.sondear_proveedores() == 1  # converge: el cambio sale como ReservaObservada
    assert filas(servicio, f"SELECT * FROM cola_pendientes WHERE adaptador_id = '{ADAPTADOR_ID}'") == []
    assert len(filas(servicio, "SELECT 1 FROM bandeja_salida WHERE tipo = 'ReservaObservada'")) == 1


def test_lo_pendiente_por_mas_de_24_h_se_descarta(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    reloj = {"ahora": T0}
    servicio = ProviderSync(configuracion, esquema=esquema, contratos=contratos,
                            secreto_webhook="secreto", reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    with transaccion(dsn, esquema) as conexion:
        proteccion.postergar(conexion, ADAPTADOR_ID, "sondear", "x", ProveedorNoDisponible("503"),
                             T0)
    reloj["ahora"] = T0 + timedelta(hours=25)
    servicio.registro.obtener(ADAPTADOR_ID).instancia.simular_fallo(ProveedorNoDisponible("503"))
    servicio.tareas_periodicas()
    pendientes = filas(servicio, "SELECT argumento FROM cola_pendientes")
    assert {"argumento": "x"} not in pendientes
