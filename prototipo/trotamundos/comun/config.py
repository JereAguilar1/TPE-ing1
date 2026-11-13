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
            dsn_postgres=os.environ.get(
                "TROTAMUNDOS_DSN",
                # La base local de docker-compose.yml, sin contraseña (ver allí).
                "postgresql://trotamundos@localhost:55432/trotamundos",
            ),
            # Vacío: el servicio no publica ni consume (la outbox queda pendiente).
            broker=os.environ.get("TROTAMUNDOS_BROKER", "localhost:19092"),
            # Región primaria de esta instancia (AM, EU o AP; ADR-0002, ADR-0018).
            region=os.environ.get("TROTAMUNDOS_REGION", "AM"),
            intervalo_tareas_s=float(os.environ.get("TROTAMUNDOS_INTERVALO_TAREAS", "60")),
            prefijo_topicos=os.environ.get("TROTAMUNDOS_PREFIJO_TOPICOS", ""),
            modo=os.environ.get("TROTAMUNDOS_MODO", "completo"),
        )
