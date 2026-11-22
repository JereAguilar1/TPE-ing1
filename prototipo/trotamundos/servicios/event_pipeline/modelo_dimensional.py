"""Modelo dimensional del plano analítico (`contratos/analitica/modelo-dimensional.sql`, ADR-0016, ADR-0030).

Ejecuta el esquema en estrella del contrato SQL y proyecta los eventos retenidos en `evento_crudo`
sobre las dimensiones (`dim_fecha`, `dim_tipo_segmento`, `dim_lugar`, `dim_fuente`, `dim_usuario`),
los hechos (`hecho_cambio_reserva`, `hecho_viaje`) y la `lista_supresion_analitica` filtrada por
`v_hecho_cambio_reserva` y `v_hecho_viaje`.

Ningún tipo de segmento concreto aparece en este módulo (regla I4, QA-15): `dim_tipo_segmento` se
alimenta automáticamente de `RegistroDeTipos`.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any, Iterable, Mapping

import psycopg

from trotamundos.comun.contratos import Contratos
from trotamundos.comun.modelo import instante_desde_texto
from trotamundos.comun.tipos_de_segmento import RegistroDeTipos
from trotamundos.servicios.event_pipeline.aterrizaje import EventoCrudo

_CONTRATO_SQL = "analitica/modelo-dimensional.sql"
# Desde aquí, el contrato solo agrega (versión 1.2): se ejecuta también sobre un esquema instalado.
_SECCION_INCREMENTAL = "-- Compactación de fase 2 (versión 1.2, ADR-0030)."
_FUENTES_FIJAS = ((1, "correo"), (2, "proveedor"), (3, "manual"))

DDL_AUXILIAR = (
    """
    CREATE TABLE IF NOT EXISTS contexto_reserva_analitico (
        reserva_clave       char(64) PRIMARY KEY,
        viaje_clave         char(64),
        tipo_segmento_id    integer NOT NULL,
        proveedor_sk        bigint,
        lugar_origen_id     bigint,
        lugar_destino_id    bigint,
        fecha_inicio        date,
        segmentos           integer NOT NULL DEFAULT 1,
        conflictos          integer NOT NULL DEFAULT 0,
        cancelada           boolean NOT NULL DEFAULT false,
        detalle             varchar(4000)
    );
    """,
)


def instalar_modelo_dimensional(conexion: psycopg.Connection, contratos: Contratos,
                                registro_tipos: RegistroDeTipos) -> None:
    """Ejecuta `contratos/analitica/modelo-dimensional.sql` si aún no está instalado en el esquema
    y sincroniza las dimensiones fijas (`dim_fuente` y `dim_tipo_segmento`)."""
    existe = conexion.execute("SELECT to_regclass('dim_fecha') AS tabla").fetchone()
    sql_contrato = (contratos.ruta / _CONTRATO_SQL).read_text(encoding="utf-8")
    if existe is None or existe["tabla"] is None:
        conexion.execute(sql_contrato)
    else:  # un esquema de una versión anterior: se le agrega lo nuevo del contrato
        conexion.execute(sql_contrato[sql_contrato.index(_SECCION_INCREMENTAL):])
    for sentencia in DDL_AUXILIAR:
        conexion.execute(sentencia)
    for fuente_id, nombre in _FUENTES_FIJAS:
        conexion.execute(
            """
            INSERT INTO dim_fuente (fuente_id, fuente)
            VALUES (%s, %s)
            ON CONFLICT (fuente) DO NOTHING
            """,
            (fuente_id, nombre),
        )
    sincronizar_tipos_de_segmento(conexion, registro_tipos)


def sincronizar_tipos_de_segmento(conexion: psycopg.Connection,
                                  registro_tipos: RegistroDeTipos) -> int:
    """Asegura que cada descriptor de `RegistroDeTipos` tenga su fila en `dim_tipo_segmento` (QA-15)."""
    insertados = 0
    for doc in registro_tipos.documentos():
        tipo = str(doc["tipo"])
        version = int(doc["version"])
        existente = conexion.execute(
            "SELECT tipo_segmento_id FROM dim_tipo_segmento WHERE tipo = %s AND version_tipo = %s",
            (tipo, version),
        ).fetchone()
        if existente is not None:
            continue
        max_fila = conexion.execute(
            "SELECT COALESCE(MAX(tipo_segmento_id), 0) AS maximo FROM dim_tipo_segmento"
        ).fetchone()
        nuevo_id = int(max_fila["maximo"]) + 1 if max_fila else 1
        atributos = json.dumps(list(doc["dimension"]["atributos"]), ensure_ascii=False)
        conexion.execute(
            """
            INSERT INTO dim_tipo_segmento (
                tipo_segmento_id, tipo, version_tipo, rol_en_viaje, atributos_dimension
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tipo, version_tipo) DO NOTHING
            """,
            (nuevo_id, tipo, version, str(doc["rolEnViaje"]), atributos),
        )
        insertados += 1
    return insertados


def _clave_hash(identificador: str) -> str:
    return hashlib.sha256(identificador.encode("utf-8")).hexdigest()


def _asegurar_fecha(conexion: psycopg.Connection, instante: datetime | date) -> int:
    f = instante.date() if isinstance(instante, datetime) else instante
    fecha_id = f.year * 10000 + f.month * 100 + f.day
    trimestre = (f.month - 1) // 3 + 1
    dia_semana = f.isoweekday()
    conexion.execute(
        """
        INSERT INTO dim_fecha (
            fecha_id, fecha, anio, trimestre, mes, dia, dia_semana, es_fin_de_semana
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fecha_id) DO NOTHING
        """,
        (fecha_id, f, f.year, trimestre, f.month, f.day, dia_semana, dia_semana >= 6),
    )
    return fecha_id


def _asegurar_usuario(conexion: psycopg.Connection, seudonimo: str, region: str,
                      ocurrido_en: datetime) -> int:
    existente = conexion.execute(
        "SELECT usuario_sk FROM dim_usuario WHERE seudonimo_analitico = %s",
        (seudonimo,),
    ).fetchone()
    if existente is not None:
        return int(existente["usuario_sk"])

    max_fila = conexion.execute(
        "SELECT COALESCE(MAX(usuario_sk), 0) AS maximo FROM dim_usuario"
    ).fetchone()
    nuevo_sk = int(max_fila["maximo"]) + 1 if max_fila else 1
    cohorte = f"{ocurrido_en.year:04d}-{ocurrido_en.month:02d}"
    conexion.execute(
        """
        INSERT INTO dim_usuario (usuario_sk, seudonimo_analitico, region, cohorte_alta)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (seudonimo_analitico) DO NOTHING
        """,
        (nuevo_sk, seudonimo, region[:2], cohorte),
    )
    confirmado = conexion.execute(
        "SELECT usuario_sk FROM dim_usuario WHERE seudonimo_analitico = %s",
        (seudonimo,),
    ).fetchone()
    assert confirmado is not None
    return int(confirmado["usuario_sk"])


def _asegurar_lugar(conexion: psycopg.Connection,
                    lugar: Mapping[str, Any] | None) -> int | None:
    if not isinstance(lugar, Mapping):
        return None
    pais = str(lugar.get("pais") or "AR")[:2]
    nombre = str(lugar.get("nombre") or "Desconocido")[:128]
    codigo = str(lugar["codigo"])[:16] if lugar.get("codigo") else None
    esquema = str(lugar["esquemaDeCodigo"])[:16] if lugar.get("esquemaDeCodigo") else None
    zona = str(lugar.get("zonaHoraria") or "UTC")[:64]

    existente = conexion.execute(
        """
        SELECT lugar_id FROM dim_lugar
        WHERE pais = %s AND ciudad = %s AND COALESCE(codigo, '') = COALESCE(%s, '')
        """,
        (pais, nombre, codigo),
    ).fetchone()
    if existente is not None:
        return int(existente["lugar_id"])

    max_fila = conexion.execute(
        "SELECT COALESCE(MAX(lugar_id), 0) AS maximo FROM dim_lugar"
    ).fetchone()
    nuevo_id = int(max_fila["maximo"]) + 1 if max_fila else 1
    conexion.execute(
        """
        INSERT INTO dim_lugar (
            lugar_id, pais, ciudad, punto, codigo, esquema_codigo, zona_horaria
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (nuevo_id, pais, nombre, nombre, codigo, esquema, zona),
    )
    return nuevo_id


