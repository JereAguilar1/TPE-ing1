"""Agregado `Reserva` (ADR-0010): invariantes, estados y representación según el contrato."""

from uuid import UUID

import pytest

from ayudas import CREADA_EN, USUARIO, instante
from trotamundos.comun.contratos import ErrorDeContrato
from trotamundos.comun.modelo import Fuente, Identificador
from trotamundos.servicios.itinerary.reservas import (
    ConflictoDeFuentes,
    EstadoReserva,
    Fijado,
    ObservacionRegistrada,
    Reserva,
    ReservaInvalida,
    TransicionInvalida,
    ValorEnDisputa,
    VistaConsolidada,
)

RESERVA_CONTRATO = "openapi/comun.yaml#/components/schemas/Reserva"


def _vista(registrada: ObservacionRegistrada, **extra) -> VistaConsolidada:
    """Vista mínima armada a mano; la de verdad la calcula `fusion` (otras pruebas)."""
    segmento = registrada.observacion.segmentos[0].a_dict()
    segmento.update(id="00000000-0000-4000-8000-000000000101", orden=0, estado="confirmado")
    return VistaConsolidada(segmentos=(segmento,), cancelada=False, **extra)


# --- observaciones: una por clave, la de mayor versión (ADR-0014) ---------------------------

def test_registrar_la_misma_observacion_dos_veces_no_cambia_nada(reserva, registrada):
    observacion = registrada()

    assert reserva.registrar(observacion) is True
    assert reserva.registrar(observacion) is False
    assert reserva.observaciones == (observacion,)


def test_una_version_posterior_de_la_misma_clave_reemplaza_a_la_anterior(reserva, registrada):
    vieja, nueva = registrada(version=instante(10)), registrada(version=instante(11))

    reserva.registrar(vieja)
    assert reserva.registrar(nueva) is True
    assert reserva.observaciones == (nueva,)


def test_una_version_anterior_que_llega_tarde_se_ignora(reserva, registrada):
    vieja, nueva = registrada(version=instante(10)), registrada(version=instante(11))

    reserva.registrar(nueva)
    assert reserva.registrar(vieja) is False
    assert reserva.observaciones == (nueva,)


def test_el_empate_de_version_se_decide_por_contenido_y_no_por_llegada(registrada):
    a = registrada(cambios={"detalle.puerta": "5"})
    b = registrada(cambios={"detalle.puerta": "7"})
    resultados = []
    for orden in ((a, b), (b, a)):
        reserva = Reserva(UUID(int=1), USUARIO, CREADA_EN)
        for observacion in orden:
            reserva.registrar(observacion)
        resultados.append(reserva.observaciones)

    assert resultados[0] == resultados[1]


def test_observaciones_de_claves_distintas_conviven(reserva, registrada):
    reserva.registrar(registrada(id_de_fuente="mensaje-1"))
    reserva.registrar(registrada(fuente="proveedor", id_de_fuente="AR/ABC123"))

    assert reserva.fuentes == {Fuente.CORREO, Fuente.PROVEEDOR}


def test_la_banda_va_solo_en_las_observaciones_del_correo(registrada):
    correo = registrada()
    with pytest.raises(ReservaInvalida):
        ObservacionRegistrada(correo.observacion, banda=None)
    proveedor = registrada(fuente="proveedor")
    with pytest.raises(ReservaInvalida):
        ObservacionRegistrada(proveedor.observacion, banda=correo.banda)


# --- validación contra el contrato y el descriptor del tipo (ADR-0011) ---------------------

def test_no_se_registra_una_observacion_cuyo_detalle_no_valida(reserva, registrada):
    with pytest.raises(ErrorDeContrato):
        reserva.registrar(registrada(cambios={"detalle.clase": "turista"}))  # fuera del enum
    with pytest.raises(ErrorDeContrato):
        reserva.registrar(registrada(cambios={"detalle.anden": "4"}))  # no existe en el tipo
    assert reserva.observaciones == ()


def test_la_vista_no_acepta_un_detalle_que_no_valida(reserva, registrada):
    observacion = registrada()
    reserva.registrar(observacion)
    vista = _vista(observacion)
    invalido = {**vista.segmentos[0], "detalle": {"aerolinea": "AR"}}  # falta numeroDeVuelo

    with pytest.raises(ReservaInvalida):
        reserva.establecer_vista(VistaConsolidada((invalido,), cancelada=False))


