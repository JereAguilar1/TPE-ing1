"""Carga viajes de ejemplo al viajero de un correo, por los caminos reales del prototipo.

Uso, con `make servicios-arriba` y desde cualquier carpeta:

    prototipo/.venv/bin/python prototipo/demo/cargar_viajes.py ana@ejemplo.com

Después se entra a http://localhost:18111 con ese mismo correo. Carga:

- la ida Buenos Aires → Mendoza, por un correo reenviado al alias del viajero
  (`mail-ingest` → `booking-extraction` → `itinerary`);
- un hotel en Mendoza, cargado a mano por `bff-web` (`POST /reservas`);
- la vuelta Mendoza → Buenos Aires, por un correo con datos dudosos: queda «por confirmar»;
- un tren Madrid → Barcelona, por el boleto del ferrocarril reenviado (extractor del tren, QA-15).

La ida, el hotel y la vuelta forman un solo viaje (RF-07).
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import httpx

PROTOTIPO = Path(__file__).resolve().parents[1]
os.chdir(PROTOTIPO)  # para leer .env y las ayudas de los escenarios, desde cualquier carpeta
sys.path.insert(0, str(PROTOTIPO))

from tests.escenarios.contenedores import (  # noqa: E402
    BFF_WEB,
    Viajero,
    ahora,
    esperar,
    inicio_en_el_panel,
)

MENDOZA = ("Hotel Aconcagua", "AR", "America/Argentina/Mendoza", -32.8908, -68.8272)


def _extremo(instante, nombre, pais, zona, lat, lon) -> dict:
    return {"instante": instante.isoformat(), "precision": "instante", "zonaHoraria": zona,
            "lugar": {"nombre": nombre, "pais": pais, "zonaHoraria": zona,
                      "coordenadas": {"lat": lat, "lon": lon}}}


def _localizador(prefijo: str) -> str:
    return (prefijo + uuid.uuid4().hex.upper())[:6]


def main(correo: str) -> None:
    with httpx.Client(timeout=20) as cliente:
        viajero = Viajero(cliente, correo).iniciar_sesion().conectar_reenvio()
        print(f"Sesión de {correo}; buzón por reenvío: {viajero.alias}")

        def alta(segmento: dict, que: str) -> None:
            respuesta = cliente.post(f"{BFF_WEB}/reservas", json={"segmentos": [segmento]},
                                     headers={**viajero.sesion, "Idempotency-Key": str(uuid.uuid4())})
            if respuesta.status_code != 201:
                sys.exit(f"No se pudo cargar {que}: {respuesta.status_code} {respuesta.text}")
            print(f"{que} (carga manual) → en el panel")

        ida = ahora().replace(microsecond=0, second=0, minute=0) + timedelta(days=6)
        vuelta = ida + timedelta(days=4)

        localizador = _localizador("I")
        viajero.reenviar_confirmacion(localizador, ida).raise_for_status()
        esperar(lambda: inicio_en_el_panel(viajero, localizador), 60, "la ida en el panel")
        print(f"✈️  Ida {localizador} (correo reenviado) → en el panel")

        alta({"tipo": "hotel", "operador": "Hotel Aconcagua", "referencia": "HAC552",
              "detalle": {"habitaciones": 1, "huespedes": 2, "regimen": "desayuno"},
              "inicio": _extremo(ida + timedelta(hours=5), *MENDOZA),
              "fin": _extremo(vuelta - timedelta(hours=3), *MENDOZA)}, "🏨 Hotel en Mendoza")

        localizador = _localizador("V")
        viajero.reenviar_confirmacion(localizador, vuelta, "MDZ", "AEP", numero="1403",
                                      rotulo="Localizador tentativo").raise_for_status()
        esperar(lambda: inicio_en_el_panel(viajero, localizador), 60, "la vuelta en el panel")
        print(f"✈️  Vuelta {localizador} (correo con datos dudosos) → por confirmar")

        localizador = _localizador("T")
        viajero.reenviar_boleto_de_tren(localizador, ida + timedelta(days=20)).raise_for_status()
        esperar(lambda: inicio_en_el_panel(viajero, localizador), 60, "el tren en el panel")
        print(f"🚆 Tren Madrid → Barcelona {localizador} (boleto reenviado: extractor del tren)")
    print(f"\nListo. Ingresá a http://localhost:18111 con {correo}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: cargar_viajes.py <correo>")
    main(sys.argv[1])
