"""Configuración compartida por todos los servicios, leída del entorno.

Los valores por omisión apuntan a la infraestructura de `docker-compose.yml` (ADR-0036).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# prototipo/trotamundos/comun/config.py -> raíz del repositorio
_RAIZ_REPOSITORIO = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Configuracion:
    ruta_contratos: Path
    dsn_postgres: str
    broker: str
    region: str

    @classmethod
    def desde_entorno(cls) -> "Configuracion":
        return cls(
            ruta_contratos=Path(
                os.environ.get("TROTAMUNDOS_CONTRATOS", _RAIZ_REPOSITORIO / "contratos")
            ).resolve(),
            dsn_postgres=os.environ.get(
                "TROTAMUNDOS_DSN",
                "postgresql://trotamundos:trotamundos@localhost:55432/trotamundos",
            ),
            broker=os.environ.get("TROTAMUNDOS_BROKER", "localhost:19092"),
            # Región primaria de esta instancia (AM, EU o AP; ADR-0002, ADR-0018).
            region=os.environ.get("TROTAMUNDOS_REGION", "AM"),
        )