def _fuente_id(conexion: psycopg.Connection, nombre_fuente: str) -> int:
    fila = conexion.execute(
        "SELECT fuente_id FROM dim_fuente WHERE fuente = %s",
        (nombre_fuente,),
    ).fetchone()
    if fila is not None:
        return int(fila["fuente_id"])
    return 1


def _atributos_de(fila: Mapping[str, Any]) -> tuple[str, str, str]:
    """Los atributos que versiona el SCD tipo 2 de `dim_proveedor`."""
    return (fila["nombre"], fila["tipo_proveedor"], (fila["pais"] or "").strip())


def _asegurar_proveedor(conexion: psycopg.Connection, reserva: Mapping[str, Any],
                        segmento: Mapping[str, Any],
                        ocurrido_en: datetime) -> int | None:
    identificadores = reserva.get("identificadores") or []
    emisor = (
        str(identificadores[0]["emisor"])
        if identificadores and isinstance(identificadores[0], Mapping) and identificadores[0].get("emisor")
        else ""
    )
    operador = str(segmento.get("operador") or "").strip()
    codigo = (emisor or operador or "desconocido")[:64]
    nombre = (operador or codigo)[:256]
    prefijo = emisor.partition(":")[0].strip().lower() if ":" in emisor else "operador"
    tipo_prov = (prefijo or "operador")[:32]
    lugar_inicio = segmento.get("inicio", {}).get("lugar") if isinstance(segmento.get("inicio"), Mapping) else None
    pais = str(lugar_inicio.get("pais") or "AR")[:2] if isinstance(lugar_inicio, Mapping) else "AR"

    # SCD tipo 2 (ADR-0016): cada hecho apunta a la versión del proveedor vigente al ocurrir.
    momento = ocurrido_en.replace(tzinfo=None)
    atributos = (nombre, tipo_prov, pais)
    en_su_momento = conexion.execute(
        """
        SELECT proveedor_sk, nombre, tipo_proveedor, pais FROM dim_proveedor
        WHERE proveedor_codigo = %s AND vigente_desde <= %s
          AND (vigente_hasta IS NULL OR %s < vigente_hasta)
        ORDER BY vigente_desde DESC LIMIT 1
        """,
        (codigo, momento, momento),
    ).fetchone()
    if en_su_momento is not None and _atributos_de(en_su_momento) == atributos:
        return int(en_su_momento["proveedor_sk"])
    vigente = conexion.execute(
        "SELECT proveedor_sk, vigente_desde FROM dim_proveedor "
        "WHERE proveedor_codigo = %s AND es_vigente = TRUE",
        (codigo,),
    ).fetchone()
    if vigente is not None and momento < vigente["vigente_desde"]:
        # Un evento atrasado no reescribe la historia: usa la versión de su momento (o la primera).
        return int((en_su_momento or vigente)["proveedor_sk"])
    if vigente is not None:  # cambió un atributo: se cierra la versión vigente y se abre otra
        conexion.execute(
            "UPDATE dim_proveedor SET vigente_hasta = %s, es_vigente = FALSE "
            "WHERE proveedor_sk = %s",
            (momento, vigente["proveedor_sk"]),
        )

    max_fila = conexion.execute(
        "SELECT COALESCE(MAX(proveedor_sk), 0) AS maximo FROM dim_proveedor"
    ).fetchone()
    nuevo_sk = int(max_fila["maximo"]) + 1 if max_fila else 1
    vigente_desde = momento
    conexion.execute(
        """
        INSERT INTO dim_proveedor (
            proveedor_sk, proveedor_codigo, nombre, tipo_proveedor,
            pais, vigente_desde, vigente_hasta, es_vigente
        )
        VALUES (%s, %s, %s, %s, %s, %s, NULL, TRUE)
        """,
        (nuevo_sk, codigo, nombre, tipo_prov, pais, vigente_desde),
    )
    return nuevo_sk


