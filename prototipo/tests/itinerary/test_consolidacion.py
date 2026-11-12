"""Consolidación (ADR-0013): un caso por cada fila de la tabla de reglas, más cambios y contrato."""

from uuid import UUID

from ayudas import CREADA_EN, USUARIO, instante
from trotamundos.comun.modelo import Fuente
from trotamundos.servicios.itinerary.fusion.consolidacion import reconsolidar
from trotamundos.servicios.itinerary.reservas import EstadoReserva, Fijado, Reserva

RESERVA_CONTRATO = "openapi/comun.yaml#/components/schemas/Reserva"
PUERTA = "segmentos[0].detalle.puerta"
SALIDA = "segmentos[0].inicio.instante"


def _consolidada(*observaciones, fijados=()) -> Reserva:
    reserva = Reserva(UUID(int=1), USUARIO, CREADA_EN)
    for observacion in observaciones:
        reserva.registrar(observacion)
    for fijado in fijados:
        reserva.fijar(fijado)
    reconsolidar(reserva)
    return reserva


def _valor(reserva: Reserva, ruta: str):
    segmento = reserva.vista.segmentos[0]
    for parte in ruta.removeprefix("segmentos[0].").split("."):
        segmento = segmento.get(parte) if isinstance(segmento, dict) else None
    return segmento


# --- dos versiones de la misma fuente: gana la de mayor versión de la fuente ---------------

def test_gana_la_version_de_la_fuente_y_no_la_que_llego_ultimo(registrada):
    vieja = registrada(id_de_fuente="aerolinea", version=instante(10), cambios={"detalle.puerta": "5"})
    nueva = registrada(id_de_fuente="agencia", version=instante(11), cambios={"detalle.puerta": "7"})

    assert _valor(_consolidada(vieja, nueva), PUERTA) == "7"
    assert _valor(_consolidada(nueva, vieja), PUERTA) == "7"


def test_la_version_vigente_reemplaza_entera_a_la_anterior_de_su_fuente(registrada):
    # Solo cuenta la vigente de cada fuente, que es la que conserva la compactación (ADR-0012,
    # ADR-0023): un campo que la versión nueva ya no informa no se completa con la vieja.
    vieja = registrada(id_de_fuente="aerolinea", version=instante(10), cambios={"detalle.puerta": "5"})
    nueva = registrada(id_de_fuente="agencia", version=instante(11))

    assert _valor(_consolidada(vieja, nueva), PUERTA) is None


def test_un_correo_de_banda_media_no_cambia_una_reserva_confirmada(registrada):
    # ADR-0015: ningún dato dudoso entra como confirmado.
    reserva = _consolidada(registrada(id_de_fuente="m1", version=instante(10),
                                      cambios={"detalle.puerta": "5"}))
    reserva.registrar(registrada(id_de_fuente="m2", version=instante(11), banda="media",
                                 identificadores=(("agencia:x", "9"),),
                                 cambios={"detalle.puerta": "7"}))
    resultado = reconsolidar(reserva)

    assert _valor(reserva, PUERTA) == "5" and resultado.cambios == ()
    assert reserva.estado == EstadoReserva.CONFIRMADA


def test_sin_confirmacion_la_banda_media_si_da_los_valores(registrada):
    reserva = _consolidada(registrada(banda="media", cambios={"detalle.puerta": "7"}))
    assert _valor(reserva, PUERTA) == "7" and reserva.estado == EstadoReserva.POR_CONFIRMAR


# --- proveedor frente a correo -------------------------------------------------------------

def test_el_proveedor_gana_en_los_hechos_operativos_y_el_correo_completa(registrada):
    correo = registrada(version=instante(12), cambios={"detalle.asiento": "3A",
                                                       "detalle.puerta": "5"})
    proveedor = registrada(fuente="proveedor", id_de_fuente="AR/ABC123", version=instante(10),
                           cambios={"inicio.instante": "2026-12-01T14:30:00Z",
                                    "detalle.puerta": "9"})

    reserva = _consolidada(correo, proveedor)

    assert _valor(reserva, SALIDA) == "2026-12-01T14:30:00Z"
    assert _valor(reserva, PUERTA) == "9"
    assert _valor(reserva, "segmentos[0].detalle.asiento") == "3A"
    assert reserva.vista.origen[SALIDA] == Fuente.PROVEEDOR
    assert reserva.vista.origen["segmentos[0].detalle.asiento"] == Fuente.CORREO


