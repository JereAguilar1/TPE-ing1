"""Puerto puro `Extractor` v1.x (contratos/plugins/extractor.yaml)."""
from typing import Protocol


class FormatoNoSoportado(ValueError):
    """El complemento no reconoce este mensaje."""


class MensajeCorrupto(ValueError):
    """La plantilla se reconoce, pero su estructura o sus campos son inválidos."""


class Extractor(Protocol):
    def reconoce(self, mensaje: dict) -> dict: ...

    def extrae(self, mensaje: dict, *, buzon_id: str, id_de_mensaje: str) -> dict:
        """El contexto del sobre permite construir `idDeFuente`, sin consultar servicios."""
        ...
