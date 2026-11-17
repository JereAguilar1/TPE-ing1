"""Módulo `normalizador` (vista N2, §3): un mensaje RFC 5322 al formato común `MensajeNormalizado`
del contrato AsyncAPI. No interpreta el contenido: eso es de `booking-extraction`.

De las cabeceras pasan solo las que sirven para identificar y fechar el mensaje: el resto (rutas
de entrega, direcciones IP, firmas) son datos que nadie aguas abajo necesita.

Los adjuntos no viajan en el prototipo: el contrato pide una referencia a su ubicación cifrada, y
ese almacenamiento no está en el plan (ver «Decisiones de implementación» en el README).
"""

from __future__ import annotations

import email
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any

from trotamundos.comun.modelo import instante_a_texto

CABECERAS_QUE_PASAN = ("Message-ID", "Date", "From", "To", "Cc", "Reply-To", "Subject")


def leer(crudo: bytes) -> EmailMessage:
    return email.message_from_bytes(crudo, policy=policy.default)  # type: ignore[return-value]


def remitente(mensaje: EmailMessage) -> str:
    return parseaddr(str(mensaje["From"] or ""))[1].strip().lower()


def normalizar(crudo: bytes, recibido_en: datetime | None = None) -> dict[str, Any]:
    """`MensajeNormalizado`. `recibido_en` es cuándo lo recibió el proveedor; si no se sabe, la
    fecha del mensaje y, si tampoco, ahora."""
    mensaje = leer(crudo)
    destinatarios = [direccion.lower() for _, direccion in getaddresses(
        [str(mensaje[c]) for c in ("To", "Cc") if mensaje[c]]) if direccion]
    normalizado: dict[str, Any] = {
        "remitente": remitente(mensaje),
        "recibidoEn": instante_a_texto(recibido_en or _fecha(mensaje)),
        "asunto": str(mensaje["Subject"] or ""),
        "cabeceras": {nombre: str(mensaje[nombre]) for nombre in CABECERAS_QUE_PASAN
                      if mensaje[nombre] is not None},
    }
    if destinatarios:
        normalizado["destinatarios"] = destinatarios
    for clave, subtipo in (("cuerpoTexto", "plain"), ("cuerpoHtml", "html")):
        parte = mensaje.get_body(preferencelist=(subtipo,))
        if parte is not None:
            normalizado[clave] = parte.get_content()
    return normalizado


def _fecha(mensaje: EmailMessage) -> datetime:
    try:
        fecha = parsedate_to_datetime(str(mensaje["Date"]))
        return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