def test_una_observacion_con_otra_estructura_no_mezcla_tramos(registrada, segmento_de_tren):
    # El proveedor informa dos tramos; el correo, uno: el correo no aporta valores al primero.
    proveedor = registrada(fuente="proveedor")
    proveedor_dos_tramos = registrada(
        fuente="proveedor", segmentos=[proveedor.observacion.segmentos[0].a_dict(), segmento_de_tren])
    correo = registrada(cambios={"detalle.asiento": "3A"})

    reserva = _consolidada(correo, proveedor_dos_tramos)

    assert len(reserva.vista.segmentos) == 2
    assert _valor(reserva, "segmentos[0].detalle.asiento") is None


# --- reserva solo manual y alta manual frente a fuentes automáticas ------------------------

def test_en_una_reserva_solo_manual_el_usuario_es_la_autoridad(registrada):
    manual = registrada(fuente="manual", id_de_fuente="alta-1", cambios={"detalle.puerta": "4"})
    reserva = _consolidada(manual)
    assert _valor(reserva, PUERTA) == "4"
    assert reserva.vista.origen[PUERTA] == Fuente.MANUAL


def test_el_alta_manual_no_fija_campos_y_una_fuente_automatica_la_completa(registrada):
    manual = registrada(fuente="manual", id_de_fuente="alta-1", version=instante(12),
                        cambios={"detalle.puerta": "4"})
    correo = registrada(version=instante(10), cambios={"detalle.puerta": "6"})

    reserva = _consolidada(manual, correo)

    assert _valor(reserva, PUERTA) == "6"
    assert reserva.vista.conflictos == ()


# --- edición manual frente a fuente automática: el campo queda fijado ----------------------

def test_el_campo_fijado_conserva_el_valor_del_usuario(registrada):
    proveedor = registrada(fuente="proveedor", version=instante(10), cambios={"detalle.puerta": "15"})
    reserva = _consolidada(proveedor, fijados=[Fijado(PUERTA, "12", instante(11))])

    assert _valor(reserva, PUERTA) == "12"
    assert reserva.vista.segmentos[0]["fijados"] == ["detalle.puerta"]
    assert reserva.vista.conflictos == ()  # el valor del proveedor es anterior al fijado


def test_un_valor_distinto_y_posterior_al_fijado_abre_un_conflicto(registrada):
    proveedor = registrada(fuente="proveedor", version=instante(12), cambios={"detalle.puerta": "15"})
    reserva = _consolidada(proveedor, fijados=[Fijado(PUERTA, "12", instante(11))])

    assert _valor(reserva, PUERTA) == "12"
    [conflicto] = reserva.vista.conflictos
    assert conflicto.campo == PUERTA
    assert [(v.fuente, v.valor) for v in conflicto.valores] == [(Fuente.MANUAL, "12"),
                                                                (Fuente.PROVEEDOR, "15")]


def test_un_valor_posterior_igual_al_fijado_no_abre_conflicto(registrada):
    proveedor = registrada(fuente="proveedor", version=instante(12), cambios={"detalle.puerta": "12"})
    reserva = _consolidada(proveedor, fijados=[Fijado(PUERTA, "12", instante(11))])
    assert reserva.vista.conflictos == ()


def test_resolver_el_conflicto_lo_cierra_y_un_valor_nuevo_abre_otro(registrada):
    reserva = _consolidada(
        registrada(fuente="proveedor", version=instante(12), cambios={"detalle.puerta": "15"}),
        fijados=[Fijado(PUERTA, "12", instante(11))])
    [primero] = reserva.vista.conflictos

    reserva.resolver_conflicto(primero.id, aceptar=Fuente.PROVEEDOR, ahora=instante(13))
    reconsolidar(reserva)
    assert _valor(reserva, PUERTA) == "15" and reserva.vista.conflictos == ()

    reserva.registrar(registrada(fuente="proveedor", version=instante(14),
                                 cambios={"detalle.puerta": "18"}))
    resultado = reconsolidar(reserva)
    [segundo] = resultado.conflictos_nuevos
    assert segundo.id != primero.id and reserva.vista.conflictos == (segundo,)


