"""`support-liaison` contra PostgreSQL (RF-12, UC-7, `support-liaison.yaml`). Sin base, se saltean.

La instantánea del viaje la da un lector de prueba en lugar de `itinerary-lectura`, y la agencia es
el complemento simulado.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.servicios.support_liaison.servicio import SupportLiaison

USUARIO = UUID("00000000-0000-4000-8000-0000000000d1")
OTRO = UUID("00000000-0000-4000-8000-0000000000d2")
VIAJE = UUID("00000000-0000-4000-8000-0000000000e1")
RESERVA = UUID("00000000-0000-4000-8000-0000000000e2")
SECRETO_JWT = "secreto-jwt-de-prueba-de-32-bytes!"
AHORA = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
TIPO = {"Content-Type": "application/vnd.trotamundos.v1+json"}
CASO = "openapi/support-liaison.yaml#/components/schemas/Caso"


class LectorDePrueba:
    """Hace de `itinerary-lectura`: el viaje `VIAJE` es de `USUARIO`, y nada más."""

    def viaje(self, usuario_id, viaje_id):
        if str(usuario_id) != str(USUARIO) or str(viaje_id) != str(VIAJE):
            return None
        return {"id": str(VIAJE), "titulo": "Viaje a Mendoza", "estado": "Planificado",
                "reservas": [{"id": str(RESERVA), "estado": "Confirmada"}]}


@pytest.fixture
def soporte(dsn, esquema, contratos):
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn,
                                        broker="", intervalo_tareas_s=0)
    reloj = {"ahora": AHORA}
    servicio = SupportLiaison(configuracion, esquema=esquema, contratos=contratos,
                              lector_de_viajes=LectorDePrueba(), secreto_jwt=SECRETO_JWT,
                              reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.bd, servicio.reloj = (dsn, esquema), reloj
    servicio.cliente = TestClient(servicio.app())
    return servicio


def _filas(soporte, consulta: str) -> list[dict]:
    with conectar(*soporte.bd) as conexion:
        return conexion.execute(consulta).fetchall()


def _sesion(usuario: UUID = USUARIO) -> dict[str, str]:
    token = jwt.encode({"sub": str(usuario), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                       SECRETO_JWT, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _preferencias(soporte, agencia: dict | None, usuario: UUID = USUARIO) -> Evento:
    """Lo que publicaría `preferences` (en el prototipo lo inyectan las pruebas y la demo)."""
    evento = Evento.nuevo("PreferenciasActualizadas", {"preferencias": {
        "agenciaPreferida": agencia, "idioma": "es-AR",
        "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM"}},
        productor="preferences", usuario_id=str(usuario), region="AM")
    soporte.consumir(evento)
    return evento


def _abrir(soporte, cuerpo: dict | None = None, clave: str | None = None, usuario: UUID = USUARIO):
    cuerpo = cuerpo if cuerpo is not None else {"viajeId": str(VIAJE), "motivo": "cancelacion"}
    return soporte.cliente.post("/casos", content=json.dumps(cuerpo), headers={
        **_sesion(usuario), **TIPO, "Idempotency-Key": clave or str(uuid4())})


AGENCIA = {"id": "agencia-del-sur", "nombre": "Agencia del Sur"}


def test_sin_agencia_preferida_el_caso_no_se_abre(soporte):
    respuesta = _abrir(soporte)
    assert respuesta.status_code == 422
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    assert "preferencias" in respuesta.json()["detail"]
    assert _filas(soporte, "SELECT * FROM caso") == []


def test_el_caso_se_deriva_a_la_agencia_y_se_publica(soporte, contratos):
    _preferencias(soporte, AGENCIA)
    respuesta = _abrir(soporte, {"viajeId": str(VIAJE), "reservaId": str(RESERVA),
                                 "motivo": "cancelacion", "descripcion": "Cancelaron el vuelo",
                                 "idDeCausa": "disrupcion-42"})

    assert respuesta.status_code == 201
    assert respuesta.headers["content-type"].startswith("application/vnd.trotamundos.v1+json")
    caso = respuesta.json()
    contratos.validar(CASO, caso)
    assert caso["estado"] == "Derivado" and caso["agencia"] == "Agencia del Sur"
    assert caso["referenciaAgencia"].startswith("AG-")
    # La agencia recibió el caso con la instantánea del viaje.
    [(agencia_id, recibido)] = soporte.adaptador.recibidos
    assert agencia_id == "agencia-del-sur" and recibido["viaje"]["titulo"] == "Viaje a Mendoza"
    assert recibido["idDeCausa"] == "disrupcion-42"
    # CasoDerivado en la outbox, por P1, con la causa en el sobre.
    [evento] = _filas(soporte, "SELECT tipo, carril, sobre, carga FROM bandeja_salida")
    assert (evento["tipo"], evento["carril"]) == ("CasoDerivado", "P1")
    assert evento["carga"] == {"casoId": caso["id"], "viajeId": str(VIAJE),
                               "agencia": "Agencia del Sur", "motivo": "cancelacion"}
    assert evento["sobre"]["idDeCausa"] == "disrupcion-42"


def test_la_misma_clave_abre_un_solo_caso(soporte):
    _preferencias(soporte, AGENCIA)
    clave = str(uuid4())
    primera = _abrir(soporte, clave=clave)
    segunda = _abrir(soporte, clave=clave)
    assert segunda.status_code == 201 and segunda.json() == primera.json()
    assert len(_filas(soporte, "SELECT * FROM caso")) == 1
    otra = _abrir(soporte, {"viajeId": str(VIAJE), "motivo": "otro"}, clave=clave)
    assert otra.status_code == 400


def test_un_viaje_o_una_reserva_ajenos_responden_404(soporte):
    _preferencias(soporte, AGENCIA)
    _preferencias(soporte, AGENCIA, usuario=OTRO)
    assert _abrir(soporte, usuario=OTRO).status_code == 404
    assert _abrir(soporte, {"viajeId": str(uuid4()), "motivo": "otro"}).status_code == 404
    assert _abrir(soporte, {"viajeId": str(VIAJE), "reservaId": str(uuid4()),
                            "motivo": "otro"}).status_code == 404
    assert _filas(soporte, "SELECT * FROM caso") == []


def test_si_la_agencia_no_responde_queda_abierto_y_se_reintenta(soporte):
    """ADR-0024: espera creciente; el viajero recibe el caso con su estado real."""
    _preferencias(soporte, AGENCIA)
    soporte.adaptador.fallar()
    respuesta = _abrir(soporte)
    caso = respuesta.json()
    assert respuesta.status_code == 201 and caso["estado"] == "Abierto"
    assert _filas(soporte, "SELECT * FROM bandeja_salida") == []

    soporte.tareas_periodicas()  # todavía en espera: no se reintenta
    soporte.adaptador.fallar(False)
    soporte.tareas_periodicas()
    assert soporte.adaptador.recibidos == []

    soporte.reloj["ahora"] = AHORA + timedelta(seconds=5)
    soporte.tareas_periodicas()
    assert soporte.cliente.get(f"/casos/{caso['id']}", headers=_sesion()).json()["estado"] == "Derivado"
    assert [f["tipo"] for f in _filas(soporte, "SELECT tipo FROM bandeja_salida")] == ["CasoDerivado"]


def test_el_viajero_ve_su_caso_y_lo_marca_resuelto(soporte, contratos):
    _preferencias(soporte, AGENCIA)
    caso = _abrir(soporte).json()
    cliente = soporte.cliente

    assert cliente.get(f"/casos/{caso['id']}", headers=_sesion()).json() == caso
    assert cliente.get(f"/casos/{caso['id']}", headers=_sesion(OTRO)).status_code == 404
    assert cliente.get(f"/casos/{caso['id']}").status_code == 401

    resuelto = cliente.post(f"/casos/{caso['id']}/resolucion", headers=_sesion())
    assert resuelto.status_code == 200 and resuelto.json()["estado"] == "Resuelto"
    contratos.validar(CASO, resuelto.json())
    assert cliente.post(f"/casos/{caso['id']}/resolucion", headers=_sesion()).status_code == 409
    assert cliente.post(f"/casos/{uuid4()}/resolucion", headers=_sesion()).status_code == 404


def test_las_preferencias_cambian_o_quitan_la_agencia(soporte):
    evento = _preferencias(soporte, AGENCIA)
    soporte.consumir(evento)  # repetido: la bandeja de entrada evita el segundo efecto
    _preferencias(soporte, {"id": "agencia-norte", "nombre": "Agencia Norte"})
    assert _abrir(soporte).json()["agencia"] == "Agencia Norte"
    _preferencias(soporte, None)
    assert _abrir(soporte).status_code == 422


def test_un_cuerpo_que_no_cumple_el_contrato_responde_400(soporte):
    _preferencias(soporte, AGENCIA)
    respuesta = _abrir(soporte, {"viajeId": str(VIAJE), "motivo": "porque si"})
    assert respuesta.status_code == 400
    assert respuesta.json()["errores"][0]["campo"] == "motivo"
