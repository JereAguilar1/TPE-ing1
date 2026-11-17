"""Proveedor de correo simulado (E-05 con *push*, E-06 IMAP) para el prototipo (ADR-0036).

Guarda en memoria los mensajes de cada buzón, en orden de llegada. Las pruebas le «entregan»
mensajes con `entregar` y después disparan el aviso o la reconciliación, como haría un proveedor
real. El token efímero no se valida acá: lo que se prueba es que `mail-ingest` lo pida siempre a
`identity-access` antes de leer (ADR-0029).
"""

from __future__ import annotations

import email
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parseaddr
from uuid import uuid4

from trotamundos.servicios.mail_ingest.interfaz_de_correo import (
    Metadatos,
    Novedades,
    Suscripcion,
    SuscripcionFallida,
)

# Gmail `watch` vence a los 7 días; Microsoft Graph, antes. Se usa el de Gmail.
VIGENCIA_DE_SUSCRIPCION = timedelta(days=7)


@dataclass
class _Mensaje:
    id: str
    crudo: bytes
    remitente: str
    recibido_en: datetime


class CorreoSimulado:
    """Un proveedor simulado. Con `soporta_push=False` se comporta como IMAP genérico."""

    def __init__(self, soporta_push: bool = True):
        self._soporta_push = soporta_push
        self._buzones: dict[str, list[_Mensaje]] = {}
        self._suscripciones: dict[str, str] = {}
        self._suscripcion_falla = False
        self._cerrojo = threading.Lock()
        self.tokens_usados: list[str] = []

    @property
    def soporta_push(self) -> bool:
        return self._soporta_push

    # --- lo que hace el proveedor por su cuenta (lo usan las pruebas) ----------------------

    def entregar(self, buzon_id: str, crudo: bytes,
                 recibido_en: datetime | None = None) -> str:
        """Llega un mensaje al buzón; devuelve su id en el proveedor."""
        mensaje = email.message_from_bytes(crudo, policy=policy.default)
        with self._cerrojo:
            identificador = f"msg-{uuid4().hex[:12]}"
            self._buzones.setdefault(buzon_id, []).append(_Mensaje(
                identificador, crudo, parseaddr(str(mensaje["From"] or ""))[1].lower(),
                recibido_en or datetime.now(timezone.utc)))
        return identificador

    def suscripcion_de(self, buzon_id: str) -> str | None:
        return self._suscripciones.get(buzon_id)

    def fallar_suscripciones(self, fallan: bool = True) -> None:
        self._suscripcion_falla = fallan

    # --- AdaptadorDeCorreo -------------------------------------------------------------------

    def suscribir(self, buzon_id: str, ahora: datetime) -> Suscripcion:
        if not self._soporta_push:
            raise SuscripcionFallida("Este proveedor no envía avisos: se reconcilia")
        if self._suscripcion_falla:
            raise SuscripcionFallida("El proveedor rechazó la suscripción")
        identificador = f"sus-{uuid4().hex[:12]}"
        self._suscripciones[buzon_id] = identificador
        return Suscripcion(identificador, ahora + VIGENCIA_DE_SUSCRIPCION)

    def renovar(self, buzon_id: str, suscripcion_id: str, ahora: datetime) -> Suscripcion:
        if self._suscripcion_falla or self._suscripciones.get(buzon_id) != suscripcion_id:
            raise SuscripcionFallida("La suscripción ya no existe en el proveedor")
        return Suscripcion(suscripcion_id, ahora + VIGENCIA_DE_SUSCRIPCION)

    def cancelar(self, buzon_id: str, suscripcion_id: str) -> None:
        if self._suscripciones.get(buzon_id) == suscripcion_id:
            del self._suscripciones[buzon_id]

    def novedades(self, buzon_id: str, token: str, cursor: str | None) -> Novedades:
        self.tokens_usados.append(token)
        with self._cerrojo:
            mensajes = list(self._buzones.get(buzon_id, []))
        desde = int(cursor) if cursor else 0
        nuevos = tuple(Metadatos(m.id, m.remitente, m.recibido_en) for m in mensajes[desde:])
        return Novedades(nuevos, str(len(mensajes)))

    def descargar(self, buzon_id: str, token: str, id_de_mensaje: str) -> bytes:
        self.tokens_usados.append(token)
        with self._cerrojo:
            for mensaje in self._buzones.get(buzon_id, []):
                if mensaje.id == id_de_mensaje:
                    return mensaje.crudo
        raise KeyError(id_de_mensaje)
