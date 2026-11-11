"""Registro de tipos de segmento (ADR-0011, ADR-0027, QA-15)."""

import pytest
import yaml

from trotamundos.comun.contratos import Contratos, ErrorDeContrato
from trotamundos.comun.modelo import RolEnViaje, Severidad
from trotamundos.comun.tipos_de_segmento import (
    DescriptorInvalido,
    RegistroDeTipos,
    TipoNoRegistrado,
    registro_por_omision,
)

RESPUESTA_GET_TIPOS = ("openapi/itinerary.yaml#/paths/~1tipos-de-segmento/get/responses/200"
                       "/content/application~1json/schema")


@pytest.fixture(scope="module")
def registro() -> RegistroDeTipos:
    return registro_por_omision()


def errores_de(registro, observacion) -> list[str]:
    with pytest.raises(ErrorDeContrato) as error:
        registro.validar_observacion(observacion)
    return error.value.errores


# --- carga ----------------------------------------------------------------------------------

def test_carga_los_cinco_descriptores_del_contrato(registro):
    assert registro.tipos() == ["auto", "autobus", "hotel", "tren", "vuelo"]


@pytest.mark.parametrize(("tipo", "rol"), [
    ("vuelo", RolEnViaje.TRASLADO),
    ("tren", RolEnViaje.TRASLADO),
    ("autobus", RolEnViaje.TRASLADO),
    ("hotel", RolEnViaje.ALOJAMIENTO),
    ("auto", RolEnViaje.MOVILIDAD_LOCAL),
])
def test_cada_tipo_declara_su_rol_en_el_viaje(registro, tipo, rol):
    assert registro.rol(tipo, 1) is rol


def test_expone_los_campos_relevantes_para_notification(registro):
    vuelo = registro.obtener("vuelo")
    assert vuelo.campos_relevantes[0].campo == "inicio.instante"
    assert vuelo.campos_relevantes[0].severidad is Severidad.CRITICA
    assert vuelo.campos_relevantes[0].umbral_minutos == 15


def test_un_tipo_no_registrado_se_informa(registro):
    with pytest.raises(TipoNoRegistrado):
        registro.obtener("barco")
    with pytest.raises(TipoNoRegistrado):
        registro.obtener("vuelo", 99)


def test_los_documentos_cumplen_la_respuesta_de_get_tipos_de_segmento(registro, contratos):
    contratos.validar(RESPUESTA_GET_TIPOS, registro.documentos())


def test_los_documentos_son_copias(registro):
    registro.documentos()[0]["rolEnViaje"] = "otro"
    registro.documento("vuelo")["presentacion"]["filas"].clear()
    assert registro.documentos()[0]["rolEnViaje"] != "otro"
    assert registro.documento("vuelo")["presentacion"]["filas"]


def test_documento_devuelve_el_descriptor_completo(registro):
    assert registro.documento("hotel", 1)["presentacion"]["icono"] == "hotel"


# --- validación de observaciones ------------------------------------------------------------

def test_una_observacion_valida_se_acepta(registro, observacion):
    registro.validar_observacion(observacion)


def test_un_boleto_abierto_de_tren_se_acepta(registro, observacion, segmento_de_tren):
    observacion["segmentos"] = [segmento_de_tren]
    registro.validar_observacion(observacion)


def test_el_detalle_se_valida_contra_el_esquema_de_su_tipo(registro, observacion):
    del observacion["segmentos"][0]["detalle"]["numeroDeVuelo"]
    assert errores_de(registro, observacion) == [
        "$.segmentos[0].detalle: 'numeroDeVuelo' is a required property",
    ]


def test_el_detalle_no_admite_campos_no_declarados(registro, observacion):
    # QA-11: la salida de un extractor defectuoso no se acepta en silencio (ADR-0011, K2).
    observacion["segmentos"][0]["detalle"]["vagon"] = "3"
    assert errores_de(registro, observacion)[0].startswith("$.segmentos[0].detalle:")


def test_un_segmento_de_tipo_no_registrado_se_rechaza(registro, observacion):
    observacion["segmentos"][0]["tipo"] = "barco"
    assert errores_de(registro, observacion) == [
        "$.segmentos[0].tipo: tipo de segmento no registrado: barco v1",
    ]


def test_los_errores_del_nucleo_y_del_detalle_se_informan_juntos(registro, observacion):
    observacion["segmentos"][0]["inicio"]["precision"] = "hora"
    observacion["segmentos"][0]["detalle"] = {}
    errores = errores_de(registro, observacion)
    assert any(e.startswith("$.segmentos[0].inicio.precision:") for e in errores)
    assert any(e.startswith("$.segmentos[0].detalle:") for e in errores)


