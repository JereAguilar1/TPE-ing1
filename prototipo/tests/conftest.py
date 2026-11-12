"""Datos de prueba compartidos."""

import shutil
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from trotamundos.comun.config import Configuracion
from trotamundos.comun.contratos import Contratos, contratos_por_omision


@pytest.fixture(scope="session")
def contratos() -> Contratos:
    return contratos_por_omision()


@pytest.fixture
def copia_de_contratos(tmp_path) -> Path:
    """Copia de `contratos/` que una prueba puede modificar (por ejemplo, agregar un tipo)."""
    destino = tmp_path / "contratos"
    shutil.copytree(contratos_por_omision().ruta, destino)
    return destino


@pytest.fixture(scope="session")
def dsn() -> str:
    """PostgreSQL de `docker-compose.yml`. Sin él, las pruebas que lo usan se saltean."""
    dsn = Configuracion.desde_entorno().dsn_postgres
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL no disponible: correr `make infra-arriba`")
    return dsn


@pytest.fixture
def esquema(dsn) -> str:
    """Esquema vacío y propio de la prueba; se borra al terminar."""
    nombre = f"prueba_{uuid.uuid4().hex[:12]}"
    yield nombre
    with psycopg.connect(dsn, autocommit=True) as conexion:
        conexion.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(nombre)))


def _extremo(instante: str, lugar: str, zona: str, precision: str = "instante") -> dict:
    return {"instante": instante, "precision": precision, "zonaHoraria": zona,
            "lugar": {"nombre": lugar, "pais": "AR", "zonaHoraria": zona}}


@pytest.fixture
def observacion() -> dict:
    """`ObservacionCanonica` válida: un vuelo Buenos Aires–Mendoza informado por correo."""
    return {
        "fuente": "correo",
        "idDeFuente": "buzon-1/mensaje-42",
        "versionDeFuente": "2026-11-10T12:00:00Z",
        "identificadores": [{"emisor": "aerolinea:AR", "codigo": "ABC123"}],
        "segmentos": [{
            "tipo": "vuelo",
            "versionTipo": 1,
            "inicio": _extremo("2026-12-01T13:00:00Z", "Aeroparque",
                               "America/Argentina/Buenos_Aires"),
            "fin": _extremo("2026-12-01T15:00:00Z", "El Plumerillo", "America/Argentina/Mendoza"),
            "operador": "Aerolíneas Argentinas",
            "referencia": "AR1402",
            "detalle": {"aerolinea": "AR", "numeroDeVuelo": "1402"},
        }],
    }


@pytest.fixture
def segmento_de_tren() -> dict:
    """Boleto abierto: vale «ese día», sin hora (`precision: dia`, ADR-0011)."""
    return {
        "tipo": "tren",
        "versionTipo": 1,
        "inicio": _extremo("2026-12-05T00:00:00Z", "Retiro", "America/Argentina/Buenos_Aires", "dia"),
        "fin": _extremo("2026-12-05T00:00:00Z", "Mar del Plata", "America/Argentina/Buenos_Aires",
                        "dia"),
        "operador": "Trenes Argentinos",
        "detalle": {"numeroDeTren": "R-301"},
    }
