"""`notification` (RF-10, iteración 2 §5.7): reglas, canales, silencio, correlación y coalescencia.

Las reglas puras corren siempre; lo que usa PostgreSQL se saltea sin base.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.test_contratos import reserva_valida
from trotamundos.comun.config import Configuracion
from trotamundos.comun.eventos import Evento
from trotamundos.comun.persistencia import conectar
from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.notification import avisos, preferencias, reglas
from trotamundos.servicios.notification.complementos.canales_simulados import CanalesSimulados
from trotamundos.servicios.notification.servicio import Notification

USUARIO = "00000000-0000-4000-8000-0000000000e1"
OTRO = "00000000-0000-4000-8000-0000000000e2"
VIAJE = "00000000-0000-4000-8000-0000000000a1"
# 15:00 UTC = 12:00 en Buenos Aires (fuera de las horas de silencio); 03:00 UTC = 00:00 (dentro).
MEDIODIA = datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc)
MEDIANOCHE = datetime(2026, 12, 2, 3, 0, tzinfo=timezone.utc)


def _reserva(**cambios) -> dict:
    reserva = reserva_valida()
    reserva["viajeId"] = VIAJE
    reserva.update(cambios)
    return reserva


def actualizada(cambios: list[dict], *, creada: bool = False, causa: str | None = None,
                usuario: str = USUARIO, **reserva) -> Evento:
    return Evento.nuevo("ReservaActualizada", {"reserva": _reserva(**reserva), "creada": creada,
                                               "cambios": cambios},
                        productor="itinerary", usuario_id=usuario, region="AM", id_de_causa=causa)


def disrupcion(severidad: str, *afectados: str, id_: str = "disrupcion-1") -> Evento:
    return Evento.nuevo("DisrupcionDetectada", {
        "disrupcionId": id_, "proveedor": "aerolinea:AR", "severidad": severidad,
        "descripcion": "Demora", "afectados": [
            {"usuarioId": u, "reservaIds": [reserva_valida()["id"]]} for u in afectados]},
        productor="provider-sync", usuario_id=afectados[0], region="AM", id_de_causa=id_)


HORARIO = {"campo": "segmentos[0].inicio.instante", "anterior": "2026-12-01T13:00:00Z",
           "nuevo": "2026-12-01T14:00:00Z", "fuente": "proveedor"}


# --- reglas (sin base) --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registro():
    return registro_por_omision()


@pytest.mark.parametrize(("cambio", "severidad"), [
    (HORARIO, "critica"),                                                  # 60 min ≥ umbral de 15
    ({**HORARIO, "nuevo": "2026-12-01T13:10:00Z"}, "informativa"),        # 10 min < 15
    ({"campo": "segmentos[0].detalle.puerta", "nuevo": "12", "fuente": "proveedor"}, "critica"),
    ({"campo": "segmentos[0].detalle.asiento", "nuevo": "3A", "fuente": "correo"}, "informativa"),
    ({"campo": "estado", "anterior": "Confirmada", "nuevo": "Cancelada", "fuente": "proveedor"},
     "critica"),
])
def test_la_severidad_sale_del_descriptor_del_tipo(registro, cambio, severidad):
    (aviso,) = reglas.avisos_de(actualizada([cambio]), registro)
    assert (aviso.severidad, aviso.viaje_id, aviso.usuario_id) == (severidad, VIAJE, USUARIO)


def test_lo_que_cambia_el_propio_viajero_no_se_le_avisa(registro):
    assert reglas.avisos_de(actualizada([{**HORARIO, "fuente": "manual"}]), registro) == []
    cancelada = Evento.nuevo("ReservaCancelada", {
        "reservaId": str(uuid4()), "version": 2, "fuente": "manual",
        "canceladaEn": "2026-12-01T10:00:00Z"}, productor="itinerary", usuario_id=USUARIO)
    assert reglas.avisos_de(cancelada, registro) == []


def test_reserva_nueva_o_por_confirmar_es_informativa(registro):
    (nueva,) = reglas.avisos_de(actualizada([], creada=True), registro)
    (dudosa,) = reglas.avisos_de(actualizada([], creada=True, estado="PorConfirmar"), registro)
    assert (nueva.severidad, nueva.motivo) == ("informativa", "reservaAgregada")
    assert (dudosa.severidad, dudosa.motivo) == ("informativa", "reservaPorConfirmar")


def test_disrupcion_avisa_a_cada_afectado_con_su_causa(registro):
    altos = reglas.avisos_de(disrupcion("alta", USUARIO, OTRO), registro)
    assert [(a.usuario_id, a.severidad, a.id_de_causa) for a in altos] == [
        (USUARIO, "critica", "disrupcion-1"), (OTRO, "critica", "disrupcion-1")]
    (medio,) = reglas.avisos_de(disrupcion("media", USUARIO), registro)
    assert medio.severidad == "informativa"


def test_avisos_administrativos(registro):
    buzon = {"buzonId": str(uuid4()), "estadoAnterior": "Activo"}
    reautorizar = Evento.nuevo("EstadoDeBuzonCambiado", {
        **buzon, "estadoNuevo": "RequiereReautorizacion"}, productor="identity-access",
        usuario_id=USUARIO)
    desconectado = Evento.nuevo("EstadoDeBuzonCambiado", {
        **buzon, "estadoNuevo": "Desconectado"}, productor="identity-access", usuario_id=USUARIO)
    assert [a.severidad for a in reglas.avisos_de(reautorizar, registro)] == ["administrativa"]
    assert reglas.avisos_de(desconectado, registro) == []


def _prefs(push=True, correo=True, desde="22:00", hasta="07:00"):
    return {"zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM",
            "canales": {"push": push, "correo": correo},
            "horasDeSilencio": {"desde": desde, "hasta": hasta}}


def test_canales_por_severidad_y_horas_de_silencio():
    assert avisos.canales("critica", _prefs(), MEDIODIA) == ("interno", "push")
    assert avisos.canales("critica", _prefs(push=False), MEDIODIA) == ("interno", "correo")
    assert avisos.canales("critica", _prefs(), MEDIANOCHE) == ("interno", "push")  # la ignora
    assert avisos.canales("informativa", _prefs(), MEDIODIA) == ("interno", "push")
    assert avisos.canales("informativa", _prefs(push=False), MEDIODIA) == ("interno",)
    assert avisos.canales("informativa", _prefs(), MEDIANOCHE) == ("interno",)
    assert avisos.canales("administrativa", _prefs(), MEDIODIA) == ("interno", "correo")
    assert avisos.canales("administrativa", _prefs(), MEDIANOCHE) == ("interno",)
    assert not avisos.en_silencio(_prefs(desde="08:00", hasta="09:00"), MEDIODIA)
    assert avisos.en_silencio(_prefs(desde="11:00", hasta="13:00"), MEDIODIA)


# --- el servicio, contra PostgreSQL -------------------------------------------------------------

@pytest.fixture
def notification(dsn, esquema, contratos):
    reloj = {"ahora": MEDIODIA}
    configuracion = dataclasses.replace(Configuracion.desde_entorno(), dsn_postgres=dsn, broker="",
                                        intervalo_tareas_s=0)
    servicio = Notification(configuracion, esquema=esquema, contratos=contratos,
                            canales_externos=CanalesSimulados(), reloj=lambda: reloj["ahora"])
    servicio.crear_esquema()
    servicio.reloj = reloj
    servicio.bd = (dsn, esquema)
    return servicio


def _emitidas(servicio) -> list[dict]:
    with conectar(*servicio.bd) as conexion:
        return [f["carga"] for f in conexion.execute(
            "SELECT carga FROM bandeja_salida WHERE tipo = 'NotificacionEmitida' "
            "ORDER BY creado_en").fetchall()]


def test_un_cambio_critico_sale_de_inmediato_y_queda_en_el_canal_interno(notification):
    evento = actualizada([HORARIO])
    notification.consumir(evento)
    notification.consumir(evento)  # repetido: la bandeja de entrada lo descarta
    (aviso,) = notification.bandeja(USUARIO)
    assert (aviso["severidad"], aviso["canales"], aviso["emitido_en"]) == (
        "critica", ["interno", "push"], MEDIODIA)
    (carga,) = _emitidas(notification)
    assert carga == {"notificacionId": str(aviso["aviso_id"]), "severidad": "critica",
                     "canales": ["interno", "push"], "eventosAgrupados": 1, "viajeId": VIAJE}
    assert [(c, u) for c, u, _ in notification.canales_externos.entregados] == [("push", USUARIO)]


def test_coalescencia_la_primera_sale_y_las_siguientes_se_agrupan_30_s(notification):
    puerta = {"campo": "segmentos[0].detalle.puerta", "nuevo": "12", "fuente": "proveedor"}
    notification.consumir(actualizada([HORARIO]))
    for segundos in (5, 10, 20):
        notification.reloj["ahora"] = MEDIODIA + timedelta(seconds=segundos)
        notification.consumir(actualizada([puerta]))
    assert len(_emitidas(notification)) == 1
    notification.reloj["ahora"] = MEDIODIA + timedelta(seconds=29)
    assert notification.emitir_agrupados() == 0
    notification.reloj["ahora"] = MEDIODIA + timedelta(seconds=30)
    assert notification.emitir_agrupados() == 1
    primera, agrupada = _emitidas(notification)
    assert (primera["eventosAgrupados"], agrupada["eventosAgrupados"]) == (1, 3)
    assert len(notification.bandeja(USUARIO)) == 2


def test_disrupcion_y_el_cambio_que_provoca_dan_un_solo_aviso(notification):
    notification.consumir(disrupcion("alta", USUARIO, OTRO))
    notification.consumir(actualizada([HORARIO], causa="disrupcion-1"))
    notification.consumir(actualizada([HORARIO], causa="disrupcion-1", usuario=OTRO))
    for usuario in (USUARIO, OTRO):
        (aviso,) = notification.bandeja(usuario)
        assert (aviso["id_de_causa"], aviso["eventos_agrupados"]) == ("disrupcion-1", 2)
    assert len(_emitidas(notification)) == 2  # uno por afectado


def test_las_preferencias_locales_eligen_los_canales_y_respetan_el_silencio(notification):
    preferencias_evento = Evento.nuevo("PreferenciasActualizadas", {"preferencias": {
        "idioma": "es-AR", "zonaHoraria": "America/Argentina/Buenos_Aires", "region": "AM",
        "canales": {"push": False, "correo": True}}}, productor="preferences", usuario_id=USUARIO)
    notification.consumir(preferencias_evento)
    notification.consumir(actualizada([HORARIO]))
    assert notification.bandeja(USUARIO)[0]["canales"] == ["interno", "correo"]

    notification.reloj["ahora"] = MEDIANOCHE
    extraccion = Evento.nuevo("ExtraccionNoReconocida", {
        "buzonId": str(uuid4()), "idDeMensaje": "m-1", "motivo": "formatoDesconocido",
        "remitente": "reservas@ejemplo.com", "fechaCorreo": "2026-12-02T02:00:00Z",
        "huellaDeFormato": "abc"}, productor="booking-extraction", usuario_id=USUARIO)
    notification.consumir(extraccion)
    assert notification.bandeja(USUARIO)[0]["canales"] == ["interno"]  # en silencio
    with conectar(*notification.bd) as conexion:
        assert preferencias.de_usuario(conexion, OTRO)["canales"] == {"push": True, "correo": True}


def test_preferencias_mas_viejas_no_pisan_las_nuevas(notification):
    def evento(push: bool, ocurrido: str) -> Evento:
        e = Evento.nuevo("PreferenciasActualizadas", {"preferencias": {
            "idioma": "es-AR", "zonaHoraria": "UTC", "region": "AM", "canales": {"push": push}}},
            productor="preferences", usuario_id=USUARIO)
        return dataclasses.replace(e, sobre={**e.sobre, "ocurridoEn": ocurrido})

    notification.consumir(evento(False, "2026-12-01T12:00:00Z"))
    notification.consumir(evento(True, "2026-12-01T11:00:00Z"))  # llegó tarde
    with conectar(*notification.bd) as conexion:
        assert preferencias.de_usuario(conexion, USUARIO)["canales"]["push"] is False


def test_un_canal_externo_caido_no_frena_el_aviso(notification):
    class Caido:
        def enviar(self, *_):
            raise ConnectionError("sin red")

    notification.canales_externos = Caido()
    notification.consumir(actualizada([HORARIO]))
    assert len(notification.bandeja(USUARIO)) == 1 and len(_emitidas(notification)) == 1


def test_evento_ajeno_o_invalido_no_deja_nada(notification):
    from trotamundos.comun.contratos import ErrorDeContrato
    ajeno = Evento.nuevo("ViajeArchivado", {"viajeId": VIAJE, "archivadoEn": "2026-12-01T00:00:00Z",
                                            "motivo": "automatico"},
                         productor="itinerary", usuario_id=USUARIO)
    with pytest.raises(ErrorDeContrato):
        notification.consumir(ajeno)
    invalido = actualizada([HORARIO])
    invalido = dataclasses.replace(invalido, carga={**copy.deepcopy(invalido.carga), "cambios": 3})
    with pytest.raises(ErrorDeContrato):
        notification.consumir(invalido)
    assert notification.bandeja(USUARIO) == []