# --- vista, versión e invariantes ----------------------------------------------------------

def test_una_reserva_tiene_al_menos_un_segmento(reserva):
    with pytest.raises(ReservaInvalida):
        reserva.establecer_vista(VistaConsolidada(segmentos=(), cancelada=False))


def test_la_version_sube_una_vez_por_cambio_aplicado(reserva, registrada):
    observacion = registrada()
    reserva.registrar(observacion)
    reserva.establecer_vista(_vista(observacion))
    assert reserva.version == 1

    reserva.registrar(observacion)  # repetida: no es un cambio
    reserva.establecer_vista(_vista(observacion))
    assert reserva.version == 1

    reserva.agregar_identificadores({Identificador("agencia:despegar", "ORD-9")})
    reserva.establecer_vista(_vista(observacion))
    assert reserva.version == 2


def test_solo_se_fijan_campos_con_ruta_valida():
    Fijado("segmentos[0].inicio.instante", "2026-12-01T14:00:00Z", instante(12))
    Fijado("cancelada", False, instante(12))
    Fijado("segmentos[0].detalle.andén-2", "4", instante(12))  # claves de un descriptor futuro
    for campo in ("segmentos[-1].operador", "segmentos[0]", "estado", "segmentos[01].operador"):
        with pytest.raises(ReservaInvalida):
            Fijado(campo, "x", instante(12))
    with pytest.raises(ReservaInvalida):
        Fijado("cancelada", "no", instante(12))


# --- estados (iteración 2 §5.2, ADR-0015) --------------------------------------------------

def test_la_banda_media_entra_por_confirmar(reserva, registrada):
    reserva.registrar(registrada(banda="media"))
    assert reserva.estado == EstadoReserva.POR_CONFIRMAR


@pytest.mark.parametrize("otra", [
    {"banda": "alta", "id_de_fuente": "mensaje-2"},
    {"fuente": "proveedor"},
    {"fuente": "manual"},
])
def test_una_observacion_confiable_confirma_la_reserva(reserva, registrada, otra):
    reserva.registrar(registrada(banda="media"))
    reserva.registrar(registrada(**otra))
    assert reserva.estado == EstadoReserva.CONFIRMADA


def test_el_usuario_confirma_o_descarta_solo_lo_que_esta_por_confirmar(registrada):
    confirmada = Reserva(UUID(int=1), USUARIO, CREADA_EN)
    confirmada.registrar(registrada(banda="media"))
    confirmada.confirmar()
    assert confirmada.estado == EstadoReserva.CONFIRMADA
    with pytest.raises(TransicionInvalida):
        confirmada.descartar()

    descartada = Reserva(UUID(int=2), USUARIO, CREADA_EN)
    descartada.registrar(registrada(banda="media"))
    descartada.descartar()
    assert descartada.estado == EstadoReserva.DESCARTADA
    with pytest.raises(TransicionInvalida):
        descartada.confirmar()


@pytest.mark.parametrize("banda", ["alta", "media"])
def test_la_baja_manual_descarta_la_reserva_desde_cualquier_estado(reserva, registrada, banda):
    observacion = registrada(banda=banda)
    reserva.registrar(observacion)
    reserva.establecer_vista(_vista(observacion))
    version = reserva.version

    reserva.dar_de_baja()
    reserva.establecer_vista(reserva.vista)

    assert reserva.estado == EstadoReserva.DESCARTADA and reserva.version == version + 1
    with pytest.raises(TransicionInvalida):
        reserva.dar_de_baja()


def test_solo_un_alta_manual_revive_una_reserva_dada_de_baja(reserva, registrada):
    observacion = registrada()
    reserva.registrar(observacion)
    reserva.establecer_vista(_vista(observacion))
    reserva.dar_de_baja()

    reserva.registrar(registrada(id_de_fuente="mensaje-2", version=instante(12)))
    assert reserva.estado == EstadoReserva.DESCARTADA

    reserva.registrar(registrada(fuente="manual", id_de_fuente="alta/1", version=instante(13)))
    assert reserva.estado == EstadoReserva.CONFIRMADA


def test_la_vista_cancelada_lleva_la_reserva_a_cancelada(reserva, registrada):
    observacion = registrada()
    reserva.registrar(observacion)
    reserva.establecer_vista(VistaConsolidada(_vista(observacion).segmentos, cancelada=True))
    assert reserva.estado == EstadoReserva.CANCELADA


