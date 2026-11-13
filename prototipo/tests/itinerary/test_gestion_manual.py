"""Gestión manual de reservas (RF-06, ADR-0013, ADR-0015) y sus eventos de dominio (AsyncAPI)."""

import copy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from ayudas import USUARIO, instante
from repositorio_en_memoria import RepositorioEnMemoria
from trotamundos.comun.eventos import Causa
from trotamundos.comun.modelo import Fuente
from trotamundos.comun.tipos_de_segmento import registro_por_omision
from trotamundos.servicios.itinerary import gestion_manual as gm
from trotamundos.servicios.itinerary.fusion.eventos import eventos_del_cambio
from trotamundos.servicios.itinerary.fusion.identidad import ingerir, persistir
from trotamundos.servicios.itinerary.reservas import EstadoReserva

PUERTA = "segmentos[0].detalle.puerta"
CAUSA = Causa(region="AM", traceparent="00-abc-def-01")


class Reloj:
    def __init__(self):
        self.ahora = instante(20)

    def avanzar(self):
        self.ahora += timedelta(minutes=1)
        return self.ahora


@pytest.fixture
def entorno():
    repositorio, reloj = RepositorioEnMemoria(), Reloj()

    def contexto() -> gm.Contexto:
        return gm.Contexto(repositorio, registro_por_omision(), USUARIO, reloj.avanzar(), CAUSA)

    contexto.repositorio = repositorio
    return contexto


@pytest.fixture
def alta(observacion):
    """Cuerpo `ReservaNueva` con el vuelo de `tests/conftest.py`."""
    segmento = copy.deepcopy(observacion["segmentos"][0])
    del segmento["versionTipo"]
    return {"identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
            "segmentos": [segmento]}


def _tipos(resultado: gm.Resultado) -> list[str]:
    return [e.tipo for e in resultado.eventos]


@pytest.fixture(autouse=True)
def eventos_validos(contratos, monkeypatch):
    """Todo evento que produce un comando cumple el contrato AsyncAPI."""
    original = gm.eventos_del_cambio

    def validando(*args, **kwargs):
        eventos = original(*args, **kwargs)
        for evento in eventos:
            evento.validar(contratos)
        return eventos

    monkeypatch.setattr(gm, "eventos_del_cambio", validando)


# --- alta ----------------------------------------------------------------------------------

def test_el_alta_crea_una_reserva_confirmada_de_fuente_manual(entorno, alta, contratos):
    resultado = gm.crear(entorno(), alta, uuid4())

    reserva = resultado.reserva.a_dict()
    assert reserva["estado"] == "Confirmada" and reserva["fuentes"] == ["manual"]
    assert reserva["segmentos"][0]["versionTipo"] == 1  # la vigente del registro
    [evento] = resultado.eventos
    assert evento.tipo == "ReservaActualizada" and evento.carga["creada"] is True
    assert evento.sobre["productor"] == "itinerary" and evento.sobre["regionOrigen"] == "AM"
    assert evento.sobre["traceparent"] == CAUSA.traceparent
    contratos.validar("openapi/comun.yaml#/components/schemas/ResultadoComandoReserva",
                      resultado.cuerpo(version_usuario=1))


def test_el_alta_rechaza_un_tipo_no_registrado_o_un_detalle_invalido(entorno, alta):
    alta["segmentos"][0]["tipo"] = "teletransporte"
    with pytest.raises(gm.SolicitudInvalida):
        gm.crear(entorno(), alta, uuid4())

    alta["segmentos"][0].update(tipo="vuelo", detalle={"aerolinea": "AR"})  # falta numeroDeVuelo
    with pytest.raises(gm.SolicitudInvalida) as error:
        gm.crear(entorno(), alta, uuid4())
    assert error.value.errores and "segmentos[0].detalle" in error.value.errores[0]["campo"]
    assert entorno.repositorio.reservas == {}


def test_un_alta_con_un_identificador_conocido_se_agrega_a_esa_reserva(entorno, alta, registrada):
    ctx = entorno()
    automatica = ingerir(ctx.repositorio, USUARIO, registrada(), ctx.ahora)
    persistir(ctx.repositorio, automatica)

    resultado = gm.crear(entorno(), alta, uuid4())

    assert resultado.reserva.id == automatica.reserva.id
    assert resultado.reserva.a_dict()["fuentes"] == ["correo", "manual"]
    assert resultado.eventos[0].carga["creada"] is False


def test_un_alta_sobre_una_reserva_dada_de_baja_la_vuelve_a_mostrar(entorno, alta):
    reserva_id = gm.crear(entorno(), alta, uuid4()).reserva.id
    gm.dar_de_baja(entorno(), reserva_id)

    resultado = gm.crear(entorno(), alta, uuid4())

    assert resultado.reserva.id == reserva_id
    assert resultado.reserva.estado == EstadoReserva.CONFIRMADA


