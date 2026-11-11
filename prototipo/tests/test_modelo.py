"""Modelo canónico (`modelo-canonico`, ADR-0010): ida y vuelta fiel al contrato."""

from datetime import datetime, timezone

import pytest

from trotamundos.comun.modelo import (
    Fuente,
    ObservacionCanonica,
    Precision,
    instante_a_texto,
    instante_desde_texto,
)

OBSERVACION = "openapi/comun.yaml#/components/schemas/ObservacionCanonica"


def test_ida_y_vuelta_conserva_la_observacion(contratos, observacion):
    reconstruida = ObservacionCanonica.desde_dict(observacion).a_dict()
    assert reconstruida == observacion
    contratos.validar(OBSERVACION, reconstruida)


def test_ida_y_vuelta_con_todos_los_campos_opcionales(contratos, observacion):
    segmento = observacion["segmentos"][0]
    segmento["estado"] = "cancelado"
    segmento["inicio"]["lugar"].update(codigo="AEP", esquemaDeCodigo="IATA",
                                       coordenadas={"lat": -34.56, "lon": -58.42})
    observacion["cancelada"] = True

    assert ObservacionCanonica.desde_dict(observacion).a_dict() == observacion
    contratos.validar(OBSERVACION, observacion)


def test_los_campos_quedan_tipados(observacion, segmento_de_tren):
    observacion["segmentos"].append(segmento_de_tren)
    leida = ObservacionCanonica.desde_dict(observacion)

    assert leida.clave == (Fuente.CORREO, "buzon-1/mensaje-42")
    assert leida.segmentos[0].inicio.instante == datetime(2026, 12, 1, 13, tzinfo=timezone.utc)
    assert leida.segmentos[1].inicio.precision is Precision.DIA


def test_las_observaciones_se_pueden_usar_en_conjuntos(observacion):
    # La fusión (paso 3) agrupa observaciones; un dict en un campo no debe impedirlo.
    a = ObservacionCanonica.desde_dict(observacion)
    b = ObservacionCanonica.desde_dict(observacion)
    assert {a, b} == {a}


def test_el_detalle_no_comparte_estado_con_el_dict_de_origen(observacion):
    observacion["segmentos"][0]["detalle"]["escalas"] = [{"lugar": "COR"}]
    leida = ObservacionCanonica.desde_dict(observacion)
    observacion["segmentos"][0]["detalle"]["escalas"][0]["lugar"] = "MUTADO"
    assert leida.segmentos[0].detalle["escalas"][0]["lugar"] == "COR"


def test_un_instante_con_desplazamiento_se_guarda_en_utc():
    # ADR-0032: los instantes se guardan en UTC; la zona local va aparte.
    assert instante_a_texto(instante_desde_texto("2026-12-01T10:00:00-03:00")) == "2026-12-01T13:00:00Z"


def test_los_milisegundos_se_conservan():
    assert instante_a_texto(instante_desde_texto("2026-12-01T13:00:00.250Z")) == "2026-12-01T13:00:00.250Z"


def test_un_instante_sin_zona_se_rechaza():
    with pytest.raises(ValueError):
        instante_desde_texto("2026-12-01T13:00:00")
