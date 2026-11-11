"""Los eventos se construyen, validan y serializan según el contrato AsyncAPI."""

import uuid

import pytest

from trotamundos.comun.contratos import ErrorDeContrato, contratos_por_omision
from trotamundos.comun.eventos import Evento

USUARIO = str(uuid.uuid4())


@pytest.fixture(scope="module")
def contratos():
    return contratos_por_omision()


def reserva_extraida(banda: str = "alta") -> Evento:
    observacion = {
        "fuente": "correo",
        "idDeFuente": "buzon-1/mensaje-42",
        "versionDeFuente": "2026-11-10T12:00:00Z",
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
        "segmentos": [{
            "tipo": "vuelo", "versionTipo": 1, "operador": "Aerolíneas Argentinas",
            "inicio": {"instante": "2026-12-01T13:00:00Z", "precision": "instante",
                       "zonaHoraria": "America/Argentina/Buenos_Aires",
                       "lugar": {"nombre": "Aeroparque", "pais": "AR",
                                 "zonaHoraria": "America/Argentina/Buenos_Aires"}},
            "fin": {"instante": "2026-12-01T15:00:00Z", "precision": "instante",
                    "zonaHoraria": "America/Argentina/Mendoza",
                    "lugar": {"nombre": "El Plumerillo", "pais": "AR",
                              "zonaHoraria": "America/Argentina/Mendoza"}},
            "detalle": {"aerolinea": "AR", "numeroDeVuelo": "1402"},
        }],
    }
    carga = {
        "buzonId": str(uuid.uuid4()),
        "idDeMensaje": "mensaje-42",
        "extractor": {"id": "extractor-aerolineas", "version": "1.0.0"},
        "banda": banda,
        "confianza": {"global": 0.93, "porCampo": {"inicio.instante": 0.93}},
        "observacion": observacion,
    }
    return Evento.nuevo("ReservaExtraida", carga, productor="booking-extraction",
                        usuario_id=USUARIO, region="AM")


def test_un_evento_bien_formado_cumple_el_contrato(contratos):
    reserva_extraida().validar(contratos)


def test_la_banda_baja_no_se_publica_como_reserva_extraida(contratos):
    # ADR-0015: la banda baja produce ExtraccionNoReconocida, nunca ReservaExtraida.
    with pytest.raises(ErrorDeContrato):
        reserva_extraida(banda="baja").validar(contratos)


def test_el_sobre_exige_usuario_id(contratos):
    evento = reserva_extraida()
    sobre = {k: v for k, v in evento.sobre.items() if k != "usuarioId"}
    with pytest.raises(ErrorDeContrato):
        Evento(evento.tipo, sobre, evento.carga).validar(contratos)


def test_ida_y_vuelta_por_kafka_conserva_sobre_y_carga():
    evento = reserva_extraida()
    clave, valor, cabeceras = evento.a_kafka()
    assert clave == USUARIO.encode()  # partición por usuario (ADR-0018)
    assert Evento.desde_kafka(valor, cabeceras) == evento


def test_todos_los_eventos_del_contrato_tienen_canal(contratos):
    tipos = contratos.tipos_de_evento()
    assert len(tipos) == 16
    for tipo in tipos:
        assert contratos.canal_de_evento(tipo).startswith("dominio.")


def test_un_tipo_no_declarado_se_rechaza(contratos):
    with pytest.raises(KeyError):
        contratos.referencia_carga("EventoInventado")


def cuenta_suprimida(usuario_id=None) -> Evento:
    return Evento.nuevo("CuentaSuprimida",
                        {"seudonimoAnalitico": "s-123", "suprimidaEn": "2026-11-11T00:00:00Z"},
                        productor="identity-access", usuario_id=usuario_id)


def test_cuenta_suprimida_no_lleva_datos_del_usuario(contratos):
    # ADR-0030: el evento de supresión no puede identificar al usuario.
    cuenta_suprimida().validar(contratos)
    with pytest.raises(ErrorDeContrato):
        cuenta_suprimida(usuario_id=USUARIO).validar(contratos)


def test_cuenta_suprimida_se_particiona_por_seudonimo():
    assert cuenta_suprimida().clave_de_particion == "s-123"


@pytest.mark.parametrize(
    ("valor", "cabeceras"),
    [(b"{}", []), (b"no es json", [("tipo", b"ReservaExtraida")])],
)
def test_un_mensaje_mal_formado_se_rechaza(valor, cabeceras):
    with pytest.raises(ErrorDeContrato):
        Evento.desde_kafka(valor, cabeceras)


def test_las_cabeceras_ajenas_al_sobre_se_ignoran():
    evento = reserva_extraida()
    clave, valor, cabeceras = evento.a_kafka()
    assert Evento.desde_kafka(valor, [*cabeceras, ("x-otra", b"1")]) == evento