def _tipo_segmento(conexion: psycopg.Connection, registro_tipos: RegistroDeTipos,
                   tipo: str, version_tipo: int) -> tuple[int, list[str]]:
    fila = conexion.execute(
        """
        SELECT tipo_segmento_id, atributos_dimension
        FROM dim_tipo_segmento
        WHERE tipo = %s AND version_tipo = %s
        """,
        (tipo, version_tipo),
    ).fetchone()
    if fila is None:
        sincronizar_tipos_de_segmento(conexion, registro_tipos)
        fila = conexion.execute(
            """
            SELECT tipo_segmento_id, atributos_dimension
            FROM dim_tipo_segmento
            WHERE tipo = %s AND version_tipo = %s
            """,
            (tipo, version_tipo),
        ).fetchone()
    assert fila is not None
    return int(fila["tipo_segmento_id"]), list(json.loads(fila["atributos_dimension"]))


def _extraer_detalle_dimension(segmento: Mapping[str, Any],
                               atributos: Iterable[str]) -> str:
    detalle_seg = segmento.get("detalle") if isinstance(segmento.get("detalle"), Mapping) else {}
    extraido: dict[str, Any] = {}
    for attr in atributos:
        if attr in segmento:
            extraido[attr] = segmento[attr]
        elif isinstance(detalle_seg, Mapping) and attr in detalle_seg:
            extraido[attr] = detalle_seg[attr]
    return json.dumps(extraido, ensure_ascii=False, sort_keys=True)


