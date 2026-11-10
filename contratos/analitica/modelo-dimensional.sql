-- =============================================================================
-- Trotamundos — modelo dimensional del plano analítico (analytics-store)
-- Versión de contrato: 1.1
--
-- Trazabilidad:
--   - Esquema en estrella alimentado desde eventos de dominio retenidos crudos: ADR-0016
--     (iteración 2, §5.9). Dos hechos y seis dimensiones.
--   - Separación de planos: ADR-0003. Nada de este esquema referencia tablas del plano
--     operacional (regla R6 de la vista de módulos N1).
--   - Seudónimo en lugar de datos personales: ADR-0016. Lista de supresión y vistas filtradas:
--     ADR-0030 (agregadas en la versión 1.1, iteración 4).
--   - Un tipo de segmento nuevo es una FILA nueva en dim_tipo_segmento, nunca una columna (QA-15).
--
-- SQL ANSI. El producto columnar concreto no forma parte del contrato; las particiones y el
-- formato físico (Parquet) se documentan en la vista de despliegue N2.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Dimensiones
-- -----------------------------------------------------------------------------

CREATE TABLE dim_fecha (
    fecha_id        INTEGER      PRIMARY KEY,   -- AAAAMMDD
    fecha           DATE         NOT NULL,
    anio            SMALLINT     NOT NULL,
    trimestre       SMALLINT     NOT NULL,
    mes             SMALLINT     NOT NULL,
    dia             SMALLINT     NOT NULL,
    dia_semana      SMALLINT     NOT NULL,      -- 1 = lunes
    es_fin_de_semana BOOLEAN     NOT NULL
);

-- Se alimenta del registro de descriptores (contratos/tipos-de-segmento/), no de código.
CREATE TABLE dim_tipo_segmento (
    tipo_segmento_id INTEGER     PRIMARY KEY,
    tipo             VARCHAR(32) NOT NULL,
    version_tipo     INTEGER     NOT NULL,
    rol_en_viaje     VARCHAR(16) NOT NULL,      -- traslado | alojamiento | movilidadLocal
    atributos_dimension VARCHAR(512) NOT NULL,  -- lista declarada en `dimension.atributos` (JSON)
    UNIQUE (tipo, version_tipo)
);

-- Historial de cambios de los proveedores: SCD tipo 2.
CREATE TABLE dim_proveedor (
    proveedor_sk     BIGINT       PRIMARY KEY,
    proveedor_codigo VARCHAR(64)  NOT NULL,
    nombre           VARCHAR(256) NOT NULL,
    tipo_proveedor   VARCHAR(32)  NOT NULL,     -- aerolinea | hotelera | rentadora | ferroviario | autobus | agencia
    pais             CHAR(2),
    vigente_desde    TIMESTAMP    NOT NULL,
    vigente_hasta    TIMESTAMP,                 -- NULL = versión vigente
    es_vigente       BOOLEAN      NOT NULL
);

-- Jerarquía país > ciudad > punto (aeropuerto, estación, hotel).
CREATE TABLE dim_lugar (
    lugar_id         BIGINT       PRIMARY KEY,
    pais             CHAR(2)      NOT NULL,
    ciudad           VARCHAR(128) NOT NULL,
    punto            VARCHAR(256),
    codigo           VARCHAR(16),
    esquema_codigo   VARCHAR(16),               -- IATA | UIC | interno
    zona_horaria     VARCHAR(64)  NOT NULL
);

CREATE TABLE dim_fuente (
    fuente_id        SMALLINT     PRIMARY KEY,
    fuente           VARCHAR(16)  NOT NULL UNIQUE  -- correo | proveedor | manual
);

-- Sin datos personales: solo el seudónimo analítico (ADR-0016, ADR-0030).
CREATE TABLE dim_usuario (
    usuario_sk          BIGINT      PRIMARY KEY,
    seudonimo_analitico VARCHAR(64) NOT NULL UNIQUE,
    region              VARCHAR(2)  NOT NULL,   -- AM | EU | AP
    cohorte_alta        CHAR(7)     NOT NULL    -- AAAA-MM
);

-- -----------------------------------------------------------------------------
-- Hechos
-- -----------------------------------------------------------------------------

