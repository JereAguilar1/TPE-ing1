"""Ayudas de los escenarios que corren contra los contenedores de `make servicios-arriba` (paso 17).

Los escenarios de QA-01 y QA-04 recorren el sistema de punta a punta, con cada servicio en su
proceso y el *broker* real: un viajero inicia sesión en `identity-access`, conecta un buzón por
reenvío, le llegan correos por `mail-ingest` y `booking-extraction`, la aerolínea avisa cambios a
`provider-sync`, e `itinerary` los refleja en el panel que lee `bff-web`. Nada se inyecta a mano.

Sin los contenedores, las pruebas se saltean; en la integración continua
(`TROTAMUNDOS_EXIGIR_CONTENEDORES=1`, trabajo `servicios`), fallan.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any, Callable, TypeVar
from uuid import uuid4

import httpx
import pytest

from trotamundos.comun.config import Configuracion, _variable
from trotamundos.comun.persistencia import conectar

IDENTITY_ACCESS = "http://localhost:18103"
MAIL_INGEST = "http://localhost:18104"
BFF_WEB = "http://localhost:18108"
PROVIDER_SYNC = "http://localhost:18109"
PUERTOS = {"itinerary-escritura": 18101, "itinerary-lectura": 18102, "identity-access": 18103,
           "mail-ingest": 18104, "booking-extraction": 18107, "bff-web": 18108,
           "provider-sync": 18109, "app-web": 18111}
ADAPTADOR = "adaptador-aerolinea-simulada"
REMITENTE = "reservas@aerolinea.example"  # lo reconoce el extractor de ejemplo del paso 9
SONDEO_S = 0.05

T = TypeVar("T")


def exigir_contenedores() -> None:
    """Saltea la prueba si los servicios no están arriba; en la integración continua, falla."""
    caidos = []
    for servicio, puerto in PUERTOS.items():
        try:
            socket.create_connection(("localhost", puerto), 1).close()
        except OSError:
            caidos.append(servicio)
    if caidos:
        motivo = f"Contenedores no disponibles ({', '.join(caidos)}): correr `make servicios-arriba`"
        if os.environ.get("TROTAMUNDOS_EXIGIR_CONTENEDORES") == "1":
            pytest.fail(motivo, pytrace=False)
        pytest.skip(motivo)


def esperar(condicion: Callable[[], T | None], limite_s: float, que: str) -> T:
    fin = time.monotonic() + limite_s
    while time.monotonic() < fin:
        resultado = condicion()
        if resultado:
            return resultado
        time.sleep(SONDEO_S)
    raise AssertionError(f"No pasó en {limite_s:.0f} s: {que}")


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def texto_utc(instante: datetime) -> str:
    return instante.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def percentil(valores: list[float], p: float) -> float:
    """Percentil por el método del rango más cercano (el de los SLO del análisis inicial)."""
    ordenados = sorted(valores)
    indice = max(0, min(len(ordenados) - 1, int(round(p / 100 * len(ordenados) + 0.5)) - 1))
    return ordenados[indice]


def fila(esquema: str, consulta: str, *parametros: Any) -> dict[str, Any] | None:
    with conectar(Configuracion.desde_entorno().dsn_postgres, esquema) as conexion:
        return conexion.execute(consulta, parametros).fetchone()


# --- el viajero -------------------------------------------------------------------------------

@dataclass
class Viajero:
    """Un usuario nuevo, con sesión OIDC y un buzón conectado por reenvío (ADR-0035)."""

    cliente: httpx.Client
    correo: str = field(default_factory=lambda: f"escenario-{uuid4().hex[:10]}@ejemplo.com")
    token: str = ""
    usuario_id: str = ""
    alias: str = ""

    @property
    def sesion(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def iniciar_sesion(self) -> "Viajero":
        respuesta = self.cliente.post(f"{IDENTITY_ACCESS}/sesiones", json={
            "codigo": f"oidc:{self.correo}:AM", "verificadorPkce": "v" * 43,
            "uriRedireccion": "https://trotamundos.app/callback"})
        assert respuesta.status_code == 201, respuesta.text
        self.token = respuesta.json()["tokenAcceso"]
        return self

    def conectar_reenvio(self) -> "Viajero":
        respuesta = self.cliente.post(f"{IDENTITY_ACCESS}/buzones", json={"via": "reenvio"},
                                      headers={**self.sesion, "Idempotency-Key": str(uuid4())})
        assert respuesta.status_code == 201, respuesta.text
        buzon = respuesta.json()
        self.alias = buzon["aliasReenvio"]
        # identity-access avisa por EstadoDeBuzonCambiado; mail-ingest lo activa al consumirlo
        esperar(lambda: fila("mail_ingest", "SELECT usuario_id FROM buzon_ingesta "
                                            "WHERE buzon_id = %s AND activo", buzon["id"]),
                90, "mail-ingest activa el buzón")
        self.usuario_id = str(fila("mail_ingest", "SELECT usuario_id FROM buzon_ingesta "
                                                  "WHERE buzon_id = %s", buzon["id"])["usuario_id"])
        return self

    def reenviar_confirmacion(self, localizador: str, salida: datetime, origen: str = "AEP",
                              destino: str = "MDZ", rotulo: str = "Localizador",
                              numero: str = "1402") -> httpx.Response:
        """El viajero reenvía a su alias la confirmación de la aerolínea. Con el rótulo
        «Localizador tentativo» el extractor la lee con confianza media: queda por confirmar."""
        emitido = ahora().replace(microsecond=0)
        cuerpo = "\n".join([
            "Reserva aérea simulada v1", f"{rotulo}: {localizador}", "Aerolinea: AR",
            f"Numero: {numero}", f"Origen: {origen}", f"Destino: {destino}", f"Salida: {texto_utc(salida)}",
            f"Llegada: {texto_utc(salida + timedelta(hours=2))}", f"Emitido: {texto_utc(emitido)}"])
        return self.reenviar(REMITENTE, f"Tu reserva {localizador}", cuerpo, emitido)

    def reenviar_boleto_de_tren(self, localizador: str, salida: datetime, origen: str = "ATO",
                                destino: str = "BCN") -> httpx.Response:
        """El viajero reenvía el boleto del ferrocarril de ejemplo (extractor del tren, QA-15)."""
        emitido = ahora().replace(microsecond=0)
        cuerpo = "\n".join([
            "Boleto de tren simulado v1", f"Localizador: {localizador}", "Operador: RF",
            "Tren: 03071", f"Origen: {origen}", f"Destino: {destino}",
            f"Salida: {texto_utc(salida)}", f"Llegada: {texto_utc(salida + timedelta(hours=3))}",
            "Coche: 5", "Asiento: 12A", "Anden: 7", f"Emitido: {texto_utc(emitido)}"])
        return self.reenviar("boletos@ferrocarril.example", f"Tu boleto {localizador}", cuerpo,
                             emitido)

    def reenviar(self, remitente: str, asunto: str, cuerpo: str, emitido: datetime) -> httpx.Response:
        """Reenvía a su alias un correo de `remitente`, verificado por el servidor propio."""
        correo = EmailMessage()
        correo["Return-Path"] = f"<{self.correo}>"  # quien reenvía es el titular del buzón
        correo["From"] = remitente
        correo["To"] = self.alias
        correo["Subject"] = asunto
        correo["Date"] = format_datetime(emitido)
        correo["Message-ID"] = f"<{uuid4().hex}@{remitente.partition('@')[2]}>"
        correo["Authentication-Results"] = "ingesta.trotamundos.app; dkim=pass; spf=pass"
        correo.set_content(cuerpo)
        return self.cliente.post(f"{MAIL_INGEST}/webhooks/correo/reenvio", content=bytes(correo),
                                 headers={"X-Alias-Destino": self.alias,
                                          "X-Servicio-Cliente": "mta-entrante",
                                          "Content-Type": "message/rfc822"})

    def panel(self) -> tuple[dict[str, Any], float]:
        """`GET /panel` de `bff-web` y cuánto tardó, en milisegundos."""
        inicio = time.perf_counter()
        respuesta = self.cliente.get(f"{BFF_WEB}/panel", headers=self.sesion)
        demora_ms = (time.perf_counter() - inicio) * 1000
        assert respuesta.status_code == 200, respuesta.text
        return respuesta.json(), demora_ms

    def reservas(self) -> dict[str, dict[str, Any]]:
        """Las reservas del panel, por su localizador."""
        datos, _ = self.panel()
        todas = [r for v in datos["viajesActivos"] for r in v["reservas"]] + datos["porConfirmar"]
        return {i["codigo"]: r for r in todas for i in r["identificadores"]}


def inicio_en_el_panel(viajero: Viajero, localizador: str) -> str | None:
    reserva = viajero.reservas().get(localizador)
    return reserva["segmentos"][0]["inicio"]["instante"] if reserva else None


def esperar_seguimiento(localizador: str, limite_s: float = 90, adaptador: str = ADAPTADOR) -> None:
    """`provider-sync` sigue la reserva desde que consume su `ReservaActualizada`."""
    esperar(lambda: fila("provider_sync", "SELECT 1 FROM reserva_seguida WHERE adaptador_id = %s "
                                          "AND referencia = %s", adaptador, localizador),
            limite_s, f"provider-sync sigue {localizador}")


# --- la aerolínea -----------------------------------------------------------------------------

def _avisar(cliente: httpx.Client, adaptador: str, notificacion: dict) -> httpx.Response:
    crudo = json.dumps(notificacion).encode("utf-8")
    firma = hmac.new(_variable("TROTAMUNDOS_SECRETO_WEBHOOK_PROVEEDOR").encode("utf-8"), crudo,
                     hashlib.sha256).hexdigest()
    return cliente.post(f"{PROVIDER_SYNC}/webhooks/proveedor", content=crudo,
                        headers={"X-Proveedor-Id": adaptador, "X-Firma": firma,
                                 "Content-Type": "application/json"})


def notificar_cambio_de_tren(cliente: httpx.Client, localizador: str, salida: datetime,
                             anden: str) -> httpx.Response:
    """El operador ferroviario avisa por *push* un cambio de horario y de andén (OSDM simulado)."""
    return _avisar(cliente, "adaptador-ferrocarril-simulado", {
        "eventId": f"osdm-{uuid4()}", "issuedAt": ahora().isoformat(),
        "bookings": [{"bookingRef": localizador, "carrier": "RF", "trips": [{
            "trainNumber": "03071", "coach": "5", "seat": "12A", "platform": anden,
            "origin": {"station": "ATO", "time": salida.isoformat()},
            "destination": {"station": "BCN", "time": (salida + timedelta(hours=3)).isoformat()}}]}]})


def notificar_cambio(cliente: httpx.Client, localizador: str, salida: datetime,
                     emitida: datetime | None = None) -> httpx.Response:
    """La aerolínea avisa por *push* un cambio de horario (NDC simulado, firmado con HMAC)."""
    notificacion = {
        "notificationId": f"notif-{uuid4()}", "timestamp": (emitida or ahora()).isoformat(),
        "orders": [{"orderId": localizador, "owner": "AR", "orderStatus": "ACTIVE", "flights": [{
            "flightNumber": "1402", "operatorName": "Aerolíneas Argentinas",
            "departure": {"airport": "AEP", "time": salida.isoformat()},
            "arrival": {"airport": "MDZ", "time": (salida + timedelta(hours=2)).isoformat()},
            "statusCode": "HK", "gate": "7"}]}]}
    return _avisar(cliente, ADAPTADOR, notificacion)
