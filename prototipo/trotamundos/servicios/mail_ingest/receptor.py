"""Módulo `receptor` (vista N2, §3; ADR-0004, ADR-0020; `mail-ingest-webhooks.yaml`).

Liviano a propósito: verifica la firma, encola «buzón con cambios» y responde. No descarga ni
interpreta nada.

La firma `X-Firma` (`firmaWebhook` de `comun.yaml`) es un HMAC-SHA256 en hexadecimal del cuerpo
tal como llegó, con el secreto compartido con el proveedor.
"""

from __future__ import annotations

import hashlib
import hmac


def firma(cuerpo: bytes, secreto: str) -> str:
    return hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def firma_valida(cuerpo: bytes, recibida: str | None, secreto: str) -> bool:
    """Comparación en tiempo constante: la firma no se puede adivinar de a un carácter."""
    # En bytes: una cabecera con caracteres no ASCII es una firma inválida, no un error.
    return recibida is not None and hmac.compare_digest(
        firma(cuerpo, secreto).encode("utf-8"), recibida.strip().encode("utf-8", "replace"))
