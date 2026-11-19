"""Puerto `AdaptadorDeProveedor` v1.x (`contratos/plugins/adaptador.yaml`, ADR-0006, ADR-0027).

Lo implementa cada complemento `adaptador-<proveedor>` en `complementos/`. Ningún tipo del modelo
del proveedor sale del complemento (regla R3): toda salida es una `ObservacionCanonica`, un
`CambioObservado` o una `Disrupcion`.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ErrorDeAdaptador(ValueError):
    """Error declarado en las operaciones de `contratos/plugins/adaptador.yaml`."""


class NoEncontrada(ErrorDeAdaptador):
    """La reserva no existe en el proveedor (`obtenerReserva`)."""


class CargaInvalida(ErrorDeAdaptador):
    """El cuerpo de un webhook entrante no cumple el formato del proveedor (`traducirNotificacion`)."""


class CuotaExcedida(ErrorDeAdaptador):
    """El proveedor respondió `429` (`obtenerReserva`, `sondear`)."""

    def __init__(self, mensaje: str = "Cuota del proveedor excedida", *,
                 retry_after: int | None = None):
        super().__init__(mensaje)
        self.retry_after = retry_after


class ProveedorNoDisponible(ErrorDeAdaptador):
    """Falla transitoria del proveedor (`obtenerReserva`, `sondear`)."""


class AdaptadorDeProveedor(Protocol):
    """Contrato canónico v1.x que implementa cada adaptador de proveedor de viaje."""

    def obtener_reserva(self, credencial: Mapping[str, str],
                        referencia: str) -> dict[str, Any]: ...

    def traducir_notificacion(self, cabeceras: Mapping[str, str],
                              cuerpo: Any) -> list[dict[str, Any]]: ...

    def sondear(self, credencial: Mapping[str, str],
                desde: str) -> list[dict[str, Any]]: ...

    def detectar_disrupcion(self, cambio: Mapping[str, Any]) -> dict[str, Any] | None: ...