def proyectar_evento(conexion: psycopg.Connection, crudo: EventoCrudo,
                     registro_tipos: RegistroDeTipos) -> None:
    """Actualiza las dimensiones, los hechos o la lista de supresión a partir de un `EventoCrudo`."""
    if crudo.tipo == "CuentaSuprimida":
        suprimida_en = instante_desde_texto(str(crudo.carga["suprimidaEn"])).replace(tzinfo=None)
        conexion.execute(
            """
            INSERT INTO lista_supresion_analitica (seudonimo_analitico, suprimida_en)
            VALUES (%s, %s)
            ON CONFLICT (seudonimo_analitico) DO NOTHING
            """,
            (crudo.seudonimo_analitico, suprimida_en),
        )
        return

    usuario_sk = _asegurar_usuario(
        conexion, crudo.seudonimo_analitico, crudo.region, crudo.ocurrido_en
    )
    fecha_evento_id = _asegurar_fecha(conexion, crudo.ocurrido_en)

    if crudo.tipo == "ReservaActualizada":
        _proyectar_reserva_actualizada(
            conexion, crudo, registro_tipos, usuario_sk, fecha_evento_id
        )
    elif crudo.tipo == "ReservaCancelada":
        _proyectar_reserva_cancelada(conexion, crudo, usuario_sk, fecha_evento_id)
    elif crudo.tipo == "ViajeArmado":
        _proyectar_viaje_armado(conexion, crudo, usuario_sk, fecha_evento_id)
    elif crudo.tipo == "ViajeCompletado":
        _proyectar_hito_viaje(
            conexion, crudo.carga["viajeId"], "fecha_completado_id",
            instante_desde_texto(str(crudo.carga["completadoEn"])),
        )
    elif crudo.tipo == "ViajeArchivado":
        _proyectar_hito_viaje(
            conexion, crudo.carga["viajeId"], "fecha_archivado_id",
            instante_desde_texto(str(crudo.carga["archivadoEn"])),
        )
    elif crudo.tipo == "ConflictoDeFuentesDetectado":
        _proyectar_conflicto(conexion, crudo, usuario_sk)


def _proyectar_conflicto(conexion: psycopg.Connection, crudo: EventoCrudo,
                         usuario_sk: int) -> None:
    reserva_clave = _clave_hash(str(crudo.carga["reservaId"]))
    fila = conexion.execute(
        """
        UPDATE contexto_reserva_analitico
        SET conflictos = conflictos + 1
        WHERE reserva_clave = %s
        RETURNING viaje_clave
        """,
        (reserva_clave,),
    ).fetchone()
    if fila is not None and fila["viaje_clave"] is not None:
        conexion.execute(
            "UPDATE hecho_viaje SET conflictos = conflictos + 1 WHERE viaje_clave = %s",
            (fila["viaje_clave"],),
        )
    else:
        conexion.execute(
            "UPDATE hecho_viaje SET conflictos = conflictos + 1 WHERE usuario_sk = %s",
            (usuario_sk,),
        )


