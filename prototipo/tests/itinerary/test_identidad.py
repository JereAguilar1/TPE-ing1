"""Identidad por identificadores múltiples y unificación (ADR-0013)."""

import copy
from datetime import timedelta
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ayudas import USUARIO, instante
from repositorio_en_memoria import RepositorioEnMemoria
from trotamundos.comun.modelo import Identificador, ObservacionCanonica
from trotamundos.servicios.itinerary.fusion.identidad import (
    MOTIVO_IDENTIFICADOR,
    MOTIVO_PARECIDO,
    PosibleDuplicado,
    fecha_local,
    ingerir,
    ingerir_observacion,
    persistir,
)
from trotamundos.servicios.itinerary.reservas import Banda, ObservacionRegistrada

AEROLINEA = ("aerolinea:AR", "ABC123")
AGENCIA = ("agencia:despegar", "ORD-9")


class _Ids:
    """Ids previsibles: la reserva n-ésima creada tiene el id n."""

    def __init__(self) -> None:
        self.ultimo = 0

    def __call__(self) -> UUID:
        self.ultimo += 1
        return UUID(int=self.ultimo)


@pytest.fixture
def ingesta():
    repositorio, ids = RepositorioEnMemoria(), _Ids()
    reloj = iter(instante(1) + timedelta(minutes=m) for m in range(1000))

    def ingerir_y_guardar(registrada: ObservacionRegistrada):
        resultado = ingerir(repositorio, USUARIO, registrada, next(reloj), ids)
        persistir(repositorio, resultado)
        return resultado

    ingerir_y_guardar.repositorio = repositorio
    return ingerir_y_guardar


def test_sin_identificador_coincidente_se_crea_una_reserva(ingesta, registrada):
    resultado = ingesta(registrada())

    assert resultado.creada and resultado.aplicada
    assert resultado.reserva.identificadores == {Identificador(*AEROLINEA)}
    assert resultado.posibles_duplicados == ()


def test_coincidir_con_cualquiera_de_los_identificadores_es_la_misma_reserva(ingesta, registrada):
    primera = ingesta(registrada(id_de_fuente="aerolinea", identificadores=(AEROLINEA,)))
    agencia = ingesta(registrada(id_de_fuente="agencia", identificadores=(AGENCIA, AEROLINEA)))
    proveedor = ingesta(registrada(fuente="proveedor", id_de_fuente="x", identificadores=(AGENCIA,)))

    assert not agencia.creada and not proveedor.creada
    assert agencia.reserva.id == proveedor.reserva.id == primera.reserva.id
    assert len(ingesta.repositorio.reservas) == 1


def test_la_misma_observacion_sin_identificadores_vuelve_a_su_reserva(ingesta, registrada):
    alta = registrada(fuente="manual", id_de_fuente="alta-1", identificadores=())
    primera = ingesta(alta)
    repetida = ingesta(alta)

    assert repetida.reserva.id == primera.reserva.id
    assert not repetida.creada and not repetida.aplicada
    assert repetida.consolidacion.cambios == ()


def test_una_observacion_que_liga_dos_reservas_las_unifica_en_la_mas_antigua(ingesta, registrada):
    antigua = ingesta(registrada(id_de_fuente="aerolinea", identificadores=(AEROLINEA,)))
    nueva = ingesta(registrada(id_de_fuente="agencia", identificadores=(AGENCIA,),
                               version=instante(11), cambios={"detalle.asiento": "3A"}))
    assert antigua.reserva.id != nueva.reserva.id

    liga = ingesta(registrada(fuente="proveedor", id_de_fuente="x",
                              identificadores=(AEROLINEA, AGENCIA)))

    assert liga.reserva.id == antigua.reserva.id
    assert [r.id for r in liga.unificadas] == [nueva.reserva.id]
    assert liga.reserva.identificadores == {Identificador(*AEROLINEA), Identificador(*AGENCIA)}
    assert liga.reserva.vista.segmentos[0]["detalle"]["asiento"] == "3A"
    assert list(ingesta.repositorio.reservas) == [antigua.reserva.id]


def test_si_alguna_es_manual_no_se_unifican_y_se_pide_confirmacion(ingesta, registrada):
    automatica = ingesta(registrada(id_de_fuente="aerolinea", identificadores=(AEROLINEA,)))
    manual = ingesta(registrada(fuente="manual", id_de_fuente="alta-1", identificadores=(AGENCIA,)))

    liga = ingesta(registrada(fuente="proveedor", id_de_fuente="x",
                              identificadores=(AEROLINEA, AGENCIA)))

    assert liga.unificadas == ()
    assert liga.reserva.id == automatica.reserva.id
    assert liga.posibles_duplicados == (PosibleDuplicado(manual.reserva.id, MOTIVO_IDENTIFICADOR),)
    # El identificador de la agencia sigue siendo solo de la reserva manual.
    assert Identificador(*AGENCIA) not in liga.reserva.identificadores
    assert len(ingesta.repositorio.reservas) == 2


def test_una_reserva_dada_de_baja_no_se_traga_a_una_visible(ingesta, registrada):
    dada_de_baja = ingesta(registrada(id_de_fuente="aerolinea", identificadores=(AEROLINEA,)))
    dada_de_baja.reserva.dar_de_baja()
    visible = ingesta(registrada(id_de_fuente="agencia", identificadores=(AGENCIA,),
                                 version=instante(11)))

    liga = ingesta(registrada(fuente="proveedor", id_de_fuente="x",
                              identificadores=(AEROLINEA, AGENCIA)))

    assert liga.unificadas == () and liga.posibles_duplicados == ()
    assert liga.reserva.id == visible.reserva.id  # la observación va a la que el usuario ve
    assert Identificador(*AEROLINEA) not in liga.reserva.identificadores
    assert len(ingesta.repositorio.reservas) == 2


