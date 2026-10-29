# Especificación de pruebas de carga y catálogo de SLIs / SLOs

> **Iteración:** 3 · **Drivers:** `QA-01`, `QA-02`, `QA-04`, `QA-05`, `QA-06`, `QA-07`, `QA-09`, `CRN-03`, `CON-04`
> **ADRs que realiza:** [ADR-0008](../../03-adr/ADR-0008-alcance-disponibilidad.md) · [ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md) · [ADR-0020](../../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) · [ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md)

En esta **1ra entrega** el alcance es exclusivamente arquitectónico y documental (el código y la
ejecución corresponden al prototipo de la **2da entrega**). Siguiendo el enfoque *spec-driven*
([ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md)) y el criterio de salida 5 del
[plan de la iteración 3](../iteracion-3-plan.md#criterios-de-salida), este documento deja
formalizados de manera no ambigua:

1. El **catálogo de indicadores y objetivos de nivel de servicio (`SLIs / SLOs`)** por cada función
   crítica de [ADR-0008](../../03-adr/ADR-0008-alcance-disponibilidad.md) y las reglas de gobierno
   del presupuesto de error (`CRN-03`).
2. La **especificación formal de las pruebas de carga y aislamiento** para los escenarios `QA-02`,
   `QA-04` y `QA-09` (precondiciones, perfil de tráfico por etapas, mezcla de operaciones y predicados
   cuantitativos de aceptación/rechazo), lista para instrumentarse directamente en la 2da entrega sin
   reinterpretar requisitos.

---

## Catálogo de indicadores y objetivos de nivel de servicio (SLIs / SLOs)

Realiza la confirmación exigida por [ADR-0008](../../03-adr/ADR-0008-alcance-disponibilidad.md#confirmación)
y [ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md): cada función tiene un
indicador medido desde el borde/cliente y una regla explícita sobre si consume o no el presupuesto
mensual de **`5,0 minutos`** (`99,9884 %`).

### 1. Funciones críticas incluidas en el presupuesto de 5 min/mes (`ADR-0008` §1)

Una petición cuenta como **exitosa** únicamente si devuelve un código no-`5xx` **dentro del umbral de
latencia** correspondiente: responder en `30 segundos` cuenta como falla.

| ID | Función crítica | SLI (medido en `edge` + sondas sintéticas + RUM) | SLO (ventana móvil 30 días) | Reparto de presupuesto |
|---|---|---|---|---|
| `SLO-01` | Autenticación (`POST /sesiones`, validación OIDC) | Proporción de autenticaciones válidas respondidas en `< 500 ms` sin error `5xx` | **≥ 99,9884 %** | Consume de los `5,0 min/mes` |
| `SLO-02` | Consulta del panel web (`GET /panel`) | Proporción de peticiones respondidas sin `5xx` con `latencia ≤ 800 ms` en modo normal (`≤ 1.500 ms` en modo disrupción `QA-04`) | **≥ 99,9884 %** de éxito · `p95 ≤ 800 ms` · `p99 ≤ 1.500 ms` | Consume de los `5,0 min/mes` |
| `SLO-03` | Resumen móvil y detalle de viaje (`GET /panel/resumen`, `GET /viajes/{id}`) | Proporción de respuestas sin `5xx` dentro de presupuesto, con cuerpo `panel/resumen ≤ 15 KB` comprimido; RUM de FCP móvil | **≥ 99,9884 %** de éxito · `FCP p75 ≤ 1.400 ms` en 4G (`QA-03`) | Consume de los `5,0 min/mes` |
| `SLO-04` | Gestión manual de reservas (`POST/PUT/DELETE /reservas`) | Proporción de mutaciones confirmadas con testigo transregional sin `5xx` en `< 1.000 ms` y `0` pérdida ante caída regional | **≥ 99,9884 %** de éxito · **`RPO = 0`** en comandos confirmados (`QA-05`) | Consume de los `5,0 min/mes` |

### 2. Funciones con objetivo propio que **no** consumen los 5 min/mes

| ID | Capacidad | SLI | SLO | Comportamiento cuando falla un tercero (`QA-06`) |
|---|---|---|---|---|
| `SLO-05` | Frescura de propagación *push* / *webhook* (`QA-01`) | `t_visible_en_panel - t_generado_en_fuente` para proveedores con *push* | **p95 ≤ 300 s (5 min)** · **p99 ≤ 480 s (8 min)** | Si el tercero cae, se abre el cortacircuitos en `≤ 25 s`, se encola hasta `24 h` y el panel exhibe `marcaFrescura` sin restar disponibilidad |
| `SLO-06` | Frescura de buzones IMAP sin *push* (`ADR-0004`) | `t_visible_en_panel - t_recibido_en_buzon` en cuentas IMAP genéricas | **p95 ≤ 20 min** (viaje activo `< 72 h`) · **p95 ≤ 60 min** (viaje planificado) | Escalonado adaptativo dentro del `80 %` de cuota |
| `SLO-07` | Emisión de notificaciones críticas (`RF-10`) | Tiempo desde `ReservaCancelada` / `DisrupcionDetectada` hasta entrega a pasarela *push* / canal interno | **99,5 %** entregadas a pasarela en `≤ 60 s` (canal interno: `100 %` inmediato) | Reintento por canal alternativo (correo) si falla el proveedor *push* (`E-15`) |
| `SLO-08` | Plano analítico (`RF-14`, `QA-09`) | Latencia de consultas SQL y atraso del último micro-lote cargado en `analytics-store` | **p95 ≤ 30 s** de consulta · **frescura ≤ 60 min** (en operación normal) | En modo `Disrupción masiva` (`D20`), `event-pipeline` se pausa deliberadamente reteniendo eventos en el *broker* |

### 3. Reglas de alerta por velocidad de consumo (*burn rate*) y freno de despliegue

| Nivel | Condición sobre el presupuesto mensual (5,0 min) | Ventana corta / larga | Acción automática y humana |
|---|---|---|---|
| **Crítica (guardia 24×7)** | Velocidad de consumo **≥ 14,4×** (agotaría el mes en ~50 h; equivale a perder ~2 % del presupuesto en 1 h) | `5 min` y `1 h` simultáneas | Alerta inmediata a guardia; si hay un canario activo (`D22`), **reversión automática en ≤ 75 s** |
| **Alta (horario hábil)** | Velocidad de consumo **≥ 3,0×** (agotaría el mes en 10 días) | `30 min` y `6 h` simultáneas | Apertura automática de ticket prioritario y diagnóstico por plano (`borde: 1,0 min` / `aplicación: 2,0 min` / `datos: 2,0 min`) |
| **Gobierno de entregas** | Consumo acumulado en 30 días **> 75 % (> 3,75 min)** | Ventana móvil 30 d | **Congelamiento automático** de despliegues funcionales; solo se habilitan correcciones de confiabilidad y seguridad |

---

## Especificación de las tres pruebas de carga verificables

### Factor de escala para el prototipo de la 2da entrega (`CON-05`)

Cada especificación se parametriza por un factor declarativo $k \in (0, 1]$ (`k = 1,0` representa la
escala nominal del enunciado de `3.000` / `9.000 req/s`; en el entorno acotado del prototipo de la
2da entrega se fija $k$ proporcional a los recursos asignados conservando **exactamente los mismos
multiplicadores de ráfaga `1× → 3×` y `1× → 10×`, las mismas duraciones de ventana y los mismos
umbrales de latencia, aislamiento y cero pérdida**).

---

### Escenario 1 — `QA-02`: Carga pico sostenida del panel web

| Campo de especificación | Definición verificable |
|---|---|
| **Escenario de origen** | [QA-02](../../01-analisis-inicial/04-escenarios-de-calidad.md) — lectura del panel web en horario pico semanal |
| **Precondiciones de datos** | Universo poblado con cuentas distribuidas uniformemente en los `64` *buckets* (`hash(usuario_id)`), media de `2` viajes vigentes y `8` reservas por usuario activo; caché regional en régimen operativo |
| **Mezcla de operaciones** | `85 %` `GET /panel` (cabeceras `Authorization: Bearer <jwt>`, `Accept-Encoding: br, gzip`; `30 %` incluyen `If-None-Match` con `ETag` previo) + `15 %` `GET /viajes/{id}` |
| **Perfil temporal de carga** | **Etapa 1 (calentamiento):** rampa lineal `0 → 3.000 · k req/s` en `2 min`.<br/>**Etapa 2 (meseta evaluada):** **`3.000 · k req/s`** constantes durante **`15 min`**. <br/>**Etapa 3 (drenaje):** descenso `3.000 · k → 0 req/s` en `1 min`. |
| **Criterios de aceptación (predicados de paso/fallo)** | 1. `latencia_extremo_a_extremo(GET /panel).p95 ≤ 800 ms`<br/>2. `latencia_extremo_a_extremo(GET /panel).p99 ≤ 1.500 ms`<br/>3. `tasa_error_http_5xx_o_timeout < 0,1 %` (`< 0,001`)<br/>4. `tasa_acierto_cache_regional ≥ 90 %`<br/>5. `100 %` de las respuestas `200 OK` incluyen los campos contractuales `marcaFrescura`, cabecera `ETag` y `Cache-Control: private, no-cache` |

---

### Escenario 2 — `QA-04`: Pico súbito por disrupción masiva

| Campo de especificación | Definición verificable |
|---|---|
| **Escenario de origen** | [QA-04](../../01-analisis-inicial/04-escenarios-de-calidad.md) *(ASR-2)* — tormenta o huelga sin aviso previo que triplica lecturas y multiplica por diez los eventos entrantes |
| **Precondiciones del entorno** | Clúster regional en modo `Normal` sin precalentamiento manual; autoescalador híbrido (`D21`) y máquina de modos de degradación (`D20`) activos; cada evento inyectado porta un `idempotency_key` único trazable |
| **Mezcla simultánea** | **Flujo A (lectura síncrona):** `GET /panel` y `GET /panel/resumen`.<br/>**Flujo B (ingesta asíncrona):** inyección de *webhooks* firmados en `POST /webhooks/correo` y `POST /webhooks/proveedor` (`40 %` sobre viajes `EnCurso` → carril `P1`; `60 %` sobre viajes `Planificado` → carril `P2`). |
| **Perfil temporal de carga** | **Fase 1 (base pico normal, `5 min`):** `3.000 · k req/s` de lectura + `45 · k eventos/s` de ingesta.<br/>**Fase 2 (salto abrupto en `30 s`, sostenido `30 min`):** **`9.000 · k req/s`** de lectura + **`450 · k eventos/s`** de ingesta.<br/>**Fase 3 (convergencia post-ráfaga, `5 min`):** retorno a carga base y auditoría de completitud de eventos inyectados. |
| **Criterios de aceptación (predicados de paso/fallo)** | 1. `latencia_panel_durante_disrupcion.p95 ≤ 1.500 ms`<br/>2. `tiempo_autoescalado ≤ 180 s (3 min)` desde el inicio del salto hasta estabilizar réplicas nuevas y `p95 < 1.200 ms`<br/>3. **`actualizaciones_perdidas == 0`** y **`actualizaciones_duplicadas == 0`** al finalizar la Fase 3 (`100 %` de los `idempotency_key` inyectados reflejados en `panel_usuario`)<br/>4. Transición automática verificada `Normal → Pico elevado → Disrupción masiva` (pausa efectiva de `event-pipeline` en carril `P3` y desactivación de publicación a redes en `sharing`) y recuperación automática tras `15 min` de carga normalizada |

---

### Escenario 3 — `QA-09`: Aislamiento frente a consultas analíticas pesadas

| Campo de especificación | Definición verificable |
|---|---|
| **Escenario de origen** | [QA-09](../../01-analisis-inicial/04-escenarios-de-calidad.md) — ejecución de consultas analíticas pesadas sobre historia multianual durante el pico operacional |
| **Precondiciones de datos** | `analytics-store` poblado con serie histórica representativa (`3 años` de hechos `hecho_cambio_reserva` y `hecho_viaje`, particionada por mes); `event-pipeline` activo alimentando micro-lotes |
| **Perfil temporal y estímulo** | **Fase A (línea base sin interferencia, `5 min`):** plano operacional sometido a `3.000 · k req/s` de lectura + `45 · k ev/s` de ingesta; se registra `p95_operacional_base`.<br/>**Fase B (interferencia analítica concurrente, `10 min`):** se mantiene exactamente la misma carga operacional mientras `10` sesiones concurrentes del equipo de datos ejecutan en bucle continuo consultas OLAP pesadas (agregación global de destinos por trimestre, tasa de cancelaciones por proveedor sobre 36 meses y distribución por `dim_tipo_segmento`); se registra `p95_operacional_con_analitica`. |
| **Criterios de aceptación (predicados de paso/fallo)** | 1. **Degradación operacional relativa `< 5 %`:** $\dfrac{\text{p95}_{\text{con\_analitica}} - \text{p95}_{\text{base}}}{\text{p95}_{\text{base}}} < 0{,}05$<br/>2. `latencia_consulta_analitica.p95 ≤ 30 s`<br/>3. `frescura_ultimo_lote_analitico ≤ 3.600 s (1 h)`<br/>4. `0` conexiones de red desde el motor analítico hacia los nodos del almacén operacional OLTP |