def _proyectar_reserva_actualizada(conexion: psycopg.Connection, crudo: EventoCrudo,
                                   registro_tipos: RegistroDeTipos,
                                   usuario_sk: int, fecha_evento_id: int) -> None:
    reserva = crudo.carga["reserva"]
    cambios = crudo.carga.get("cambios") or []
    if crudo.carga.get("unificadaCon"):
        tipo_cambio = "unificada"
    elif crudo.carga.get("creada"):
        tipo_cambio = "creada"
    else:
        tipo_cambio = "actualizada"

    if cambios and isinstance(cambios[-1], Mapping) and cambios[-1].get("fuente"):
        nombre_fuente = str(cambios[-1]["fuente"])
    else:
        fuentes = reserva.get("fuentes") or ["manual"]
        nombre_fuente = str(fuentes[-1])
    fuente_id = _fuente_id(conexion, nombre_fuente)

    segmentos_reserva = reserva["segmentos"]
    segmento = segmentos_reserva[0]
    ultimo_segmento = segmentos_reserva[-1]
    tipo_seg_id, atributos = _tipo_segmento(
        conexion, registro_tipos, str(segmento["tipo"]), int(segmento["versionTipo"])
    )
    proveedor_sk = _asegurar_proveedor(conexion, reserva, segmento, crudo.ocurrido_en)
    origen_id = _asegurar_lugar(conexion, segmento["inicio"].get("lugar"))
    destino_id = _asegurar_lugar(conexion, ultimo_segmento["fin"].get("lugar"))
    inicio_dt = instante_desde_texto(str(segmento["inicio"]["instante"]))
    anticipacion = (inicio_dt.date() - crudo.ocurrido_en.date()).days
    detalle_json = _extraer_detalle_dimension(segmento, atributos)
    cantidad_segmentos = len(segmentos_reserva)

    reserva_clave = _clave_hash(str(reserva["id"]))
    conexion.execute(
        """
        INSERT INTO contexto_reserva_analitico (
            reserva_clave, tipo_segmento_id, proveedor_sk, lugar_origen_id,
            lugar_destino_id, fecha_inicio, segmentos, detalle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (reserva_clave) DO UPDATE
        SET tipo_segmento_id = EXCLUDED.tipo_segmento_id,
            proveedor_sk = EXCLUDED.proveedor_sk,
            lugar_origen_id = EXCLUDED.lugar_origen_id,
            lugar_destino_id = EXCLUDED.lugar_destino_id,
            fecha_inicio = EXCLUDED.fecha_inicio,
            segmentos = EXCLUDED.segmentos,
            detalle = EXCLUDED.detalle
        """,
        (
            reserva_clave,
            tipo_seg_id,
            proveedor_sk,
            origen_id,
            destino_id,
            inicio_dt.date(),
            cantidad_segmentos,
            detalle_json,
        ),
    )

    conexion.execute(
        """
        INSERT INTO hecho_cambio_reserva (
            id_de_evento, fecha_id, tipo_segmento_id, proveedor_sk,
            lugar_origen_id, lugar_destino_id, fuente_id, usuario_sk,
            tipo_de_cambio, cantidad, anticipacion_dias, detalle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
        ON CONFLICT (id_de_evento) DO NOTHING
        """,
        (
            crudo.evento_id,
            fecha_evento_id,
            tipo_seg_id,
            proveedor_sk,
            origen_id,
            destino_id,
            fuente_id,
            usuario_sk,
            tipo_cambio,
            anticipacion,
            detalle_json,
        ),
    )