def test_dos_habitaciones_del_mismo_hotel_la_misma_noche_no_se_fusionan(ingesta, registrada):
    # Prueba negativa de ADR-0013: sin código común, el sistema solo sugiere.
    def habitacion(id_de_fuente: str) -> ObservacionRegistrada:
        base = registrada().observacion.segmentos[0].a_dict()
        hotel = {**copy.deepcopy(base), "tipo": "hotel", "operador": "Hotel Aconcagua",
                 "detalle": {"habitaciones": 1, "huespedes": 2}}
        hotel["fin"]["lugar"] = hotel["inicio"]["lugar"]
        return registrada(id_de_fuente=id_de_fuente, identificadores=(), segmentos=[hotel])

    primera = ingesta(habitacion("mensaje-1"))
    segunda = ingesta(habitacion("mensaje-2"))

    assert segunda.creada and segunda.reserva.id != primera.reserva.id
    assert segunda.posibles_duplicados == (PosibleDuplicado(primera.reserva.id, MOTIVO_PARECIDO),)
    assert len(ingesta.repositorio.reservas) == 2


def test_no_se_sugiere_lo_que_empieza_otro_dia_o_en_otro_lugar(ingesta, registrada):
    ingesta(registrada(id_de_fuente="ida", identificadores=()))
    otro_dia = ingesta(registrada(id_de_fuente="otra", identificadores=(),
                                  cambios={"inicio.instante": "2026-12-03T13:00:00Z"}))
    otro_lugar = ingesta(registrada(id_de_fuente="vuelta", identificadores=(),
                                    cambios={"inicio.lugar": {"nombre": "Mendoza", "pais": "AR",
                                                              "zonaHoraria": "America/Argentina/Mendoza"}}))

    assert otro_dia.posibles_duplicados == () and otro_lugar.posibles_duplicados == ()


def test_ingerir_una_observacion_recibida_de_afuera(registrada):
    repositorio = RepositorioEnMemoria()
    correo = registrada(banda="media").observacion

    resultado = ingerir_observacion(repositorio, USUARIO, correo, instante(1), banda="media",
                                    confianza=0.7)

    [guardada] = resultado.reserva.observaciones
    assert (guardada.banda, guardada.confianza) == (Banda.MEDIA, 0.7)
    assert resultado.reserva.estado.value == "PorConfirmar"


def test_la_fecha_local_respeta_la_zona_y_los_boletos_abiertos(segmento_de_tren):
    tarde = {"instante": "2026-12-05T02:00:00Z", "precision": "instante",
             "zonaHoraria": "America/Argentina/Buenos_Aires"}
    assert str(fecha_local(tarde)) == "2026-12-04"  # 23 h del 4 en Buenos Aires
    assert str(fecha_local(segmento_de_tren["inicio"])) == "2026-12-05"  # precision: dia


# --- propiedad: sin reservas manuales, la unificación converge -------------------------------

CODIGOS = [("aerolinea:AR", "A1"), ("agencia:x", "B2"), ("agencia:y", "C3")]


@st.composite
def observaciones_automaticas(draw, base: dict) -> ObservacionRegistrada:
    fuente = draw(st.sampled_from(["correo", "proveedor"]))
    datos = copy.deepcopy(base)
    datos.update(
        fuente=fuente, idDeFuente=draw(st.sampled_from(["m1", "m2", "m3", "m4"])),
        versionDeFuente=(instante(10) + timedelta(hours=draw(st.integers(0, 3)))).isoformat(),
        identificadores=[{"emisor": e, "codigo": c}
                         for e, c in draw(st.lists(st.sampled_from(CODIGOS), min_size=1, unique=True))],
    )
    datos["segmentos"][0]["detalle"]["puerta"] = draw(st.sampled_from(["1", "2"]))
    return ObservacionRegistrada(ObservacionCanonica.desde_dict(datos),
                                 banda=Banda.ALTA if fuente == "correo" else None)


def _contenido(repositorio: RepositorioEnMemoria) -> list:
    """Las reservas sin lo que depende del orden: ids, versión e ids de segmento."""
    contenido = []
    for reserva in repositorio.reservas.values():
        datos = reserva.a_dict()
        for clave in ("id", "version"):
            datos.pop(clave)
        for segmento in datos["segmentos"]:
            segmento.pop("id")
        contenido.append(repr(datos))
    return sorted(contenido)


# La fixture `observacion` solo se lee (se copia con deepcopy), así que compartirla entre ejemplos
# es seguro.
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.data())
def test_sin_manuales_el_resultado_no_depende_del_orden_de_llegada(observacion, data):
    entradas = data.draw(st.lists(observaciones_automaticas(observacion), min_size=1, max_size=6))
    permutadas = data.draw(st.permutations(entradas))

    resultados = []
    for orden in (entradas, permutadas):
        repositorio, ids = RepositorioEnMemoria(), _Ids()
        for minuto, registrada in enumerate(orden):
            persistir(repositorio, ingerir(repositorio, USUARIO, registrada,
                                           instante(1) + timedelta(minutes=minuto), ids))
        resultados.append(_contenido(repositorio))

    assert resultados[0] == resultados[1]
