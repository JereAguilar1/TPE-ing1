"""Suite de conformidad del adaptador ferroviario (QA-15, paso 3 de la guía de extensión; ADR-0006,
ADR-0017). Las mismas exigencias que el adaptador de la aerolínea: manifiesto, salidas válidas
contra el contrato y el descriptor `tren.v1`, grabaciones reproducibles y errores declarados.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.provider_sync.complementos.ferrocarril_simulado import (
    AdaptadorFerrocarrilSimulado,
)
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CargaInvalida,
    CuotaExcedida,
    NoEncontrada,
    ProveedorNoDisponible,
)
from trotamundos.servicios.provider_sync.receptor_de_notificaciones import firma
from trotamundos.servicios.provider_sync.registro_de_adaptadores import (
    RegistroDeAdaptadores,
    entradas_configuradas,
)
from trotamundos.servicios.provider_sync.servicio import ProviderSync

GRABACIONES = json.loads((Path(__file__).parent / "grabaciones/ferrocarril_simulado.json")
                         .read_text(encoding="utf-8"))
ADAPTADOR_ID = "adaptador-ferrocarril-simulado"


def _registro(contratos, instancia=None) -> RegistroDeAdaptadores:
    entradas = copy.deepcopy(entradas_configuradas())
    if instancia is not None:
        next(e for e in entradas if e["manifiesto"]["id"] == ADAPTADOR_ID)["instancia"] = instancia
    return RegistroDeAdaptadores(contratos, entradas=entradas)


def test_el_manifiesto_configurado_cumple_el_contrato(contratos):
    registro = _registro(contratos)
    manifiesto = registro.obtener(ADAPTADOR_ID).manifiesto
    contratos.validar("plugins/adaptador.yaml#/manifiesto", manifiesto)
    assert manifiesto["tiposDeSegmento"] == ["tren"]
    assert registro.adaptadores_para_emisor("ferrocarril:RF") == [ADAPTADOR_ID]
    assert registro.adaptadores_para_emisor("aerolinea:AR") == ["adaptador-aerolinea-simulada"]


def test_las_grabaciones_reproducen_las_observaciones_canonicas(contratos):
    registro = _registro(contratos)
    for caso in GRABACIONES:
        [cambio] = registro.traducir_notificacion(ADAPTADOR_ID, {}, copy.deepcopy(caso["notificacion"]))
        [repetido] = registro.traducir_notificacion(ADAPTADOR_ID, {},
                                                    copy.deepcopy(caso["notificacion"]))
        assert cambio == repetido, caso["nombre"]
        esperado, observacion = caso["esperado"], cambio["observacion"]
        segmento = observacion["segmentos"][0]
        assert cambio["referencia"] == esperado["referencia"]
        assert observacion["fuente"] == "proveedor" and segmento["tipo"] == "tren"
        assert observacion["cancelada"] is esperado["cancelada"]
        assert observacion["versionDeFuente"] == esperado["versionDeFuente"]
        assert observacion["identificadores"] == [{"emisor": esperado["emisor"],
                                                   "codigo": esperado["referencia"]}]
        assert (segmento["inicio"]["instante"], segmento["fin"]["instante"]) == (
            esperado["inicio"], esperado["fin"])
        assert segmento["detalle"].get("anden") == esperado["anden"]
        disrupcion = registro.detectar_disrupcion(ADAPTADOR_ID, cambio)
        assert (disrupcion is not None) is esperado["disrupcion"]


def test_obtener_reserva_y_sondear_cumplen_el_contrato_y_manejan_errores(contratos):
    instancia = AdaptadorFerrocarrilSimulado()
    registro = _registro(contratos, instancia)
    reserva = GRABACIONES[0]["notificacion"]["bookings"][0]
    instancia.registrar_reserva_nativa(reserva, emitido="2026-11-18T12:00:00Z")
    assert registro.obtener_reserva(ADAPTADOR_ID, "RFX123")["segmentos"][0]["tipo"] == "tren"
    assert len(registro.sondear(ADAPTADOR_ID, "2026-11-18T00:00:00Z")) == 1
    with pytest.raises(NoEncontrada):
        registro.obtener_reserva(ADAPTADOR_ID, "NOEXIS1")
    for error in (CuotaExcedida(retry_after=10), ProveedorNoDisponible("503")):
        instancia.simular_fallo(error)
        with pytest.raises(type(error)):
            registro.sondear(ADAPTADOR_ID, "2026-11-18T00:00:00Z")


@pytest.mark.parametrize("carga", [
    {"bookings": []},
    {"eventId": "x", "issuedAt": "2026-11-18T12:00:00Z",
     "bookings": [{"bookingRef": "RFX123", "carrier": "RF", "trips": [
         {"trainNumber": "1", "origin": {"station": "ZZZ", "time": "2026-12-06T08:00:00+01:00"},
          "destination": {"station": "BCN", "time": "2026-12-06T09:00:00+01:00"}}]}]},
    "<xml/>",
])
def test_cargas_nativas_invalidas_lanzan_carga_invalida(contratos, carga):
    with pytest.raises(CargaInvalida):
        _registro(contratos).traducir_notificacion(ADAPTADOR_ID, {}, carga)


def test_un_aviso_del_operador_sobre_un_tren_seguido_publica_reserva_observada(dsn, esquema, contratos):
    """De punta a punta en `provider-sync`: el tren de un viajero se sigue por su emisor
    (`ferrocarril:RF`) y el aviso del operador sale como `ReservaObservada` de tipo `tren`."""
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    servicio = ProviderSync(configuracion, esquema=esquema, contratos=contratos,
                            registro=_registro(contratos), secreto_webhook="secreto-de-prueba",
                            reloj=lambda: datetime(2026, 11, 18, 12, tzinfo=timezone.utc))
    servicio.crear_esquema()
    usuario = str(uuid4())
    observacion = _registro(contratos).traducir_notificacion(
        ADAPTADOR_ID, {}, copy.deepcopy(GRABACIONES[0]["notificacion"]))[0]["observacion"]
    segmento = {**observacion["segmentos"][0], "id": str(uuid4())}
    reserva = {"id": str(uuid4()), "estado": "Confirmada", "version": 1, "fuentes": ["correo"],
               "identificadores": observacion["identificadores"], "segmentos": [segmento]}
    servicio.consumir(Evento.nuevo("ReservaActualizada", {"reserva": reserva, "creada": True,
                                                          "cambios": []},
                                   productor="itinerary", usuario_id=usuario, region="AM"))

    cuerpo = json.dumps(GRABACIONES[1]["notificacion"]).encode()
    servicio.recibir_notificacion(ADAPTADOR_ID, "application/json", {}, cuerpo,
                                  firma(cuerpo, "secreto-de-prueba"))
    with conectar(dsn, esquema) as conexion:
        (fila,) = conexion.execute("SELECT carga FROM bandeja_salida "
                                   "WHERE tipo = 'ReservaObservada'").fetchall()
    tramo = fila["carga"]["observacion"]["segmentos"][0]
    assert fila["carga"]["adaptador"]["id"] == ADAPTADOR_ID
    assert (tramo["tipo"], tramo["detalle"]["anden"]) == ("tren", "9")
