"""Suite de conformidad de `AdaptadorDeProveedor` (ADR-0017, ADR-0006, ADR-0027, QA-10).

Verifica las cuatro exigencias de `contratos/plugins/adaptador.yaml#/conformidad`:
1. El manifiesto valida contra `manifiesto` y SemVer.
2. Cada salida valida contra su esquema y contra el descriptor del tipo de segmento, con
   `fuente: proveedor` y sin tipos externos (regla R3).
3. Las grabaciones de respuestas del proveedor se reproducen y producen las mismas observaciones.
4. Registrar un adaptador nuevo no modifica ningún archivo de otro adaptador ni de un servicio de
   dominio (QA-10).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.tipos_de_segmento import TipoNoRegistrado
from trotamundos.servicios.provider_sync.complementos.aerolinea_simulada import (
    AdaptadorAerolineaSimulada,
)
from trotamundos.servicios.provider_sync.interfaz_de_adaptador import (
    CargaInvalida,
    CuotaExcedida,
    NoEncontrada,
    ProveedorNoDisponible,
)
from trotamundos.servicios.provider_sync.registro_de_adaptadores import (
    RegistroDeAdaptadores,
    entradas_configuradas,
)

GRABACIONES = json.loads(
    (Path(__file__).parent / "grabaciones/aerolinea_simulada.json").read_text(encoding="utf-8")
)
ADAPTADOR_ID = "adaptador-aerolinea-simulada"


def test_el_manifiesto_configurado_cumple_el_contrato(contratos):
    registro = RegistroDeAdaptadores(contratos)
    assert ADAPTADOR_ID in registro.ids()
    adaptador = registro.obtener(ADAPTADOR_ID)
    contratos.validar("plugins/adaptador.yaml#/manifiesto", adaptador.manifiesto)
    assert adaptador.manifiesto["apiContrato"] == "1.0"
    assert registro.adaptadores_para_emisor("aerolinea:AR") == [ADAPTADOR_ID]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("apiContrato", "2.0"),
        ("version", "no-es-semver"),
        ("id", "sin-prefijo"),
        ("tiposDeSegmento", ["teletransporte"]),
    ],
)
def test_el_registro_rechaza_manifiesto_incompatible(contratos, campo, valor):
    entradas = copy.deepcopy(entradas_configuradas())
    entradas[0]["manifiesto"][campo] = valor
    with pytest.raises((ValueError, KeyError, ErrorDeContrato, TipoNoRegistrado)):
        RegistroDeAdaptadores(contratos, entradas=entradas)


def test_las_grabaciones_del_proveedor_reproducen_las_observaciones_canonicas(contratos):
    registro = RegistroDeAdaptadores(contratos)
    for caso in GRABACIONES:
        [cambio] = registro.traducir_notificacion(
            ADAPTADOR_ID,
            {"content-type": caso["tipoContenido"]},
            copy.deepcopy(caso["notificacion"]),
        )
        # Reproducibilidad determinista: una segunda traducción produce la misma observación.
        [repetido] = registro.traducir_notificacion(
            ADAPTADOR_ID,
            {"content-type": caso["tipoContenido"]},
            copy.deepcopy(caso["notificacion"]),
        )
        assert cambio == repetido

        esperado = caso["esperado"]
        obs = cambio["observacion"]
        seg = obs["segmentos"][0]
        assert cambio["referencia"] == esperado["referencia"]
        assert obs["fuente"] == "proveedor"
        assert obs["cancelada"] is esperado["cancelada"]
        assert obs["versionDeFuente"] == esperado["versionDeFuente"]
        assert obs["identificadores"] == [
            {"emisor": esperado["emisor"], "codigo": esperado["referencia"]}
        ]
        assert seg["inicio"]["instante"] == esperado["inicio"]
        assert seg["fin"]["instante"] == esperado["fin"]
        assert seg["detalle"].get("puerta") == esperado["puerta"]

        disrupcion = registro.detectar_disrupcion(ADAPTADOR_ID, cambio)
        if esperado["disrupcion"] is None:
            assert disrupcion is None
        else:
            assert disrupcion is not None
            assert disrupcion["id"] == esperado["disrupcion"]["id"]
            assert disrupcion["severidad"] == esperado["disrupcion"]["severidad"]
            assert disrupcion["referenciasAfectadas"] == esperado["disrupcion"]["referenciasAfectadas"]


def test_obtener_reserva_y_sondear_cumplen_el_contrato_y_manejan_errores(contratos):
    instancia = AdaptadorAerolineaSimulada()
    entradas = copy.deepcopy(entradas_configuradas())
    entradas[0]["instancia"] = instancia
    registro = RegistroDeAdaptadores(contratos, entradas=entradas)

    with pytest.raises(NoEncontrada):
        registro.obtener_reserva(ADAPTADOR_ID, "NOEXISTE")

    orden = GRABACIONES[0]["notificacion"]["orders"][0]
    instancia.registrar_orden_nativa(orden, emitido="2026-11-18T12:00:00Z", id_evento="alta")

    obs = registro.obtener_reserva(ADAPTADOR_ID, "ABC123")
    assert obs["fuente"] == "proveedor"
    assert obs["identificadores"][0]["codigo"] == "ABC123"

    cambios = registro.sondear(ADAPTADOR_ID, "2026-11-18T11:00:00Z")
    assert len(cambios) == 1
    assert cambios[0]["referencia"] == "ABC123"
    assert registro.sondear(ADAPTADOR_ID, "2026-11-18T13:00:00Z") == []

    instancia.simular_fallo(CuotaExcedida("429 Too Many Requests", retry_after=30))
    with pytest.raises(CuotaExcedida) as exc_cuota:
        registro.sondear(ADAPTADOR_ID, "2026-11-18T00:00:00Z")
    assert exc_cuota.value.retry_after == 30

    instancia.simular_fallo(ProveedorNoDisponible("503 Service Unavailable"))
    with pytest.raises(ProveedorNoDisponible):
        registro.obtener_reserva(ADAPTADOR_ID, "ABC123")


@pytest.mark.parametrize(
    "carga_invalida",
    [
        {},
        {"notificationId": "n1", "timestamp": "2026-11-18T10:00:00Z", "orders": []},
        "<xml-invalido/>",
        {
            "notificationId": "n1",
            "timestamp": "fecha-invalida",
            "orders": GRABACIONES[0]["notificacion"]["orders"],
        },
    ],
)
def test_cargas_nativas_invalidas_lanzan_carga_invalida(contratos, carga_invalida):
    registro = RegistroDeAdaptadores(contratos)
    with pytest.raises(CargaInvalida):
        registro.traducir_notificacion(ADAPTADOR_ID, {}, carga_invalida)


def test_qa10_registrar_un_adaptador_nuevo_no_toca_otros_elementos(contratos):
    """QA-10: un adaptador ficticio de hotelera HTNG se registra por configuración y pasa la
    misma validación contractual sin tocar ningún archivo existente."""

    class AdaptadorHoteleraHtngFicticio:
        def obtener_reserva(self, credencial: Mapping[str, str],
                            referencia: str) -> dict[str, Any]:
            return self._observacion(referencia)

        def traducir_notificacion(self, cabeceras: Mapping[str, str],
                                  cuerpo: Any) -> list[dict[str, Any]]:
            ref = str(cuerpo["reservationCode"])
            return [{"referencia": ref, "observacion": self._observacion(ref)}]

        def sondear(self, credencial: Mapping[str, str],
                    desde: str) -> list[dict[str, Any]]:
            return [{"referencia": "HTL900", "observacion": self._observacion("HTL900")}]

        def detectar_disrupcion(self, cambio: Mapping[str, Any]) -> dict[str, Any] | None:
            return None

        @staticmethod
        def _observacion(referencia: str) -> dict[str, Any]:
            lugar = {
                "nombre": "Hotel Andino Mendoza",
                "pais": "AR",
                "zonaHoraria": "America/Argentina/Mendoza",
            }
            return {
                "fuente": "proveedor",
                "idDeFuente": f"htng:{referencia}:v1",
                "versionDeFuente": "2026-11-18T10:00:00Z",
                "cancelada": False,
                "identificadores": [{"emisor": "hotel:HTNG", "codigo": referencia}],
                "segmentos": [
                    {
                        "tipo": "hotel",
                        "versionTipo": 1,
                        "orden": 0,
                        "inicio": {
                            "instante": "2026-12-01T18:00:00Z",
                            "precision": "instante",
                            "zonaHoraria": "America/Argentina/Mendoza",
                            "lugar": lugar,
                        },
                        "fin": {
                            "instante": "2026-12-05T14:00:00Z",
                            "precision": "instante",
                            "zonaHoraria": "America/Argentina/Mendoza",
                            "lugar": lugar,
                        },
                        "operador": "Cadena Andina",
                        "referencia": referencia,
                        "estado": "confirmado",
                        "detalle": {
                            "tipoDeHabitacion": "Suite Cordillera",
                            "habitaciones": 1,
                            "huespedes": 2,
                            "regimen": "desayuno",
                        },
                    }
                ],
            }

    entradas = [
        *entradas_configuradas(),
        {
            "instancia": AdaptadorHoteleraHtngFicticio(),
            "emisores": ["hotel:HTNG"],
            "credencial": {"tipo": "apiKey", "valor": "clave-htng"},
            "manifiesto": {
                "id": "adaptador-hotelera-htng-demo",
                "version": "1.0.0",
                "apiContrato": "1.0",
                "estandar": "HTNG",
                "tiposDeSegmento": ["hotel"],
                "capacidades": {
                    "push": True,
                    "sondeo": True,
                    "cancelaciones": True,
                    "cuotaPorMinuto": 120,
                },
            },
        },
    ]
    registro = RegistroDeAdaptadores(contratos, entradas=entradas)

    assert "adaptador-hotelera-htng-demo" in registro.ids()
    obs = registro.obtener_reserva("adaptador-hotelera-htng-demo", "HTL900")
    assert obs["segmentos"][0]["tipo"] == "hotel"
    [cambio] = registro.traducir_notificacion(
        "adaptador-hotelera-htng-demo", {}, {"reservationCode": "HTL900"}
    )
    assert cambio["referencia"] == "HTL900"
    assert registro.sondear("adaptador-hotelera-htng-demo", "2026-11-18T00:00:00Z") == [cambio]
    assert registro.detectar_disrupcion("adaptador-hotelera-htng-demo", cambio) is None
