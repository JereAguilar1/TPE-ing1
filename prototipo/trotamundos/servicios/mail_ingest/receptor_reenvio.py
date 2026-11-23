"""Módulo `receptor-reenvio-verificado` (ADR-0035; vista de módulos de adaptadores).

El servidor de correo entrante propio entrega por HTTP cada mensaje que llega a un alias
`viajes+<token>@ingesta.trotamundos.app`. Antes de aceptarlo se verifica:

1. que el alias sea de un buzón activo;
2. la autenticación del mensaje, que el servidor propio deja en `Authentication-Results` con su
   identificador (`ingesta.trotamundos.app`); las de otros servidores no cuentan, porque las puede
   escribir cualquiera. Hace falta `dkim=pass` y además `spf=pass` o `arc=pass` (el ARC es lo que
   sobrevive a un reenvío automático);
3. que quien reenvió sea el titular del buzón: el remitente del sobre (`Return-Path`) o, si no
   está, el `From`, tiene que coincidir con su correo verificado;
4. si se acepta solo por el ARC (el SPF no pasó), que alguna firma DKIM válida sea del dominio
   del titular (`header.d` o `header.i`, alineación relajada). Sin esto, cualquiera con su propio
   dominio firmado y su propia cadena ARC podía hacerse pasar por el titular.

Lo que no pasa se descarta y queda auditado, sin guardar el contenido del mensaje.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr

import psycopg

AUTENTICADOR = "ingesta.trotamundos.app"
_RESULTADO = re.compile(r"\b(dkim|spf|arc)\s*=\s*([a-z]+)", re.IGNORECASE)
_FIRMANTE = re.compile(r"\bheader\.(?:d=([\w.-]+)|i=[^\s;@]*@([\w.-]+))", re.IGNORECASE)

DDL = (
    """
    CREATE TABLE IF NOT EXISTS reenvio_rechazado (
        id          bigserial   PRIMARY KEY,
        alias       text        NOT NULL,
        motivo      text        NOT NULL,
        recibido_en timestamptz NOT NULL
    );
    """,
)


def resultados(mensaje: EmailMessage) -> dict[str, str]:
    """`{mecanismo: resultado}` de las `Authentication-Results` del servidor propio."""
    encontrados: dict[str, str] = {}
    for cabecera in mensaje.get_all("Authentication-Results") or []:
        autenticador, _, detalle = str(cabecera).partition(";")
        if autenticador.strip().lower() != AUTENTICADOR:
            continue
        for mecanismo, resultado in _RESULTADO.findall(detalle):
            encontrados.setdefault(mecanismo.lower(), resultado.lower())
    return encontrados


def firmantes_dkim(mensaje: EmailMessage) -> set[str]:
    """Los dominios de las firmas DKIM que el servidor propio dio por válidas."""
    dominios: set[str] = set()
    for cabecera in mensaje.get_all("Authentication-Results") or []:
        autenticador, _, detalle = str(cabecera).partition(";")
        if autenticador.strip().lower() != AUTENTICADOR:
            continue
        for resultado in detalle.split(";"):
            if re.match(r"\s*dkim\s*=\s*pass\b", resultado, re.IGNORECASE):
                dominios |= {(d or i).lower() for d, i in _FIRMANTE.findall(resultado)}
    return dominios


def _alineados(firmante: str, dominio: str) -> bool:
    return firmante == dominio or dominio.endswith("." + firmante) or firmante.endswith("." + dominio)


def quien_reenvia(mensaje: EmailMessage) -> str:
    sobre = parseaddr(str(mensaje["Return-Path"] or ""))[1]
    return (sobre or parseaddr(str(mensaje["From"] or ""))[1]).strip().lower()


def motivo_de_rechazo(mensaje: EmailMessage, correo_titular: str | None) -> str | None:
    """`None` si el mensaje se acepta; si no, por qué se rechaza."""
    autenticacion = resultados(mensaje)
    if autenticacion.get("dkim") != "pass" or "pass" not in (autenticacion.get("spf"),
                                                              autenticacion.get("arc")):
        return "autenticacionFallida"
    if not correo_titular or quien_reenvia(mensaje) != correo_titular.strip().lower():
        return "remitenteNoAutorizado"
    if autenticacion.get("spf") != "pass":
        dominio = correo_titular.strip().lower().rpartition("@")[2]
        if not any(_alineados(f, dominio) for f in firmantes_dkim(mensaje)):
            return "autenticacionFallida"
    return None


def id_de_mensaje(mensaje: EmailMessage, crudo: bytes) -> str:
    """El `Message-ID`; si no tiene, un resumen del contenido (el mismo mensaje, el mismo id)."""
    propio = str(mensaje["Message-ID"] or "").strip()
    return propio or f"sha256:{hashlib.sha256(crudo).hexdigest()}"


def auditar_rechazo(conexion: psycopg.Connection, alias: str, motivo: str,
                    ahora: datetime) -> None:
    conexion.execute(
        "INSERT INTO reenvio_rechazado (alias, motivo, recibido_en) VALUES (%s, %s, %s)",
        (alias.strip().lower(), motivo, ahora))
