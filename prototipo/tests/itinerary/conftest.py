"""Datos de prueba de `itinerary`."""

import copy
from datetime import datetime

import pytest

from ayudas import CREADA_EN, RESERVA, USUARIO, instante
from trotamundos.comun.modelo import ObservacionCanonica
from trotamundos.servicios.itinerary.reservas import Banda, ObservacionRegistrada, Reserva


@pytest.fixture
def registrada(observacion):
    """Fábrica de `ObservacionRegistrada` a partir del vuelo de `tests/conftest.py`.

    `cambios` modifica el primer segmento: `{"inicio.instante": "...", "detalle.puerta": "12"}`.
    """

    def construir(fuente: str = "correo", id_de_fuente: str = "mensaje-1",
                  version: datetime = instante(10), identificadores=(("aerolinea:AR", "ABC123"),),
                  cambios: dict | None = None, segmentos: list | None = None,
                  cancelada: bool = False, banda: str | None = "alta") -> ObservacionRegistrada:
        datos = copy.deepcopy(observacion)
        datos.update(fuente=fuente, idDeFuente=id_de_fuente,
                     versionDeFuente=version.isoformat().replace("+00:00", "Z"),
                     identificadores=[{"emisor": e, "codigo": c} for e, c in identificadores])
        if segmentos is not None:
            datos["segmentos"] = segmentos
        for ruta, valor in (cambios or {}).items():
            nodo = datos["segmentos"][0]
            *camino, hoja = ruta.split(".")
            for parte in camino:
                nodo = nodo.setdefault(parte, {})
            nodo[hoja] = valor
        if cancelada:
            datos["cancelada"] = True
        return ObservacionRegistrada(ObservacionCanonica.desde_dict(datos),
                                     banda=Banda(banda) if fuente == "correo" else None)

    return construir


@pytest.fixture
def reserva() -> Reserva:
    return Reserva(RESERVA, USUARIO, CREADA_EN)