def test_un_fijado_del_detalle_no_se_aplica_si_el_segmento_cambio_de_tipo(registrada):
    correo = registrada(version=instante(10))
    hotel = {**correo.observacion.segmentos[0].a_dict(), "tipo": "hotel",
             "detalle": {"habitaciones": 1, "huespedes": 2}}
    proveedor = registrada(fuente="proveedor", version=instante(12), segmentos=[hotel])

    reserva = _consolidada(correo, proveedor, fijados=[Fijado(PUERTA, "12", instante(11))])

    assert reserva.vista.segmentos[0]["detalle"] == {"habitaciones": 1, "huespedes": 2}
    assert "fijados" not in reserva.vista.segmentos[0] and reserva.vista.conflictos == ()


# --- cancelación del proveedor: prevalece siempre -------------------------------------------

def test_la_cancelacion_del_proveedor_prevalece_sobre_un_correo_posterior(registrada):
    proveedor = registrada(fuente="proveedor", version=instante(10), cancelada=True)
    correo = registrada(version=instante(12))

    reserva = _consolidada(correo, proveedor)

    assert reserva.estado == EstadoReserva.CANCELADA
    assert {s["estado"] for s in reserva.vista.segmentos} == {"cancelado"}


def test_el_usuario_reactiva_y_una_cancelacion_posterior_vuelve_a_prevalecer(registrada):
    cancelada = registrada(fuente="proveedor", version=instante(10), cancelada=True)
    reactivada = _consolidada(cancelada, fijados=[Fijado("cancelada", False, instante(11))])
    assert reactivada.estado == EstadoReserva.CONFIRMADA

    reactivada.registrar(registrada(fuente="proveedor", version=instante(12), cancelada=True))
    resultado = reconsolidar(reactivada)

    assert reactivada.estado == EstadoReserva.CANCELADA
    assert resultado.cancelada_ahora and resultado.conflictos_nuevos == ()


def test_la_cancelacion_se_informa_por_el_cambio_de_estado(registrada):
    # Una reserva por confirmar no pasa a `Cancelada` por un correo de banda media (ADR-0015).
    media = _consolidada(registrada(banda="media", version=instante(10)))
    media.registrar(registrada(banda="media", version=instante(11), cancelada=True))
    assert not reconsolidar(media).cancelada_ahora
    assert media.estado == EstadoReserva.POR_CONFIRMAR

    confirmada = _consolidada(registrada(version=instante(10)))
    confirmada.registrar(registrada(version=instante(11), cancelada=True))
    resultado = reconsolidar(confirmada)
    assert resultado.cancelada_ahora
    assert (resultado.estado_anterior, resultado.estado) == (EstadoReserva.CONFIRMADA,
                                                             EstadoReserva.CANCELADA)


# --- cambios, versión y contrato ------------------------------------------------------------

def test_reconsolidar_informa_los_cambios_campo_por_campo(registrada):
    reserva = _consolidada(registrada(version=instante(10)))
    assert reserva.version == 1

    resultado = reconsolidar(reserva)
    assert resultado.cambios == () and reserva.version == 1  # nada cambió

    reserva.registrar(registrada(fuente="proveedor", version=instante(11),
                                 cambios={"inicio.instante": "2026-12-01T14:30:00Z"}))
    resultado = reconsolidar(reserva)

    assert [c.a_dict() for c in resultado.cambios] == [{
        "campo": SALIDA, "anterior": "2026-12-01T13:00:00Z", "nuevo": "2026-12-01T14:30:00Z",
        "fuente": "proveedor"}]
    assert reserva.version == 2


def test_la_reserva_consolidada_cumple_el_contrato(contratos, registrada):
    reserva = _consolidada(
        registrada(), registrada(fuente="proveedor", version=instante(12),
                                 cambios={"detalle.puerta": "15"}),
        fijados=[Fijado(PUERTA, "12", instante(11))])

    contratos.validar(RESERVA_CONTRATO, reserva.a_dict())


def test_los_ids_de_segmentos_y_conflictos_no_dependen_del_orden(registrada):
    observaciones = [registrada(), registrada(fuente="proveedor", version=instante(12),
                                              cambios={"detalle.puerta": "15"})]
    fijado = Fijado(PUERTA, "12", instante(11))

    una = _consolidada(*observaciones, fijados=[fijado])
    otra = _consolidada(*reversed(observaciones), fijados=[fijado])

    assert una.vista.conflictos and una.a_dict() == otra.a_dict()