-- Transaccional: una fila por evento de reserva (creada, actualizada, cancelada, unificada).
CREATE TABLE hecho_cambio_reserva (
    id_de_evento        CHAR(36)     NOT NULL PRIMARY KEY,  -- idDeEvento del sobre: hace idempotente la carga
    fecha_id            INTEGER      NOT NULL REFERENCES dim_fecha (fecha_id),
    tipo_segmento_id    INTEGER      NOT NULL REFERENCES dim_tipo_segmento (tipo_segmento_id),
    proveedor_sk        BIGINT       REFERENCES dim_proveedor (proveedor_sk),
    lugar_origen_id     BIGINT       REFERENCES dim_lugar (lugar_id),
    lugar_destino_id    BIGINT       REFERENCES dim_lugar (lugar_id),
    fuente_id           SMALLINT     NOT NULL REFERENCES dim_fuente (fuente_id),
    usuario_sk          BIGINT       NOT NULL REFERENCES dim_usuario (usuario_sk),
    tipo_de_cambio      VARCHAR(16)  NOT NULL,   -- creada | actualizada | cancelada | unificada
    cantidad            INTEGER      NOT NULL DEFAULT 1,
    anticipacion_dias   INTEGER,                 -- inicio del primer segmento − fecha del evento
    detalle             VARCHAR(4000)            -- atributos declarados en `dimension.atributos` (JSON)
);

-- Snapshot acumulativo: una fila por viaje, con sus hitos.
CREATE TABLE hecho_viaje (
    viaje_clave             CHAR(64)  NOT NULL PRIMARY KEY,  -- hash del viajeId, no el id operacional
    usuario_sk              BIGINT    NOT NULL REFERENCES dim_usuario (usuario_sk),
    destino_principal_id    BIGINT    REFERENCES dim_lugar (lugar_id),
    fecha_creado_id         INTEGER   NOT NULL REFERENCES dim_fecha (fecha_id),
    fecha_iniciado_id       INTEGER   REFERENCES dim_fecha (fecha_id),
    fecha_completado_id     INTEGER   REFERENCES dim_fecha (fecha_id),
    fecha_archivado_id      INTEGER   REFERENCES dim_fecha (fecha_id),
    reservas                INTEGER   NOT NULL DEFAULT 0,
    segmentos               INTEGER   NOT NULL DEFAULT 0,
    duracion_dias           INTEGER,
    cancelaciones           INTEGER   NOT NULL DEFAULT 0,
    disrupciones            INTEGER   NOT NULL DEFAULT 0,
    conflictos              INTEGER   NOT NULL DEFAULT 0
);

-- -----------------------------------------------------------------------------
-- Supresión de datos personales (versión 1.1, ADR-0030)
-- -----------------------------------------------------------------------------

-- Al recibir `CuentaSuprimida`, event-pipeline inserta el seudónimo al instante.
CREATE TABLE lista_supresion_analitica (
    seudonimo_analitico VARCHAR(64) PRIMARY KEY,
    suprimida_en        TIMESTAMP   NOT NULL,
    compactada_en       TIMESTAMP              -- NULL hasta la compactación quincenal
);

-- Los analistas consultan SOLO estas vistas: excluyen desde el primer minuto a los usuarios
-- suprimidos, aunque sus filas físicas sigan hasta la compactación (≤ 30 días).
CREATE VIEW v_hecho_cambio_reserva AS
SELECT h.*
FROM hecho_cambio_reserva h
JOIN dim_usuario u ON u.usuario_sk = h.usuario_sk
WHERE NOT EXISTS (
    SELECT 1 FROM lista_supresion_analitica s
    WHERE s.seudonimo_analitico = u.seudonimo_analitico
);

CREATE VIEW v_hecho_viaje AS
SELECT h.*
FROM hecho_viaje h
JOIN dim_usuario u ON u.usuario_sk = h.usuario_sk
WHERE NOT EXISTS (
    SELECT 1 FROM lista_supresion_analitica s
    WHERE s.seudonimo_analitico = u.seudonimo_analitico
);

-- -----------------------------------------------------------------------------
-- Consultas de referencia de RF-14 (forman parte del contrato como ejemplos verificables)
-- -----------------------------------------------------------------------------

-- Tendencias: cambios de reserva por mes y tipo de segmento.
-- SELECT f.anio, f.mes, t.tipo, SUM(h.cantidad)
-- FROM v_hecho_cambio_reserva h
-- JOIN dim_fecha f ON f.fecha_id = h.fecha_id
-- JOIN dim_tipo_segmento t ON t.tipo_segmento_id = h.tipo_segmento_id
-- GROUP BY f.anio, f.mes, t.tipo;

-- Destinos: viajes por país y ciudad de destino.
-- SELECT l.pais, l.ciudad, COUNT(*)
-- FROM v_hecho_viaje h
-- JOIN dim_lugar l ON l.lugar_id = h.destino_principal_id
-- GROUP BY l.pais, l.ciudad;

-- Cancelaciones: por proveedor y anticipación.
-- SELECT p.nombre, h.anticipacion_dias, SUM(h.cantidad)
-- FROM v_hecho_cambio_reserva h
-- JOIN dim_proveedor p ON p.proveedor_sk = h.proveedor_sk
-- WHERE h.tipo_de_cambio = 'cancelada'
-- GROUP BY p.nombre, h.anticipacion_dias;
