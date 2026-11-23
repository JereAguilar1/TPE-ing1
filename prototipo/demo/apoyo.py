"""Comandos de apoyo de la demostración (guion, momentos 2 y 3.4), para el viajero de un correo.

Uso, con `make servicios-arriba` y desde cualquier carpeta:

    prototipo/.venv/bin/python prototipo/demo/apoyo.py cambio-de-horario ana@ejemplo.com
    prototipo/.venv/bin/python prototipo/demo/apoyo.py disrupcion ana@ejemplo.com

- `cambio-de-horario`: la aerolínea avisa por *push* a `provider-sync` que el próximo vuelo del
  viajero sale una hora y media más tarde (NDC simulado, firmado). El panel lo muestra solo.
- `disrupcion`: el viajero elige su agencia preferida en `preferences` (`PUT /preferencias` por
  `api-gateway`) y se publica `DisrupcionDetectada` del próximo vuelo, como la publicaría
  `provider-sync` ante una cancelación. Después, en el chat: «¿Se canceló mi vuelo?».
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

PROTOTIPO = Path(__file__).resolve().parents[1]
os.chdir(PROTOTIPO)  # para leer .env y las ayudas de los escenarios, desde cualquier carpeta
sys.path.insert(0, str(PROTOTIPO))

from tests.escenarios.contenedores import API_GATEWAY, Viajero, notificar_cambio  # noqa: E402

TIPO = "application/vnd.trotamundos.v1+json"


def _proximo_vuelo(cliente: httpx.Client, viajero: Viajero) -> dict[str, Any]:
    respuesta = cliente.get(f"{API_GATEWAY}/panel", headers=viajero.sesion)
    respuesta.raise_for_status()
    vuelos = [r for v in respuesta.json()["viajesActivos"] for r in v["reservas"]
              if r["segmentos"][0]["tipo"] == "vuelo"]
    if not vuelos:
        sys.exit("El viajero no tiene vuelos en el panel: correr antes demo/cargar_viajes.py")
    return min(vuelos, key=lambda r: r["segmentos"][0]["inicio"]["instante"])


def cambio_de_horario(cliente: httpx.Client, viajero: Viajero) -> None:
    vuelo = _proximo_vuelo(cliente, viajero)
    localizador = next(i["codigo"] for i in vuelo["identificadores"]
                       if i["emisor"].startswith("aerolinea:"))
    salida = datetime.fromisoformat(vuelo["segmentos"][0]["inicio"]["instante"].replace("Z", "+00:00"))
    nueva = salida + timedelta(minutes=90)
    notificar_cambio(cliente, localizador, nueva).raise_for_status()
    print(f"La aerolínea avisó: el vuelo {localizador} sale a las {nueva:%H:%M} UTC "
          f"(antes, {salida:%H:%M} UTC). Mirá el panel.")


def disrupcion(cliente: httpx.Client, viajero: Viajero) -> None:
    respuesta = cliente.put(f"{API_GATEWAY}/preferencias", headers={
        **viajero.sesion, "Content-Type": TIPO}, json={
        "agenciaPreferida": {"id": "agencia-sur", "nombre": "Agencia del Sur"},
        "idioma": "es-AR", "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM"})
    respuesta.raise_for_status()
    print("Agencia preferida: Agencia del Sur (preferences publica PreferenciasActualizadas)")
    vuelo = _proximo_vuelo(cliente, viajero)
    usuario = _usuario_del_token(viajero.token)
    asyncio.run(_publicar_disrupcion(usuario, vuelo["id"]))
    print("Publicada DisrupcionDetectada: vuelo cancelado por tormenta. "
          "En el chat: «¿Se canceló mi vuelo?»")


def _usuario_del_token(token: str) -> str:
    """El usuario de la sesión, con la firma verificada como en los servicios (`comun.sesion`)."""
    from trotamundos.comun.config import _variable
    from trotamundos.comun.sesion import usuario_de_sesion
    return str(usuario_de_sesion(f"Bearer {token}", _variable("TROTAMUNDOS_JWT_SECRETO")))


async def _publicar_disrupcion(usuario: str, reserva: str) -> None:
    from aiokafka import AIOKafkaProducer

    from trotamundos.comun.carriles import topico
    from trotamundos.comun.config import Configuracion
    from trotamundos.comun.contratos import contratos_por_omision
    from trotamundos.comun.eventos import Evento

    evento = Evento.nuevo("DisrupcionDetectada", {
        "disrupcionId": f"disr-{usuario[:8]}-{reserva[:8]}", "proveedor": "Aerolíneas Argentinas",
        "severidad": "alta", "descripcion": "Vuelo cancelado por tormenta",
        "afectados": [{"usuarioId": usuario, "reservaIds": [reserva]}]},
        productor="provider-sync", usuario_id=usuario, region="AM")
    configuracion = Configuracion.desde_entorno()
    productor = AIOKafkaProducer(bootstrap_servers=configuracion.broker)
    await productor.start()
    try:
        clave, valor, cabeceras = evento.a_kafka()
        await productor.send_and_wait(
            topico(contratos_por_omision(), evento.tipo, "P1", configuracion.prefijo_topicos),
            valor, key=clave, headers=cabeceras)
    finally:
        await productor.stop()


COMANDOS = {"cambio-de-horario": cambio_de_horario, "disrupcion": disrupcion}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in COMANDOS:
        sys.exit(f"Uso: apoyo.py {{{'|'.join(COMANDOS)}}} <correo>")
    with httpx.Client(timeout=20) as http:
        COMANDOS[sys.argv[1]](http, Viajero(http, sys.argv[2]).iniciar_sesion())
