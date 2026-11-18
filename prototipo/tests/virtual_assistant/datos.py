"""Datos y dobles de prueba del asistente: un itinerario y un `support-liaison` en memoria.

El viaje a Madrid tiene un vuelo (AR1402, jueves 3/12 a las 10:00 de Buenos Aires) y un hotel con un
conflicto abierto; además hay un tren por confirmar que llegó por correo.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from trotamundos.comun.contratos import contratos_por_omision
from trotamundos.servicios.virtual_assistant import acciones, contexto, derivacion

USUARIO = UUID("00000000-0000-4000-8000-0000000000a1")
OTRO = UUID("00000000-0000-4000-8000-0000000000a2")
VIAJE = "00000000-0000-4000-8000-0000000000b1"
VUELO = "00000000-0000-4000-8000-0000000000c1"
HOTEL = "00000000-0000-4000-8000-0000000000c2"
TREN = "00000000-0000-4000-8000-0000000000c3"
CONFLICTO = "00000000-0000-4000-8000-0000000000d1"
SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
AHORA = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)  # viernes
BAIRES, MADRID = "America/Argentina/Buenos_Aires", "Europe/Madrid"

_CONTRATOS = contratos_por_omision()
_EDICION = "openapi/comun.yaml#/components/schemas/EdicionReserva"
_CASO = ("openapi/support-liaison.yaml#/paths/~1casos/post/requestBody/content/"
         "application~1vnd.trotamundos.v1+json/schema")


def _lugar(nombre: str, pais: str, zona: str) -> dict:
    return {"nombre": nombre, "pais": pais, "zonaHoraria": zona}


def _extremo(instante: str, lugar: dict, precision: str = "instante") -> dict:
    return {"instante": instante, "precision": precision, "zonaHoraria": lugar["zonaHoraria"],
            "lugar": lugar}


def _reserva(id_: str, tipo: str, referencia: str, inicio: dict, fin: dict, *,
             estado: str = "Confirmada", viaje: str | None = VIAJE) -> dict:
    return {"id": id_, "estado": estado, "version": 3,
            "identificadores": [{"emisor": "agencia:prueba", "codigo": f"LOC{referencia}"}],
            "segmentos": [{"id": f"{id_[:-2]}e{id_[-1]}", "tipo": tipo, "versionTipo": 1, "orden": 0,
                           "inicio": inicio, "fin": fin, "operador": "Operador de prueba",
                           "referencia": referencia, "estado": "confirmado", "detalle": {}}],
            "fuentes": ["correo"], "viajeId": viaje}


def itinerario_inicial() -> dict:
    aeroparque = _lugar("Aeroparque", "AR", BAIRES)
    barajas = _lugar("Barajas", "ES", MADRID)
    hotel_madrid = _lugar("Hotel Prado", "ES", MADRID)
    atocha = _lugar("Atocha", "ES", MADRID)
    vuelo = _reserva(VUELO, "vuelo", "AR1402", _extremo("2026-12-03T13:00:00Z", aeroparque),
                     _extremo("2026-12-04T05:00:00Z", barajas))
    hotel = _reserva(HOTEL, "hotel", "HTL778", _extremo("2026-12-04T13:00:00Z", hotel_madrid),
                     _extremo("2026-12-08T10:00:00Z", hotel_madrid))
    hotel["conflictosAbiertos"] = [{
        "id": CONFLICTO, "campo": "segmentos[0].inicio.instante", "estado": "Abierto",
        "valores": [{"fuente": "manual", "valor": "2026-12-04T13:00:00Z"},
                    {"fuente": "proveedor", "valor": "2026-12-04T12:00:00Z"}]}]
    tren = _reserva(TREN, "tren", "IRYO6020", _extremo("2026-12-06T08:00:00Z", atocha),
                    _extremo("2026-12-06T11:00:00Z", atocha), estado="PorConfirmar", viaje=None)
    tren["banda"] = "media"
    viaje = {"id": VIAJE, "titulo": "Viaje a Madrid", "estado": "Planificado",
             "desde": "2026-12-03T13:00:00Z", "hasta": "2026-12-08T10:00:00Z", "version": 1,
             "reservas": [vuelo, hotel]}
    return {"viajes": [viaje], "porConfirmar": [tren]}


class ItinerarioEnMemoria:
    """Hace de `itinerary-lectura` y de `itinerary-escritura` para `USUARIO`. Valida los cuerpos
    contra el contrato y respeta el control de versión (`409`)."""

    def __init__(self):
        self.datos = itinerario_inicial()
        self.escrituras: list[tuple] = []
        self.disponible = True

    def _exigir(self) -> None:
        if not self.disponible:
            raise contexto.ItinerarioNoDisponible("apagado")

    # --- lectura -----------------------------------------------------------------------------

    def panel(self, usuario_id):
        self._exigir()
        if str(usuario_id) != str(USUARIO):
            return {"viajesActivos": [], "porConfirmar": [], "conflictosAbiertos": [],
                    "versionUsuario": 0}
        viajes = copy.deepcopy(self.datos["viajes"])
        por_confirmar = copy.deepcopy(self.datos["porConfirmar"])
        return {"viajesActivos": viajes, "porConfirmar": por_confirmar,
                "conflictosAbiertos": [{"reservaId": r["id"], "conflicto": c}
                                       for v in viajes for r in v["reservas"]
                                       for c in r.get("conflictosAbiertos", [])],
                "versionUsuario": 7}

    def viaje(self, usuario_id, viaje_id):
        self._exigir()
        if str(usuario_id) != str(USUARIO):
            return None
        return copy.deepcopy(next((v for v in self.datos["viajes"] if v["id"] == str(viaje_id)),
                                  None))

    def reserva(self, reserva_id: str) -> dict | None:
        todas = [r for v in self.datos["viajes"] for r in v["reservas"]] + self.datos["porConfirmar"]
        return next((r for r in todas if r["id"] == reserva_id), None)

    # --- escritura ---------------------------------------------------------------------------

    def _propia(self, usuario_id, reserva_id: str) -> dict:
        if not self.disponible:
            raise acciones.EscrituraNoDisponible("apagado")
        reserva = self.reserva(reserva_id)
        if str(usuario_id) != str(USUARIO) or reserva is None:
            raise acciones.ReservaInexistente(reserva_id)
        return reserva

    def editar(self, usuario_id, reserva_id, cuerpo):
        _CONTRATOS.validar(_EDICION, cuerpo)
        reserva = self._propia(usuario_id, reserva_id)
        if cuerpo["version"] != reserva["version"]:
            raise acciones.ReservaCambiada(reserva_id)
        for actual, nuevo in zip(reserva["segmentos"], cuerpo["segmentos"]):
            actual["inicio"], actual["fin"] = nuevo["inicio"], nuevo["fin"]
        reserva["version"] += 1
        self.escrituras.append(("editar", reserva_id, copy.deepcopy(cuerpo)))

    def confirmar(self, usuario_id, reserva_id, decision):
        reserva = self._propia(usuario_id, reserva_id)
        if reserva["estado"] != "PorConfirmar":
            raise acciones.ReservaCambiada(reserva_id)
        self.datos["porConfirmar"].remove(reserva)
        self.escrituras.append(("confirmar", reserva_id, decision))

    def resolver(self, usuario_id, reserva_id, conflicto_id, cuerpo):
        reserva = self._propia(usuario_id, reserva_id)
        abiertos = reserva.get("conflictosAbiertos", [])
        if not any(c["id"] == conflicto_id for c in abiertos):
            raise acciones.ReservaCambiada(reserva_id)
        reserva["conflictosAbiertos"] = [c for c in abiertos if c["id"] != conflicto_id]
        self.escrituras.append(("resolver", reserva_id, conflicto_id, dict(cuerpo)))


class SoporteEnMemoria:
    """Hace de `support-liaison`: idempotente por `Idempotency-Key`, valida el cuerpo y responde
    `422` si el viajero no tiene agencia."""

    def __init__(self):
        self.casos: dict[str, dict] = {}  # por Idempotency-Key
        self.pedidos: list[tuple[str, dict]] = []
        self.con_agencia = True
        self.disponible = True

    def abrir(self, authorization, clave, cuerpo):
        if not self.disponible:
            raise derivacion.SoporteNoDisponible("apagado")
        _CONTRATOS.validar(_CASO, dict(cuerpo))
        assert authorization.startswith("Bearer ")
        self.pedidos.append((clave, dict(cuerpo)))
        if not self.con_agencia:
            raise derivacion.SinAgencia()
        if clave not in self.casos:
            self.casos[clave] = {"id": f"00000000-0000-4000-8000-{len(self.casos) + 1:012d}",
                                 "viajeId": cuerpo["viajeId"], "motivo": cuerpo["motivo"],
                                 "agencia": "Agencia del Sur", "estado": "Derivado",
                                 "abiertoEn": "2026-11-20T12:00:00Z"}
        return self.casos[clave]


def sesion_http(usuario: UUID = USUARIO) -> dict[str, str]:
    token = jwt.encode({"sub": str(usuario), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       SECRETO_JWT, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