# --- edición: fija los campos tocados ------------------------------------------------------

def _edicion(reserva, **cambios_de_detalle) -> dict:
    segmento = {k: v for k, v in reserva.vista.segmentos[0].items()
                if k not in ("orden", "fijados", "versionTipo", "estado")}
    segmento["detalle"] = {**segmento["detalle"], **cambios_de_detalle}
    return {"version": reserva.version, "segmentos": [segmento]}


def test_la_edicion_fija_solo_los_campos_que_cambian(entorno, alta, registrada):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva

    resultado = gm.editar(entorno(), reserva.id, _edicion(reserva, puerta="12"))

    assert resultado.reserva.vista.segmentos[0]["fijados"] == ["detalle.puerta"]
    assert list(resultado.reserva.fijados) == [PUERTA]
    [evento] = resultado.eventos
    assert {"campo": PUERTA, "nuevo": "12", "fuente": "manual"} in evento.carga["cambios"]

    # Un proveedor posterior con otro valor abre un conflicto: el valor fijado se mantiene.
    ctx = entorno()
    proveedor = registrada(fuente="proveedor", version=ctx.ahora + timedelta(hours=1),
                           cambios={"detalle.puerta": "15"})
    ingesta = ingerir(ctx.repositorio, USUARIO, proveedor, ctx.ahora)
    assert ingesta.reserva.vista.segmentos[0]["detalle"]["puerta"] == "12"
    assert len(ingesta.consolidacion.conflictos_nuevos) == 1


def test_la_edicion_exige_la_version_vigente(entorno, alta):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva
    edicion = _edicion(reserva, puerta="12")
    edicion["version"] -= 1

    with pytest.raises(gm.ConflictoDeComando):
        gm.editar(entorno(), reserva.id, edicion)


def test_la_edicion_no_cambia_la_estructura(entorno, alta):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva
    edicion = _edicion(reserva)
    with pytest.raises(gm.SolicitudInvalida):
        gm.editar(entorno(), reserva.id, {**edicion, "segmentos": edicion["segmentos"] * 2})
    edicion["segmentos"][0]["tipo"] = "hotel"
    with pytest.raises(gm.SolicitudInvalida):
        gm.editar(entorno(), reserva.id, edicion)


def test_un_identificador_ajeno_no_se_mueve_y_vuelve_como_posible_duplicado(entorno, alta):
    una = gm.crear(entorno(), alta, uuid4()).reserva
    otra = gm.crear(entorno(), {**alta, "identificadores": [{"emisor": "agencia:x", "codigo": "9"}]},
                    uuid4()).reserva

    resultado = gm.editar(entorno(), otra.id, {"version": otra.version,
                                               "identificadores": [{"emisor": "aerolinea:AR",
                                                                    "codigo": "ABC123"}]})

    assert [d.reserva_id for d in resultado.posibles_duplicados] == [una.id]
    assert {i.emisor for i in resultado.reserva.identificadores} == {"agencia:x"}


def test_no_se_sugiere_como_duplicado_una_reserva_dada_de_baja(entorno, alta):
    una = gm.crear(entorno(), alta, uuid4()).reserva
    gm.dar_de_baja(entorno(), una.id)
    otra = gm.crear(entorno(), {**alta, "identificadores": [{"emisor": "agencia:x", "codigo": "9"}]},
                    uuid4()).reserva

    resultado = gm.editar(entorno(), otra.id, {"version": otra.version,
                                               "identificadores": alta["identificadores"]})

    assert resultado.posibles_duplicados == ()


# --- baja ----------------------------------------------------------------------------------

def test_la_baja_descarta_la_reserva_y_ya_no_se_encuentra(entorno, alta):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva

    resultado = gm.dar_de_baja(entorno(), reserva.id)

    assert resultado.reserva.estado == EstadoReserva.DESCARTADA
    [evento] = resultado.eventos
    assert {"campo": "estado", "anterior": "Confirmada", "nuevo": "Descartada",
            "fuente": "manual"} in evento.carga["cambios"]
    for comando in (lambda: gm.dar_de_baja(entorno(), reserva.id),
                    lambda: gm.editar(entorno(), reserva.id, _edicion(reserva))):
        with pytest.raises(gm.NoEncontrada):
            comando()


def test_otro_usuario_no_encuentra_la_reserva(entorno, alta):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva
    ajeno = gm.Contexto(entorno.repositorio, registro_por_omision(), UUID(int=99), instante(25))
    with pytest.raises(gm.NoEncontrada):
        gm.dar_de_baja(ajeno, reserva.id)


