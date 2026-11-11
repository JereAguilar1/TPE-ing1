"""Eventos de dominio: sobre, carga y su representación en el broker.

Contrato: `contratos/asyncapi/eventos-de-dominio.yaml`.

- El **sobre** (`Sobre` en el contrato) viaja en las cabeceras del mensaje Kafka; la **carga**, en el
  cuerpo como JSON.
- La **clave** del mensaje es `usuarioId`, de modo que los eventos de un usuario quedan en la misma
  partición y se procesan en orden (ADR-0014, ADR-0018). `CuentaSuprimida` no lleva `usuarioId`
  (ADR-0030) y se particiona por el seudónimo analítico.
- `idDeEvento` es la clave de la bandeja de entrada de cada consumidor (ADR-0014).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from trotamundos.comun.contratos import Contratos, ErrorDeContrato

VERSION_ESQUEMA = "1.0"  # versionEsquema inicial de cada evento (ADR-0027)
_REFERENCIA_SOBRE = "asyncapi/eventos-de-dominio.yaml#/components/schemas/Sobre"

# Campos del sobre (esquemas `Sobre` y `SobreSinUsuario`). Al leer un mensaje se toman solo estas
# cabeceras: otras que agregue la infraestructura (por ejemplo, de trazas) no forman parte del sobre.
_CABECERAS = (
    "idDeEvento", "tipo", "versionEsquema", "usuarioId", "ocurridoEn",
    "productor", "regionOrigen", "idDeCausa", "traceparent",
)


def ahora_utc() -> str:
    """Instante actual en UTC con formato RFC 3339 (ADR-0032)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Evento:
    tipo: str
    sobre: dict[str, Any]
    carga: dict[str, Any]

    @classmethod
    def nuevo(
        cls,
        tipo: str,
        carga: dict[str, Any],
        *,
        productor: str,
        usuario_id: str | None,
        region: str | None = None,
        id_de_causa: str | None = None,
        traceparent: str | None = None,
    ) -> "Evento":
        sobre: dict[str, Any] = {
            "idDeEvento": str(uuid.uuid4()),
            "tipo": tipo,
            "versionEsquema": VERSION_ESQUEMA,
            "ocurridoEn": ahora_utc(),
            "productor": productor,
        }
        opcionales = {
            "usuarioId": usuario_id,
            "regionOrigen": region,
            "idDeCausa": id_de_causa,
            "traceparent": traceparent,
        }
        sobre.update({k: v for k, v in opcionales.items() if v is not None})
        return cls(tipo=tipo, sobre=sobre, carga=carga)

    @property
    def id(self) -> str:
        return self.sobre["idDeEvento"]

    @property
    def clave_de_particion(self) -> str:
        return self.sobre.get("usuarioId") or self.carga.get("seudonimoAnalitico") or self.id

    def validar(self, contratos: Contratos) -> None:
        """Lanza `ErrorDeContrato` si el sobre o la carga no cumplen el contrato AsyncAPI."""
        contratos.validar(contratos.referencia_sobre(self.tipo), self.sobre)
        contratos.validar(contratos.referencia_carga(self.tipo), self.carga)

    # --- representación en Kafka ---------------------------------------------------------

    def a_kafka(self) -> tuple[bytes, bytes, list[tuple[str, bytes]]]:
        """(clave, valor, cabeceras) listos para el productor."""
        cabeceras = [(k, str(v).encode()) for k, v in self.sobre.items()]
        valor = json.dumps(self.carga, ensure_ascii=False, separators=(",", ":")).encode()
        return self.clave_de_particion.encode(), valor, cabeceras

    @classmethod
    def desde_kafka(cls, valor: bytes, cabeceras: list[tuple[str, bytes]]) -> "Evento":
        """Reconstruye el evento. Lanza `ErrorDeContrato` si el mensaje no trae sobre o carga."""
        sobre = {k: v.decode() for k, v in cabeceras if k in _CABECERAS}
        if "tipo" not in sobre:
            raise ErrorDeContrato(_REFERENCIA_SOBRE, ["el mensaje no trae la cabecera 'tipo'"])
        try:
            carga = json.loads(valor)
        except ValueError as error:
            raise ErrorDeContrato(_REFERENCIA_SOBRE, [f"la carga no es JSON: {error}"]) from error
        return cls(tipo=sobre["tipo"], sobre=sobre, carga=carga)


@dataclass
class RegistroDeEventos:
    """Acumula eventos emitidos; útil en pruebas y como paso previo a la outbox."""

    eventos: list[Evento] = field(default_factory=list)

    def emitir(self, evento: Evento) -> None:
        self.eventos.append(evento)

    def de_tipo(self, tipo: str) -> list[Evento]:
        return [e for e in self.eventos if e.tipo == tipo]
