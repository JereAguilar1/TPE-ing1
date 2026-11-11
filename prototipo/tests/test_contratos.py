"""La librería común valida contra los archivos de `contratos/` (ADR-0009, ADR-0036)."""

import pytest

from trotamundos.comun.contratos import Contratos, ErrorDeContrato, contratos_por_omision

RESERVA = "openapi/comun.yaml#/components/schemas/Reserva"


@pytest.fixture(scope="module")
def contratos() -> Contratos:
    return contratos_por_omision()


def reserva_valida() -> dict:
    return {
        "id": "0b9d7c1e-3f5a-4b6e-9c2d-1a2b3c4d5e6f",
        "estado": "Confirmada",
        "version": 1,
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
        "fuentes": ["correo"],
        "segmentos": [
            {
                "id": "6f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b",
                "tipo": "vuelo",
                "versionTipo": 1,
                "orden": 0,
                "inicio": {
                    "instante": "2026-12-01T13:00:00Z",
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Buenos_Aires",
                    "lugar": {"nombre": "Aeroparque", "codigo": "AEP", "pais": "AR",
                              "zonaHoraria": "America/Argentina/Buenos_Aires"},
                },
                "fin": {
                    "instante": "2026-12-01T15:00:00Z",
                    "precision": "instante",
                    "zonaHoraria": "America/Argentina/Mendoza",
                    "lugar": {"nombre": "El Plumerillo", "codigo": "MDZ", "pais": "AR",
                              "zonaHoraria": "America/Argentina/Mendoza"},
                },
                "operador": "Aerolíneas Argentinas",
                "referencia": "AR1402",
                "estado": "confirmado",
                "detalle": {"aerolinea": "AR", "numeroDeVuelo": "1402"},
            }
        ],
    }


def test_una_reserva_valida_cumple_el_contrato(contratos):
    contratos.validar(RESERVA, reserva_valida())


def test_una_reserva_sin_segmentos_no_cumple_el_contrato(contratos):
    reserva = reserva_valida()
    reserva["segmentos"] = []
    with pytest.raises(ErrorDeContrato) as error:
        contratos.validar(RESERVA, reserva)
    assert any("segmentos" in e for e in error.value.errores)


def test_un_estado_fuera_del_contrato_se_rechaza(contratos):
    reserva = reserva_valida()
    reserva["estado"] = "Inventada"
    assert contratos.errores(RESERVA, reserva)


def test_resumen_publicable_rechaza_campos_fuera_de_la_lista_blanca(contratos):
    # ADR-0028: un localizador es irrepresentable en ResumenPublicable.
    ref = "openapi/sharing.yaml#/components/schemas/ResumenPublicable"
    resumen = {"tituloViaje": "Mendoza", "ciudadesDestino": ["Mendoza"],
               "mesAnio": "2026-12", "tiposTransporte": ["vuelo"]}
    contratos.validar(ref, resumen)
    assert contratos.errores(ref, resumen | {"codigoReserva": "ABC123"})


@pytest.mark.parametrize("tipo", ["vuelo", "hotel", "auto", "tren", "autobus"])
def test_los_cinco_descriptores_cumplen_el_metaesquema(contratos, tipo):
    descriptores = dict(contratos.descriptores())
    descriptor = descriptores[f"tipos-de-segmento/{tipo}.v1.yaml"]
    contratos.validar("tipos-de-segmento/descriptor.schema.yaml#", descriptor)


def test_un_descriptor_con_rol_desconocido_se_rechaza(contratos):
    descriptor = dict(dict(contratos.descriptores())["tipos-de-segmento/tren.v1.yaml"])
    descriptor["rolEnViaje"] = "teletransporte"
    assert contratos.errores("tipos-de-segmento/descriptor.schema.yaml#", descriptor)


def test_una_fecha_que_no_es_rfc3339_se_rechaza(contratos):
    # Los instantes son UTC en RFC 3339 (ADR-0032); sin esto la validación de formato no se aplica.
    reserva = reserva_valida()
    reserva["segmentos"][0]["inicio"]["instante"] = "ayer a la tarde"
    assert contratos.errores(RESERVA, reserva)


def test_una_uri_invalida_se_rechaza(contratos):
    # format: uri también se aplica (extra format-nongpl de jsonschema).
    problema = {"type": "no es una uri", "title": "x", "status": 400}
    assert contratos.errores("openapi/comun.yaml#/components/schemas/Problema", problema)


def test_modificar_un_documento_no_altera_las_validaciones(contratos):
    ref = "openapi/comun.yaml#/components/schemas/Identificador"
    documento = contratos.documento("openapi/comun.yaml")
    documento["components"]["schemas"]["Identificador"]["required"].append("inventado")
    contratos.validador.cache_clear()
    assert not contratos.errores(ref, {"emisor": "aerolinea:AR", "codigo": "ABC123"})


def test_una_referencia_fuera_de_contratos_se_rechaza(contratos):
    with pytest.raises(ValueError, match="sale de la carpeta de contratos"):
        contratos.validar("../README.md#", {})


def test_los_errores_indican_la_ruta_del_campo(contratos):
    reserva = reserva_valida()
    reserva["segmentos"][0]["estado"] = "perdido"
    assert any(e.startswith("$.segmentos[0].estado:") for e in contratos.errores(RESERVA, reserva))
