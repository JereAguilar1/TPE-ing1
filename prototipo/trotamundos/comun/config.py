"""Configuración compartida por todos los servicios, leída del entorno.

Los valores por omisión apuntan a la infraestructura de `docker-compose.yml` (ADR-0036).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# prototipo/trotamundos/comun/config.py -> raíz del repositorio
_RAIZ_REPOSITORIO = Path(__file__).resolve().parents[3]
# Lo que genera `make infra-arriba` para la base local (ignorado por git).
_ARCHIVO_ENV = _RAIZ_REPOSITORIO / "prototipo" / ".env"


def _variable(nombre: str) -> str:
    """Del entorno o, si no está, de `prototipo/.env`."""
    if nombre in os.environ:
        return os.environ[nombre]
    if _ARCHIVO_ENV.is_file():
        for linea in _ARCHIVO_ENV.read_text().splitlines():
            clave, _, valor = linea.partition("=")
            if clave.strip() == nombre:
                return valor.strip()
    return ""


def _dsn_local() -> str:
    """La base local de docker-compose.yml. Su contraseña no está en el código: está en `.env`."""
    contrasena = quote(_variable("POSTGRES_PASSWORD"), safe="")
    return f"postgresql://trotamundos:{contrasena}@localhost:55432/trotamundos"


@dataclass(frozen=True)
class Configuracion:
    ruta_contratos: Path
    dsn_postgres: str
    broker: str
    region: str
    # Cada cuántos segundos corre el trabajo periódico de un servicio; 0 lo apaga.
    intervalo_tareas_s: float = 60.0
    # Antepuesto a los tópicos del broker: aísla entornos (por ejemplo, las pruebas).
    prefijo_topicos: str = ""
    # Modo de despliegue de un servicio con lectura y escritura separadas (ADR-0021):
    # `completo`, `lectura` o `escritura`.
    modo: str = "completo"

    @classmethod
    def desde_entorno(cls) -> "Configuracion":
        return cls(
            ruta_contratos=Path(
                os.environ.get("TROTAMUNDOS_CONTRATOS", _RAIZ_REPOSITORIO / "contratos")
            ).resolve(),
            dsn_postgres=os.environ.get("TROTAMUNDOS_DSN") or _dsn_local(),
            # Vacío: el servicio no publica ni consume (la outbox queda pendiente).
            broker=os.environ.get("TROTAMUNDOS_BROKER", "localhost:19092"),
            # Región primaria de esta instancia (AM, EU o AP; ADR-0002, ADR-0018).
            region=os.environ.get("TROTAMUNDOS_REGION", "AM"),
            intervalo_tareas_s=float(os.environ.get("TROTAMUNDOS_INTERVALO_TAREAS", "60")),
            prefijo_topicos=os.environ.get("TROTAMUNDOS_PREFIJO_TOPICOS", ""),
            modo=os.environ.get("TROTAMUNDOS_MODO", "completo"),
        )
