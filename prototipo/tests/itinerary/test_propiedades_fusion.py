"""Propiedades de la fusión (ADR-0010 «Confirmación», ADR-0017).

Para cualquier conjunto de observaciones y de campos fijados, el estado consolidado no depende
del orden de llegada ni de las repeticiones (ADR-0014, N3), no cambia al compactar las
observaciones (ADR-0012, ADR-0023) y siempre cumple el contrato.
"""

from datetime import timedelta
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from ayudas import CREADA_EN, USUARIO, instante
from trotamundos.comun.contratos import contratos_por_omision
from trotamundos.comun.modelo import ObservacionCanonica
from trotamundos.servicios.itinerary.fusion.consolidacion import ordenar, reconsolidar, vigentes
from trotamundos.servicios.itinerary.reservas import Banda, Fijado, ObservacionRegistrada, Reserva

RESERVA_CONTRATO = "openapi/comun.yaml#/components/schemas/Reserva"


def _extremo(hora: int, lugar: str) -> dict:
    return {"instante": f"2026-12-01T{hora:02d}:00:00Z", "precision": "instante",
            "zonaHoraria": "America/Argentina/Buenos_Aires",
            "lugar": {"nombre": lugar, "pais": "AR", "zonaHoraria": "America/Argentina/Buenos_Aires"}}


@st.composite
def segmentos(draw) -> dict:
    detalle = {"aerolinea": "AR", "numeroDeVuelo": draw(st.sampled_from(["1402", "1404"]))}
    for campo in ("puerta", "asiento"):
        valor = draw(st.sampled_from([None, "1", "2"]))
        if valor is not None:
            detalle[campo] = valor
    segmento = {"tipo": "vuelo", "versionTipo": 1, "inicio": _extremo(draw(st.sampled_from([13, 14])), "Aeroparque"),
                "fin": _extremo(16, draw(st.sampled_from(["El Plumerillo", "Ezeiza"]))),
                "operador": "Aerolíneas Argentinas", "detalle": detalle}
    estado = draw(st.sampled_from([None, "confirmado", "cancelado"]))
    if estado:
        segmento["estado"] = estado
    return segmento


@st.composite
def observaciones(draw) -> ObservacionRegistrada:
    fuente = draw(st.sampled_from(["correo", "proveedor", "manual"]))
    datos = {
        "fuente": fuente,
        "idDeFuente": draw(st.sampled_from(["a", "b", "c"])),
        "versionDeFuente": (instante(10) + timedelta(hours=draw(st.integers(0, 4)))).isoformat(),
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
        "segmentos": draw(st.lists(segmentos(), min_size=1, max_size=2)),
        "cancelada": draw(st.booleans()),
    }
    banda = Banda(draw(st.sampled_from(["alta", "media"]))) if fuente == "correo" else None
    return ObservacionRegistrada(ObservacionCanonica.desde_dict(datos), banda=banda)


fijados = st.lists(st.one_of(
    st.builds(Fijado, st.just("segmentos[0].detalle.puerta"), st.sampled_from(["1", "9"]),
              st.integers(0, 4).map(lambda h: instante(10) + timedelta(hours=h, minutes=30))),
    st.builds(Fijado, st.just("cancelada"), st.booleans(),
              st.integers(0, 4).map(lambda h: instante(10) + timedelta(hours=h, minutes=30))),
), max_size=2, unique_by=lambda f: f.campo)


def _reserva(entradas: list[ObservacionRegistrada], fijos: list[Fijado]) -> Reserva:
    reserva = Reserva(UUID(int=1), USUARIO, CREADA_EN)
    for fijado in fijos:
        reserva.fijar(fijado)
    for observacion in entradas:
        reserva.registrar(observacion)
    reconsolidar(reserva)
    return reserva


def _estado(reserva: Reserva) -> dict:
    datos = reserva.a_dict()
    datos.pop("version")  # cuenta cambios aplicados, que sí dependen del orden de llegada
    return datos


@settings(max_examples=200, deadline=None)
@given(st.lists(observaciones(), min_size=1, max_size=6), fijados, st.data())
def test_el_orden_de_llegada_y_las_repeticiones_no_cambian_el_resultado(entradas, fijos, data):
    permutadas = data.draw(st.permutations(entradas))
    repetidas = data.draw(st.lists(st.sampled_from(entradas), max_size=4))

    assert _estado(_reserva(entradas, fijos)) == _estado(_reserva(permutadas + repetidas, fijos))


@settings(max_examples=150, deadline=None)
@given(st.lists(observaciones(), min_size=1, max_size=6), fijados)
def test_compactar_las_observaciones_no_cambia_el_resultado(entradas, fijos):
    # La compactación conserva la observación vigente de cada fuente (ADR-0012, ADR-0023) y,
    # si la última de una fuente es de banda media y no es vigente, también esa (de ella salen
    # la banda y las fuentes de la reserva).
    completa = _reserva(entradas, fijos)
    ultimas: dict = {}
    for registrada in ordenar(completa.observaciones):
        ultimas.setdefault(registrada.fuente, registrada)
    conservadas = {o.clave: o for o in [*ultimas.values(), *vigentes(completa.observaciones)]}
    compactada = _reserva(list(conservadas.values()), fijos)

    assert _estado(compactada) == _estado(completa)


@settings(max_examples=100, deadline=None)
@given(st.lists(observaciones(), min_size=1, max_size=6), fijados)
def test_reconsolidar_sin_entradas_nuevas_no_cambia_nada(entradas, fijos):
    reserva = _reserva(entradas, fijos)
    version = reserva.version

    resultado = reconsolidar(reserva)

    assert resultado.cambios == () and resultado.conflictos_nuevos == ()
    assert reserva.version == version


@settings(max_examples=100, deadline=None)
@given(st.lists(observaciones(), min_size=1, max_size=6), fijados)
def test_la_reserva_consolidada_siempre_cumple_el_contrato(entradas, fijos):
    contratos_por_omision().validar(RESERVA_CONTRATO, _reserva(entradas, fijos).a_dict())
