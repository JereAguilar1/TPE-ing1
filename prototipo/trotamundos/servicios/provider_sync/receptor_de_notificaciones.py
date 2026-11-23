"""Módulo `receptor-de-notificaciones` (iteración 2 §5.5; `provider-sync-webhooks.yaml`, ADR-0020).

Valida la firma `X-Firma` (`firmaWebhook` de `comun.yaml`: HMAC-SHA256 en hexadecimal sobre los
bytes crudos del cuerpo) y decodifica la carga nativa (`application/json` o `application/xml`)
para que el adaptador registrado la traduzca.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


class FirmaInvalida(ValueError):
    """La firma `X-Firma` falta o no coincide con el cuerpo recibido."""


class CargaWebhookInvalida(ValueError):
    """El cuerpo del webhook no es un objeto JSON ni un documento XML válido."""


def firma(cuerpo: bytes, secreto: str) -> str:
    return hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def firma_valida(cuerpo: bytes, recibida: str | None, secreto: str) -> bool:
    """Comparación en tiempo constante para no filtrar la firma carácter por carácter."""
    # En bytes: una cabecera con caracteres no ASCII es una firma inválida, no un error.
    return recibida is not None and hmac.compare_digest(
        firma(cuerpo, secreto).encode("utf-8"), recibida.strip().encode("utf-8", "replace"))


def decodificar_cuerpo(cuerpo: bytes, tipo_contenido: str | None) -> dict[str, Any] | str:
    medio = (tipo_contenido or "application/json").partition(";")[0].strip().lower()
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CargaWebhookInvalida("El cuerpo no está codificado en UTF-8") from error

    if medio in ("application/xml", "text/xml"):
        if not texto.strip():
            raise CargaWebhookInvalida("El cuerpo XML está vacío")
        return texto

    if medio == "application/json" or not medio:
        try:
            datos = json.loads(texto) if texto.strip() else None
        except json.JSONDecodeError as error:
            raise CargaWebhookInvalida("El cuerpo no es JSON válido") from error
        if not isinstance(datos, dict):
            raise CargaWebhookInvalida("El cuerpo JSON del webhook debe ser un objeto")
        return datos

    raise CargaWebhookInvalida(f"Tipo de contenido no soportado: {medio}")