# --- extensión: agregar un tipo es agregar un archivo (QA-15) --------------------------------

def escribir(carpeta, nombre, descriptor):
    (carpeta / "tipos-de-segmento" / nombre).write_text(yaml.safe_dump(descriptor), encoding="utf-8")


def barco(**cambios) -> dict:
    descriptor = {
        "tipo": "barco", "version": 1, "rolEnViaje": "traslado",
        "esquemaDeDetalle": {"type": "object", "required": ["camarote"],
                             "additionalProperties": False,
                             "properties": {"camarote": {"type": "string"},
                                            "cubierta": {"type": "string"}}},
        "camposRelevantes": [{"campo": "inicio.instante", "severidad": "critica",
                              "umbralMinutos": 30},
                             {"campo": "detalle.cubierta", "severidad": "informativa"}],
        "presentacion": {"icono": "barco", "titulo": "{operador} {referencia}",
                         "filas": ["camarote", "cubierta"]},
        "dimension": {"atributos": ["operador"]},
    }
    descriptor.update(cambios)
    return descriptor


def test_un_tipo_nuevo_se_incorpora_agregando_solo_su_descriptor(copia_de_contratos, observacion):
    escribir(copia_de_contratos, "barco.v1.yaml", barco())
    registro = RegistroDeTipos.desde_contratos(Contratos(copia_de_contratos))

    observacion["segmentos"][0].update(tipo="barco", detalle={"camarote": "214"})

    assert registro.rol("barco", 1) is RolEnViaje.TRASLADO
    registro.validar_observacion(observacion)


def test_las_versiones_de_un_tipo_coexisten(copia_de_contratos, segmento_de_tren):
    # ADR-0027: un segmento se valida contra la versión con que se creó.
    tren_v1 = yaml.safe_load((copia_de_contratos / "tipos-de-segmento/tren.v1.yaml").read_text())
    tren_v2 = {**tren_v1, "version": 2}
    tren_v2["esquemaDeDetalle"] = {**tren_v1["esquemaDeDetalle"],
                                   "required": ["numeroDeTren", "coche"]}
    escribir(copia_de_contratos, "tren.v2.yaml", tren_v2)
    registro = RegistroDeTipos.desde_contratos(Contratos(copia_de_contratos))

    assert registro.obtener("tren").version == 2
    registro.validar_detalle("tren", 1, segmento_de_tren["detalle"])
    with pytest.raises(ErrorDeContrato):
        registro.validar_detalle("tren", 2, segmento_de_tren["detalle"])


@pytest.mark.parametrize(("nombre", "descriptor", "problema"), [
    ("barco.v1.yaml", barco(rolEnViaje="crucero"), "$.rolEnViaje"),
    ("barco.v2.yaml", barco(), "el archivo debe llamarse barco.v1.yaml"),
    ("barco.v1.yaml", barco(camposRelevantes=[{"campo": "detalle.puerto", "severidad": "critica"}]),
     "camposRelevantes nombra un campo inexistente: detalle.puerto"),
    ("barco.v1.yaml", barco(camposRelevantes=[{"campo": "inicio.hora", "severidad": "critica"}]),
     "camposRelevantes nombra un campo inexistente: inicio.hora"),
    ("barco.v1.yaml", barco(presentacion={"icono": "barco", "titulo": "{operador}",
                                          "filas": ["puerto"]}),
     "presentacion.filas nombra un campo del detalle inexistente: puerto"),
    ("barco.v1.yaml", barco(presentacion={"icono": "barco", "titulo": "{camarote}", "filas": []}),
     "presentacion.titulo usa un campo que no es del núcleo: camarote"),
    ("barco.v1.yaml", barco(dimension={"atributos": ["naviera"]}),
     "dimension.atributos nombra un campo inexistente: naviera"),
    # Un subesquema booleano (`true`) es JSON Schema válido pero no declara subcampos.
    ("barco.v1.yaml", barco(
        esquemaDeDetalle={"type": "object", "properties": {"camarote": True}},
        camposRelevantes=[{"campo": "detalle.camarote.numero", "severidad": "critica"}],
        presentacion={"icono": "barco", "titulo": "{operador}", "filas": []}),
     "camposRelevantes nombra un campo inexistente: detalle.camarote.numero"),
])
def test_un_descriptor_incoherente_se_rechaza_al_cargar(copia_de_contratos, nombre, descriptor,
                                                        problema):
    escribir(copia_de_contratos, nombre, descriptor)
    with pytest.raises(DescriptorInvalido) as error:
        RegistroDeTipos.desde_contratos(Contratos(copia_de_contratos))
    assert any(problema in p and p.startswith(f"tipos-de-segmento/{nombre}")
               for p in error.value.problemas), error.value.problemas
