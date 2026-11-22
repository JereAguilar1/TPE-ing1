"""Compactación de fase 2 de la supresión en el plano analítico (ADR-0030; contrato SQL 1.2).

Desde que llega `CuentaSuprimida`, las vistas de consulta ya excluyen al seudónimo; sus filas
físicas siguen hasta esta compactación. Cada 15 días (si hay algo que compactar), en una sola
transacción:

1. el aporte de esas filas a `hecho_cambio_reserva` se suma al **cubo anónimo**
   `cubo_cambios_anonimo` (por mes, tipo de segmento y tipo de cambio, sin usuario), que los
   analistas ven solo en celdas con k ≥ 50 usuarios (`v_cubo_cambios_anonimo`);
2. se **borran físicamente** sus hechos, sus eventos crudos, el contexto de sus reservas y su fila
   en `dim_usuario`;
3. se marca `compactada_en` en `lista_supresion_analitica`;
4. se registra el **acta**: cantidades y un resumen SHA-256 de los seudónimos (nunca los
   seudónimos), firmada con HMAC-SHA256 con la clave de actas.

Así cada baja se compacta a más tardar 15 días después de llegar (≤ 25 días, dentro de los 30).
Un evento atrasado de un seudónimo ya compactado vuelve a entrar a la próxima compactación.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any

import psycopg

PERIODO = timedelta(days=15)


def _clave_hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def pendientes(conexion: psycopg.Connection) -> list[str]:
    """Los seudónimos suprimidos que todavía tienen filas en el plano analítico."""
    filas = conexion.execute(
        """
        SELECT s.seudonimo_analitico FROM lista_supresion_analitica s
        WHERE EXISTS (SELECT 1 FROM dim_usuario u WHERE u.seudonimo_analitico = s.seudonimo_analitico)
           OR EXISTS (SELECT 1 FROM evento_crudo c WHERE c.seudonimo_analitico = s.seudonimo_analitico)
        ORDER BY s.seudonimo_analitico
        """).fetchall()
    return [f["seudonimo_analitico"] for f in filas]


def corresponde(conexion: psycopg.Connection, ahora: datetime) -> bool:
    """Hay algo que compactar y pasaron 15 días desde la última compactación (o nunca hubo)."""
    ultima = conexion.execute("SELECT MAX(ejecutada_en) AS ultima FROM acta_compactacion").fetchone()
    vencida = ultima["ultima"] is None or ahora.replace(tzinfo=None) - ultima["ultima"] >= PERIODO
    return vencida and bool(pendientes(conexion))


def _reservas_de(conexion: psycopg.Connection, seudonimos: list[str]) -> list[str]:
    """Las claves (hash) de las reservas de esos seudónimos, para borrar su contexto analítico."""
    filas = conexion.execute(
        """
        SELECT COALESCE(carga->'reserva'->>'id', carga->>'reservaId') AS reserva_id
        FROM evento_crudo WHERE seudonimo_analitico = ANY(%s)
        """, (seudonimos,)).fetchall()
    return sorted({_clave_hash(f["reserva_id"]) for f in filas if f["reserva_id"]})


def compactar(conexion: psycopg.Connection, ahora: datetime, clave_de_actas: str) -> dict[str, Any] | None:
    """Compacta todos los seudónimos pendientes y devuelve el acta (o `None` si no había nada)."""
    seudonimos = pendientes(conexion)
    if not seudonimos:
        return None
    momento = ahora.replace(tzinfo=None)
    usuarios = [f["usuario_sk"] for f in conexion.execute(
        "SELECT usuario_sk FROM dim_usuario WHERE seudonimo_analitico = ANY(%s)",
        (seudonimos,)).fetchall()]

    # 1. su aporte, al cubo anónimo
    conexion.execute(
        """
        INSERT INTO cubo_cambios_anonimo (anio, mes, tipo_segmento_id, tipo_de_cambio, cantidad,
                                          usuarios)
        SELECT f.anio, f.mes, h.tipo_segmento_id, h.tipo_de_cambio, SUM(h.cantidad),
               COUNT(DISTINCT h.usuario_sk)
        FROM hecho_cambio_reserva h JOIN dim_fecha f ON f.fecha_id = h.fecha_id
        WHERE h.usuario_sk = ANY(%s)
        GROUP BY f.anio, f.mes, h.tipo_segmento_id, h.tipo_de_cambio
        ON CONFLICT (anio, mes, tipo_segmento_id, tipo_de_cambio) DO UPDATE
            SET cantidad = cubo_cambios_anonimo.cantidad + EXCLUDED.cantidad,
                usuarios = cubo_cambios_anonimo.usuarios + EXCLUDED.usuarios
        """, (usuarios,))

    # 2. borrado físico de sus filas
    reservas = _reservas_de(conexion, seudonimos)
    borradas = 0
    for consulta, parametro in (
        ("DELETE FROM hecho_cambio_reserva WHERE usuario_sk = ANY(%s)", usuarios),
        ("DELETE FROM hecho_viaje WHERE usuario_sk = ANY(%s)", usuarios),
        ("DELETE FROM contexto_reserva_analitico WHERE reserva_clave = ANY(%s)", reservas),
        ("DELETE FROM evento_crudo WHERE seudonimo_analitico = ANY(%s)", seudonimos),
        ("DELETE FROM dim_usuario WHERE usuario_sk = ANY(%s)", usuarios),
    ):
        borradas += conexion.execute(consulta, (parametro,)).rowcount

    # 3. marca en la lista de supresión (la primera compactación de cada seudónimo)
    conexion.execute(
        "UPDATE lista_supresion_analitica SET compactada_en = %s "
        "WHERE seudonimo_analitico = ANY(%s) AND compactada_en IS NULL", (momento, seudonimos))

    # 4. el acta firmada
    resumen = hashlib.sha256("\n".join(seudonimos).encode("utf-8")).hexdigest()
    siguiente = conexion.execute(
        "SELECT COALESCE(MAX(acta_id), 0) + 1 AS siguiente FROM acta_compactacion").fetchone()
    acta = {"acta_id": siguiente["siguiente"], "ejecutada_en": momento,
            "seudonimos": len(seudonimos), "filas_borradas": borradas, "resumen": resumen}
    acta["firma"] = firmar(acta, clave_de_actas)
    conexion.execute(
        """
        INSERT INTO acta_compactacion (acta_id, ejecutada_en, seudonimos, filas_borradas, resumen,
                                       firma)
        VALUES (%(acta_id)s, %(ejecutada_en)s, %(seudonimos)s, %(filas_borradas)s, %(resumen)s,
                %(firma)s)
        """, acta)
    return acta


def firmar(acta: dict[str, Any], clave_de_actas: str) -> str:
    """HMAC-SHA256 de los campos del acta, en un orden fijo."""
    texto = "|".join(str(acta[campo]) for campo in
                     ("acta_id", "ejecutada_en", "seudonimos", "filas_borradas", "resumen"))
    return hmac.new(clave_de_actas.encode("utf-8"), texto.encode("utf-8"), hashlib.sha256).hexdigest()
