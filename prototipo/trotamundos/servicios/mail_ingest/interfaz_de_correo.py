"""La «interfaz» que `mail-ingest` expone a los complementos de proveedor de correo (ADR-0006).

Cada proveedor (Gmail, Microsoft Graph, IMAP genérico) se atiende con un complemento en
`complementos/` que implementa `AdaptadorDeCorreo`: la diferencia entre proveedores queda contenida
ahí, como pide la capa de anticorrupción, y el resto de `mail-ingest` no la conoce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SuscripcionFallida(Exception):
    """El proveedor no aceptó crear o renovar la suscripción de avisos."""


@dataclass(frozen=True)
class Suscripcion:
    """Una suscripción de avisos *push* (Gmail `watch`, Graph *subscriptions*)."""

    id: str
    expira_en: datetime


@dataclass(frozen=True)
class Metadatos:
    """Lo que se sabe de un mensaje **antes** de bajar su cuerpo: alcanza para filtrar (RF-04)."""

    id_de_mensaje: str
    remitente: str
    recibido_en: datetime


@dataclass(frozen=True)
class Novedades:
    """Mensajes nuevos desde `cursor` y el cursor desde el que seguir la próxima vez."""

    mensajes: tuple[Metadatos, ...]
    cursor: str | None


class AdaptadorDeCorreo(Protocol):
    """Lo que un complemento de proveedor de correo hace por `mail-ingest`."""

    @property
    def soporta_push(self) -> bool:
        """`False` para IMAP genérico: ese buzón se atiende solo por reconciliación (ADR-0004)."""
        ...

    def suscribir(self, buzon_id: str, ahora: datetime) -> Suscripcion: ...

    def renovar(self, buzon_id: str, suscripcion_id: str, ahora: datetime) -> Suscripcion: ...

    def cancelar(self, buzon_id: str, suscripcion_id: str) -> None: ...

    def novedades(self, buzon_id: str, token: str, cursor: str | None) -> Novedades:
        """Metadatos de los mensajes posteriores a `cursor`, con el token efímero del buzón."""
        ...

    def descargar(self, buzon_id: str, token: str, id_de_mensaje: str) -> bytes:
        """El mensaje completo, en formato RFC 5322."""
        ...
