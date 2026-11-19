"""Escenario QA-01 (ASR-1): una actualización de viaje llega al panel en ≤ 5 min (p95) y ≤ 8 min (p99).

Corre contra los contenedores (`tests/escenarios/contenedores.py`), por los dos caminos de la
cadena de ingesta y propagación:

* **correo:** el viajero reenvía la confirmación a su alias → `mail-ingest` (ADR-0035) →
  `MensajeDeViajeRecibido` → `booking-extraction` (ADR-0015) → `ReservaExtraida` → `itinerary`
  (fusión, ADR-0013) → panel en `bff-web`;
* **proveedor:** la aerolínea avisa un cambio de horario por *push* → `provider-sync` (ADR-0006) →
  `ReservaObservada` (carril por cercanía, ADR-0020) → `itinerary` → panel en `bff-web`.

Además del total, mide cada tramo con las marcas de tiempo de las *outbox* y bandejas de entrada
(ADR-0014) y lo compara con el presupuesto de frescura del análisis inicial (`07-supuestos-y-carga-
derivada.md`): 60 s para recibir y despachar (15 s de encolado más 45 s de descarga), 45 s para
extraer, normalizar y deduplicar, y 75 s para persistir y llegar al cliente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from tests.escenarios.contenedores import (
    Viajero,
    ahora,
    esperar,
    esperar_seguimiento,
    exigir_contenedores,
    fila,
    inicio_en_el_panel,
    notificar_cambio,
    percentil,
    texto_utc,
)

TOTAL_P95_S, TOTAL_P99_S = 300, 480  # QA-01
PRESUPUESTO = {"recepcion y despacho": 60, "extraccion, normalizacion y deduplicacion": 45,
               "persistencia y cliente": 75}
CORREOS, CAMBIOS = 3, 10


@pytest.fixture(scope="module")
def cliente():
    exigir_contenedores()
    with httpx.Client(timeout=15) as cliente:
        yield cliente


def _tramos(t0: datetime, despachado: datetime, en_itinerary: datetime,
            visible: datetime) -> dict[str, float]:
    return {"recepcion y despacho": (despachado - t0).total_seconds(),
            "extraccion, normalizacion y deduplicacion": (en_itinerary - despachado).total_seconds(),
            "persistencia y cliente": (visible - en_itinerary).total_seconds(),
            "total": (visible - t0).total_seconds()}


def _llegada_a_itinerary(evento_id) -> datetime:
    return esperar(lambda: (f := fila("itinerary", "SELECT recibido_en FROM bandeja_entrada "
                                                   "WHERE evento_id = %s", evento_id))
                   and f["recibido_en"], 60, "itinerary registra el evento")


def _en_el_panel_o_rechazada(viajero: Viajero, localizador: str, salida: datetime,
                             desde: datetime) -> bool:
    """Falla enseguida si `booking-extraction` no reconoció el correo, en lugar de esperar 8 min."""
    rechazo = fila("booking_extraction", """SELECT carga->>'motivo' AS motivo FROM bandeja_salida
                   WHERE usuario_id = %s AND tipo = 'ExtraccionNoReconocida' AND creado_en >= %s""",
                   viajero.usuario_id, desde)
    assert rechazo is None, f"booking-extraction no reconoció {localizador}: {rechazo['motivo']}"
    return inicio_en_el_panel(viajero, localizador) == texto_utc(salida)


def _por_correo(viajero: Viajero, localizador: str, salida: datetime) -> dict[str, float]:
    t0 = ahora()
    respuesta = viajero.reenviar_confirmacion(localizador, salida)
    assert respuesta.status_code == 202, respuesta.text
    esperar(lambda: _en_el_panel_o_rechazada(viajero, localizador, salida, t0), TOTAL_P99_S,
            f"{localizador} en el panel")
    visible = ahora()
    mensaje = fila("mail_ingest", """SELECT publicado_en FROM bandeja_salida
                   WHERE usuario_id = %s AND tipo = 'MensajeDeViajeRecibido' AND creado_en >= %s
                   ORDER BY creado_en LIMIT 1""", viajero.usuario_id, t0)
    extraida = fila("booking_extraction", """SELECT evento_id FROM bandeja_salida
                    WHERE usuario_id = %s AND tipo = 'ReservaExtraida'
                    AND carga->'observacion'->'identificadores' @> %s::jsonb""",
                    viajero.usuario_id, f'[{{"codigo": "{localizador}"}}]')
    return _tramos(t0, mensaje["publicado_en"], _llegada_a_itinerary(extraida["evento_id"]), visible)


def _por_proveedor(cliente: httpx.Client, viajero: Viajero, localizador: str,
                   salida: datetime) -> dict[str, float]:
    t0 = ahora()
    respuesta = notificar_cambio(cliente, localizador, salida)
    assert respuesta.status_code == 202, respuesta.text
    esperar(lambda: inicio_en_el_panel(viajero, localizador) == texto_utc(salida), TOTAL_P99_S,
            f"el cambio de {localizador} en el panel")
    visible = ahora()
    observada = fila("provider_sync", """SELECT evento_id, publicado_en FROM bandeja_salida
                     WHERE usuario_id = %s AND tipo = 'ReservaObservada' AND creado_en >= %s
                     ORDER BY creado_en DESC LIMIT 1""", viajero.usuario_id, t0)
    return _tramos(t0, observada["publicado_en"], _llegada_a_itinerary(observada["evento_id"]),
                   visible)


def _localizador(prefijo: str) -> str:
    """Un localizador de 6 caracteres, como los de la aerolínea simulada, y único por corrida."""
    return (prefijo + uuid4().hex.upper())[:6]


def _verificar(camino: str, mediciones: list[dict[str, float]]) -> None:
    totales = [m["total"] for m in mediciones]
    print(f"\nQA-01 por {camino}: {len(totales)} actualizaciones · p50 "
          f"{percentil(totales, 50):.2f} s · p95 {percentil(totales, 95):.2f} s · "
          f"p99 {percentil(totales, 99):.2f} s (objetivo: p95 ≤ {TOTAL_P95_S} s, "
          f"p99 ≤ {TOTAL_P99_S} s)")
    for tramo, presupuesto in PRESUPUESTO.items():
        peor = max(m[tramo] for m in mediciones)
        print(f"  {tramo:<45} peor {peor:6.2f} s · presupuesto {presupuesto} s")
        assert peor <= presupuesto, f"{camino}: el tramo «{tramo}» tardó {peor:.1f} s"
    assert percentil(totales, 95) <= TOTAL_P95_S
    assert percentil(totales, 99) <= TOTAL_P99_S


def test_qa01_una_reserva_reenviada_por_correo_llega_al_panel_dentro_del_presupuesto(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    base = ahora().replace(microsecond=0) + timedelta(days=7)
    localizadores = [_localizador(f"C{i}") for i in range(CORREOS)]
    mediciones = [_por_correo(viajero, localizador, base + timedelta(days=i))
                  for i, localizador in enumerate(localizadores)]
    reserva = viajero.reservas()[localizadores[0]]
    assert reserva["estado"] == "Confirmada" and reserva["fuentes"] == ["correo"]
    _verificar("correo", mediciones)


def test_qa01_un_cambio_del_proveedor_llega_al_panel_dentro_del_presupuesto(cliente):
    viajero = Viajero(cliente).iniciar_sesion().conectar_reenvio()
    localizador = _localizador("P")
    salida = ahora().replace(microsecond=0) + timedelta(days=10)
    assert viajero.reenviar_confirmacion(localizador, salida).status_code == 202
    esperar(lambda: inicio_en_el_panel(viajero, localizador), 60, "la reserva en el panel")
    esperar_seguimiento(localizador)

    mediciones = [_por_proveedor(cliente, viajero, localizador,
                                 salida + timedelta(minutes=30 * (i + 1))) for i in range(CAMBIOS)]
    reserva = viajero.reservas()[localizador]
    assert set(reserva["fuentes"]) == {"correo", "proveedor"}
    assert not reserva.get("conflictosAbiertos")  # el proveedor actualiza, no discute con el correo
    _verificar("proveedor", mediciones)


def test_qa01_las_marcas_de_tiempo_son_de_un_mismo_reloj():
    """Los tramos restan marcas del anfitrión y de PostgreSQL: tienen que ser del mismo reloj."""
    exigir_contenedores()
    base = fila("itinerary", "SELECT now() AS ahora")["ahora"]
    assert abs((base - datetime.now(timezone.utc)).total_seconds()) < 2