def test_datos_de_banda_media_no_cancelan_una_reserva_por_confirmar(reserva, registrada):
    # Iteración 2 §5.2: solo una `Confirmada` pasa a `Cancelada`; la banda media no dispara
    # avisos críticos (ADR-0015).
    observacion = registrada(banda="media", cancelada=True)
    reserva.registrar(observacion)
    reserva.establecer_vista(VistaConsolidada(_vista(observacion).segmentos, cancelada=True))
    assert reserva.estado == EstadoReserva.POR_CONFIRMAR

    reserva.confirmar()
    assert reserva.estado == EstadoReserva.CANCELADA


# --- resolución de conflictos: siempre es una nueva fijación (ADR-0013) --------------------

def _con_conflicto(reserva: Reserva, registrada) -> ConflictoDeFuentes:
    observacion = registrada()
    conflicto = ConflictoDeFuentes(UUID(int=7), "segmentos[0].detalle.puerta", (
        ValorEnDisputa(Fuente.MANUAL, "12", instante(11)),
        ValorEnDisputa(Fuente.PROVEEDOR, "15", instante(12)),
    ))
    reserva.registrar(observacion)
    reserva.fijar(Fijado(conflicto.campo, "12", instante(11)))
    reserva.establecer_vista(_vista(observacion, conflictos=(conflicto,)))
    return conflicto


def test_mantener_el_fijado_lo_renueva_con_el_mismo_valor(reserva, registrada):
    conflicto = _con_conflicto(reserva, registrada)
    reserva.resolver_conflicto(conflicto.id, aceptar=None, ahora=instante(13))
    assert reserva.fijados[conflicto.campo] == Fijado(conflicto.campo, "12", instante(13))


def test_aceptar_una_fuente_fija_su_valor(reserva, registrada):
    conflicto = _con_conflicto(reserva, registrada)
    reserva.resolver_conflicto(conflicto.id, aceptar=Fuente.PROVEEDOR, ahora=instante(13))
    assert reserva.fijados[conflicto.campo] == Fijado(conflicto.campo, "15", instante(13))


def test_no_se_resuelve_un_conflicto_inexistente_ni_con_una_fuente_ajena(reserva, registrada):
    conflicto = _con_conflicto(reserva, registrada)
    with pytest.raises(TransicionInvalida):
        reserva.resolver_conflicto(UUID(int=99), aceptar=None, ahora=instante(13))
    with pytest.raises(TransicionInvalida):
        reserva.resolver_conflicto(conflicto.id, aceptar=Fuente.CORREO, ahora=instante(13))


# --- unión de dos reservas (la usa la unificación por identificadores) ---------------------

def test_unir_absorbe_observaciones_fijados_e_identificadores(registrada):
    vieja = Reserva(UUID(int=1), USUARIO, CREADA_EN)
    vieja.registrar(registrada(id_de_fuente="mensaje-1"))
    vieja.agregar_identificadores({Identificador("aerolinea:AR", "ABC123")})
    nueva = Reserva(UUID(int=2), USUARIO, CREADA_EN)
    nueva.registrar(registrada(id_de_fuente="mensaje-2", identificadores=(("agencia:x", "9"),)))
    nueva.agregar_identificadores({Identificador("agencia:x", "9")})
    nueva.fijar(Fijado("segmentos[0].detalle.asiento", "3A", instante(11)))

    vieja.unir(nueva)

    assert {o.clave for o in vieja.observaciones} == {(Fuente.CORREO, "mensaje-1"),
                                                      (Fuente.CORREO, "mensaje-2")}
    assert vieja.identificadores == {Identificador("aerolinea:AR", "ABC123"),
                                     Identificador("agencia:x", "9")}
    assert "segmentos[0].detalle.asiento" in vieja.fijados


# --- contrato -----------------------------------------------------------------------------

def test_la_representacion_cumple_el_esquema_reserva(contratos, reserva, registrada):
    conflicto = _con_conflicto(reserva, registrada)
    reserva.agregar_identificadores({Identificador("aerolinea:AR", "ABC123")})
    reserva.establecer_vista(reserva.vista)

    datos = reserva.a_dict()

    contratos.validar(RESERVA_CONTRATO, datos)
    assert datos["estado"] == "Confirmada" and datos["banda"] == "alta"
    assert datos["conflictosAbiertos"] == [conflicto.a_dict()]