def _proyectar_reserva_cancelada(conexion: psycopg.Connection, crudo: EventoCrudo,
                                 usuario_sk: int, fecha_evento_id: int) -> None:
    reserva_clave = _clave_hash(str(crudo.carga["reservaId"]))
    ctx = conexion.execute(
        """
        UPDATE contexto_reserva_analitico
        SET cancelada = TRUE
        WHERE reserva_clave = %s
        RETURNING *
        """,
        (reserva_clave,),
    ).fetchone()
    if ctx is not None:
        tipo_seg_id = int(ctx["tipo_segmento_id"])
        proveedor_sk = ctx["proveedor_sk"]
        origen_id = ctx["lugar_origen_id"]
        destino_id = ctx["lugar_destino_id"]
        anticipacion = (
            (ctx["fecha_inicio"] - crudo.ocurrido_en.date()).days
            if ctx["fecha_inicio"] is not None
            else None
        )
        detalle = ctx["detalle"]
        viaje_asociado = ctx["viaje_clave"]
    else:
        primero = conexion.execute(
            "SELECT tipo_segmento_id FROM dim_tipo_segmento ORDER BY tipo_segmento_id LIMIT 1"
        ).fetchone()
        assert primero is not None
        tipo_seg_id = int(primero["tipo_segmento_id"])
        proveedor_sk = None
        origen_id = None
        destino_id = None
        anticipacion = None
        detalle = "{}"
        viaje_asociado = None

    fuente_id = _fuente_id(conexion, str(crudo.carga["fuente"]))
    conexion.execute(
        """
        INSERT INTO hecho_cambio_reserva (
            id_de_evento, fecha_id, tipo_segmento_id, proveedor_sk,
            lugar_origen_id, lugar_destino_id, fuente_id, usuario_sk,
            tipo_de_cambio, cantidad, anticipacion_dias, detalle
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'cancelada', 1, %s, %s)
        ON CONFLICT (id_de_evento) DO NOTHING
        """,
        (
            crudo.evento_id,
            fecha_evento_id,
            tipo_seg_id,
            proveedor_sk,
            origen_id,
            destino_id,
            fuente_id,
            usuario_sk,
            anticipacion,
            detalle,
        ),
    )
    viaje_clave = (
        _clave_hash(str(crudo.carga["viajeId"]))
        if crudo.carga.get("viajeId")
        else viaje_asociado
    )
    if viaje_clave:
        conexion.execute(
            "UPDATE hecho_viaje SET cancelaciones = cancelaciones + 1 WHERE viaje_clave = %s",
            (viaje_clave,),
        )


def _proyectar_viaje_armado(conexion: psycopg.Connection, crudo: EventoCrudo,
                            usuario_sk: int, fecha_evento_id: int) -> None:
    viaje_clave = _clave_hash(str(crudo.carga["viajeId"]))
    destino_id = _asegurar_lugar(conexion, crudo.carga.get("destinoPrincipal"))
    desde_dt = instante_desde_texto(str(crudo.carga["desde"]))
    hasta_dt = instante_desde_texto(str(crudo.carga["hasta"]))
    duracion = max(0, (hasta_dt.date() - desde_dt.date()).days)
    reserva_ids = [str(rid) for rid in (crudo.carga.get("reservaIds") or ())]
    reservas = len(reserva_ids)
    claves_reservas = [_clave_hash(rid) for rid in reserva_ids]

    total_segmentos = reservas
    total_conflictos = 0
    total_cancelaciones = 0
    if claves_reservas:
        conexion.execute(
            """
            UPDATE contexto_reserva_analitico
            SET viaje_clave = %s
            WHERE reserva_clave = ANY(%s)
            """,
            (viaje_clave, claves_reservas),
        )
        agregado = conexion.execute(
            """
            SELECT COALESCE(SUM(segmentos), 0) AS segs,
                   COALESCE(SUM(conflictos), 0) AS confs,
                   COALESCE(SUM(CASE WHEN cancelada THEN 1 ELSE 0 END), 0) AS cancs
            FROM contexto_reserva_analitico
            WHERE reserva_clave = ANY(%s)
            """,
            (claves_reservas,),
        ).fetchone()
        if agregado is not None and int(agregado["segs"]) > 0:
            total_segmentos = int(agregado["segs"])
            total_conflictos = int(agregado["confs"])
            total_cancelaciones = int(agregado["cancs"])

    fecha_iniciado_id = (
        _asegurar_fecha(conexion, desde_dt)
        if crudo.carga.get("estado") == "EnCurso"
        else None
    )

    conexion.execute(
        """
        INSERT INTO hecho_viaje (
            viaje_clave, usuario_sk, destino_principal_id,
            fecha_creado_id, fecha_iniciado_id,
            reservas, segmentos, duracion_dias, cancelaciones, conflictos
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (viaje_clave) DO UPDATE
        SET destino_principal_id = COALESCE(EXCLUDED.destino_principal_id, hecho_viaje.destino_principal_id),
            fecha_iniciado_id = COALESCE(EXCLUDED.fecha_iniciado_id, hecho_viaje.fecha_iniciado_id),
            reservas = EXCLUDED.reservas,
            segmentos = GREATEST(hecho_viaje.segmentos, EXCLUDED.segmentos),
            duracion_dias = EXCLUDED.duracion_dias,
            cancelaciones = GREATEST(hecho_viaje.cancelaciones, EXCLUDED.cancelaciones),
            conflictos = GREATEST(hecho_viaje.conflictos, EXCLUDED.conflictos)
        """,
        (
            viaje_clave,
            usuario_sk,
            destino_id,
            fecha_evento_id,
            fecha_iniciado_id,
            reservas,
            total_segmentos,
            duracion,
            total_cancelaciones,
            total_conflictos,
        ),
    )