# --- confirmación de la banda media (ADR-0015) ---------------------------------------------

@pytest.fixture
def por_confirmar(entorno, registrada):
    ctx = entorno()
    resultado = ingerir(ctx.repositorio, USUARIO, registrada(banda="media"), ctx.ahora)
    persistir(ctx.repositorio, resultado)
    return resultado.reserva


def test_confirmar_y_descartar_solo_una_reserva_por_confirmar(entorno, por_confirmar):
    resultado = gm.confirmar(entorno(), por_confirmar.id, {"decision": "confirmar"})
    assert resultado.reserva.estado == EstadoReserva.CONFIRMADA
    with pytest.raises(gm.ConflictoDeComando):
        gm.confirmar(entorno(), por_confirmar.id, {"decision": "descartar"})


def test_descartar_saca_la_reserva(entorno, por_confirmar):
    gm.confirmar(entorno(), por_confirmar.id, {"decision": "descartar"})
    with pytest.raises(gm.NoEncontrada):
        gm.confirmar(entorno(), por_confirmar.id, {"decision": "confirmar"})


def test_la_correccion_se_aplica_como_edicion_y_confirma(entorno, por_confirmar):
    with pytest.raises(gm.SolicitudInvalida):  # corregir y descartar a la vez no tiene sentido
        gm.confirmar(entorno(), por_confirmar.id, {
            "decision": "descartar", "correccion": _edicion(por_confirmar)})

    resultado = gm.confirmar(entorno(), por_confirmar.id, {
        "decision": "confirmar", "correccion": _edicion(por_confirmar, puerta="3")})

    assert resultado.reserva.estado == EstadoReserva.CONFIRMADA
    assert resultado.reserva.vista.segmentos[0]["detalle"]["puerta"] == "3"


# --- resolución de conflictos --------------------------------------------------------------

@pytest.fixture
def con_conflicto(entorno, alta, registrada):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva
    reserva = gm.editar(entorno(), reserva.id, _edicion(reserva, puerta="12")).reserva
    ctx = entorno()
    proveedor = registrada(fuente="proveedor", version=ctx.ahora + timedelta(hours=1),
                           cambios={"detalle.puerta": "15"})
    resultado = ingerir(ctx.repositorio, USUARIO, proveedor, ctx.ahora)
    persistir(ctx.repositorio, resultado)
    [conflicto] = resultado.reserva.vista.conflictos
    return resultado.reserva, conflicto


def test_aceptar_la_fuente_cierra_el_conflicto_con_su_valor(entorno, con_conflicto):
    reserva, conflicto = con_conflicto
    resultado = gm.resolver_conflicto(entorno(), reserva.id, conflicto.id,
                                      {"eleccion": "aceptarFuente", "fuente": "proveedor"})
    assert resultado.reserva.vista.conflictos == ()
    assert resultado.reserva.vista.segmentos[0]["detalle"]["puerta"] == "15"


def test_resolver_valida_la_eleccion_y_el_conflicto(entorno, con_conflicto):
    reserva, conflicto = con_conflicto
    with pytest.raises(gm.SolicitudInvalida):
        gm.resolver_conflicto(entorno(), reserva.id, conflicto.id, {"eleccion": "aceptarFuente"})
    with pytest.raises(gm.SolicitudInvalida):
        gm.resolver_conflicto(entorno(), reserva.id, conflicto.id,
                              {"eleccion": "aceptarFuente", "fuente": "correo"})
    with pytest.raises(gm.NoEncontrada):
        gm.resolver_conflicto(entorno(), reserva.id, uuid4(), {"eleccion": "mantenerFijado"})


# --- eventos de la fusión ------------------------------------------------------------------

def test_una_cancelacion_publica_reserva_cancelada_con_su_fuente(entorno, alta, registrada,
                                                                 contratos):
    reserva = gm.crear(entorno(), alta, uuid4()).reserva
    ctx = entorno()
    resultado = ingerir(ctx.repositorio, USUARIO,
                        registrada(fuente="proveedor", version=ctx.ahora, cancelada=True), ctx.ahora)

    eventos = eventos_del_cambio(resultado.reserva, resultado.consolidacion, Fuente.PROVEEDOR,
                                 CAUSA, ctx.ahora, hubo_cambio=True)

    assert [e.tipo for e in eventos] == ["ReservaActualizada", "ReservaCancelada"]
    assert eventos[1].carga["fuente"] == "proveedor" and eventos[1].carga["reservaId"] == str(reserva.id)
    for evento in eventos:
        evento.validar(contratos)