def _proyectar_hito_viaje(conexion: psycopg.Connection, viaje_id: str,
                          columna_fecha: str, instante: datetime) -> None:
    if columna_fecha not in ("fecha_completado_id", "fecha_archivado_id"):
        raise ValueError(f"Columna de hito no permitida: {columna_fecha}")
    fecha_id = _asegurar_fecha(conexion, instante)
    viaje_clave = _clave_hash(str(viaje_id))
    conexion.execute(
        f"UPDATE hecho_viaje SET {columna_fecha} = %s WHERE viaje_clave = %s",
        (fecha_id, viaje_clave),
    )


def reconstruir_desde_crudos(conexion: psycopg.Connection,
                             crudos: Iterable[EventoCrudo],
                             registro_tipos: RegistroDeTipos) -> None:
    """Confirmación de ADR-0016: regenerar los hechos desde los eventos crudos produce el mismo
    resultado sin tocar el plano operacional."""
    conexion.execute("DELETE FROM hecho_cambio_reserva")
    conexion.execute("DELETE FROM hecho_viaje")
    conexion.execute("DELETE FROM contexto_reserva_analitico")
    sincronizar_tipos_de_segmento(conexion, registro_tipos)
    for crudo in crudos:
        proyectar_evento(conexion, crudo, registro_tipos)


# --- Consultas analíticas de referencia (RF-14, contratos/analitica/modelo-dimensional.sql) ---

def consultar_tendencias(conexion: psycopg.Connection) -> list[dict[str, Any]]:
    """Cambios de reserva por año, mes y tipo de segmento sobre `v_hecho_cambio_reserva`."""
    filas = conexion.execute(
        """
        SELECT f.anio, f.mes, t.tipo, SUM(h.cantidad) AS total
        FROM v_hecho_cambio_reserva h
        JOIN dim_fecha f ON f.fecha_id = h.fecha_id
        JOIN dim_tipo_segmento t ON t.tipo_segmento_id = h.tipo_segmento_id
        GROUP BY f.anio, f.mes, t.tipo
        ORDER BY f.anio, f.mes, t.tipo
        """
    ).fetchall()
    return [
        {"anio": int(f["anio"]), "mes": int(f["mes"]), "tipo": str(f["tipo"]), "total": int(f["total"])}
        for f in filas
    ]


def consultar_destinos(conexion: psycopg.Connection) -> list[dict[str, Any]]:
    """Viajes por país y ciudad de destino sobre `v_hecho_viaje`."""
    filas = conexion.execute(
        """
        SELECT l.pais, l.ciudad, COUNT(*) AS viajes
        FROM v_hecho_viaje h
        JOIN dim_lugar l ON l.lugar_id = h.destino_principal_id
        GROUP BY l.pais, l.ciudad
        ORDER BY viajes DESC, l.pais, l.ciudad
        """
    ).fetchall()
    return [
        {"pais": str(f["pais"]), "ciudad": str(f["ciudad"]), "viajes": int(f["viajes"])}
        for f in filas
    ]


def consultar_cancelaciones(conexion: psycopg.Connection) -> list[dict[str, Any]]:
    """Cancelaciones por proveedor y anticipación sobre `v_hecho_cambio_reserva` (RF-14)."""
    filas = conexion.execute(
        """
        SELECT p.nombre, h.anticipacion_dias, SUM(h.cantidad) AS total
        FROM v_hecho_cambio_reserva h
        JOIN dim_proveedor p ON p.proveedor_sk = h.proveedor_sk
        WHERE h.tipo_de_cambio = 'cancelada'
        GROUP BY p.nombre, h.anticipacion_dias
        ORDER BY p.nombre, h.anticipacion_dias
        """
    ).fetchall()
    return [
        {
            "nombre": str(f["nombre"]),
            "anticipacionDias": int(f["anticipacion_dias"]) if f["anticipacion_dias"] is not None else None,
            "total": int(f["total"]),
        }
        for f in filas
    ]
