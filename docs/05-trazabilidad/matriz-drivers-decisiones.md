# 5. Matriz de trazabilidad: driver → decisión → vista

Esta matriz es el artefacto que hace verificable a
[QA-16](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-16--trazabilidad-de-una-decisión-al-código)
(«100 % de los drivers referenciados por al menos un ADR») y a CRN-07. Se recorre en los dos
sentidos: desde un driver, para saber qué decisión lo atiende; y desde un elemento del sistema,
para saber por qué existe.

**Estado al cierre de la iteración 3:** **50 de 56 drivers (89 %)** están atendidos por decisiones
arquitectónicas (`36 🟩` completamente tratados + `14 🟨` en refinamiento final). Los **6** restantes en
`⬜` corresponden estrictamente a los 5 drivers reservados para la **iteración 4** (`QA-14`, `QA-17`,
`QA-18`, `CON-10`, `CRN-10`) más `CON-05` (propio de la **2da entrega**), listados en
[huecos de trazabilidad](#huecos-de-trazabilidad).

---

## Driver → decisión

*(Nota: `D10`–`D17` refieren a las decisiones `ADR-0010`–`ADR-0017` documentadas en
[Iteración 2 — Paso 4](../02-proceso-add/iteracion-2/paso-4-alternativas.md)).*

### Requisitos funcionales

| Driver | ADR / decisión que lo atiende | Elemento responsable | Estado |
|---|---|---|---|
| RF-01 Conectar cuenta de correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | `identity-access` | 🟨 |
| RF-02 Obtener mensajes de viaje | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), `D14`, [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | `mail-ingest` | 🟩 |
| RF-03 Extraer y normalizar reservas | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D10`, `D15` | `booking-extraction` | 🟨 |
| RF-04 Filtros y whitelists | `D15` ([iteración 2](../02-proceso-add/iteracion-2/README.md#54-mail-ingest)) | `mail-ingest` | 🟩 |
| RF-05 Sincronizar con proveedores | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D14`, [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | `provider-sync` | 🟨 |
| RF-06 Gestión manual de reservas | `D10`, `D13`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) | `itinerary-escritura` | 🟩 |
| RF-07 Agrupar reservas en viajes | `D10` ([iteración 2](../02-proceso-add/iteracion-2/paso-4-alternativas.md)) | `itinerary-escritura` | 🟨 |
| RF-08 Ciclo de vida del viaje | `D10`, [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md) | `itinerary-escritura`, `preferences` | 🟩 |
| RF-09 Visualizar el panel | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), `D12`, [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | `bff-web`, `bff-mobile`, `itinerary-lectura` | 🟩 |
| RF-10 Notificar actualizaciones | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | `notification` | 🟩 |
| RF-11 Compartir con designados | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md) | `sharing` | 🟨 |
| RF-12 Derivar a la agencia | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | `support-liaison` | 🟨 |
| RF-13 Publicar en redes sociales | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | `sharing` | 🟨 |
| RF-14 Consultas analíticas | [0003](../03-adr/ADR-0003-separacion-planos.md), `D16`, [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | `event-pipeline`, `analytics-store` | 🟩 |
| RF-15 Preferencias del usuario | `D12`, [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | `preferences` | 🟩 |

### Escenarios de atributos de calidad

| Driver | ADR que lo atiende | Vista / especificación donde se ve | Estado |
|---|---|---|---|
| QA-01 Propagación ≤ 5 min | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), `D14`, [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | [C&C N1](../04-vistas/vista-cyc-nivel-1.md#camino-de-ingesta--sostiene-qa-01) · [Iteración 3 §5.9](../02-proceso-add/iteracion-3/README.md#2-presupuesto-de-frescura-qa-01-p95--300-s-desde-la-generación-en-la-fuente) | 🟩 |
| QA-02 Panel web ≤ 800 ms | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 1)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-1--qa-02-carga-pico-sostenida-del-panel-web) | 🟩 |
| QA-03 FCP móvil ≤ 1,4 s | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | [Iteración 3 §5.2](../02-proceso-add/iteracion-3/README.md#desglose-del-arranque-en-frío-móvil-sin-caché-local-qa-03-p75--1400-ms-en-4g) | 🟩 |
| QA-04 Pico de disrupción | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 2)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-2--qa-04-pico-súbito-por-disrupción-masiva) | 🟩 |
| QA-05 Pérdida de una región | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | [Despliegue N2 §5](../04-vistas/vista-despliegue-nivel-2.md#5-recorrido-de-caída-regional-qa-05-con-r-1-y-r-4-cerrados) *(cierra `R-1` y `R-4`)* | 🟩 |
| QA-06 Proveedor externo caído | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) | 🟩 |
| QA-07 Despliegue sin inactividad | [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | [Despliegue N2 §4](../04-vistas/vista-despliegue-nivel-2.md#4-políticas-de-autoescalado-y-entrega-progresiva) | 🟩 |
| QA-08 Crecimiento de la base | [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | [Despliegue N2 §3 y §6](../04-vistas/vista-despliegue-nivel-2.md#6-evolución-por-etapas-sobre-la-misma-topología-d26--cierre-de-r-3) | 🟩 |
| QA-09 Aislar la analítica | [0003](../03-adr/ADR-0003-separacion-planos.md), `D16`, [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) · [Pruebas de carga (Escenario 3)](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-3--qa-09-aislamiento-frente-a-consultas-analíticas-pesadas) | 🟩 |
| QA-10 Proveedor de viaje nuevo | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D17` | [Módulos N1: regla R2](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) | 🟩 |
| QA-11 Formato de correo desconocido | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D15` | [Módulos N1: regla R3](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) | 🟨 ⚠ R-2 |
| QA-12 Solo personas designadas | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | [Contexto: E-03](../04-vistas/vista-contexto.md) | 🟩 |
| QA-13 Custodia de tokens | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | [Módulos N1: regla R5](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) · [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) | 🟨 |
| QA-14 Auditoría de datos personales | — *(iteración 4)* | — | ⬜ |
| QA-15 Nuevo medio de transporte | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D11` | [Módulos N1](../04-vistas/vista-modulos-nivel-1.md) · [Iteración 2](../02-proceso-add/iteracion-2/README.md) | 🟩 |
| QA-16 Trazabilidad al código | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17` | esta matriz | 🟨 |
| QA-17 Contexto de ubicación | — *(iteración 4)* | — | ⬜ |
| QA-18 Región nueva | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) *(topología y `región_primaria` listas; falta localización en iteración 4)* | [Despliegue N2](../04-vistas/vista-despliegue-nivel-2.md) | ⬜ |

### Restricciones

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | [Plan de iteraciones](../00-gestion/plan-de-iteraciones.md) (3 de 4 completas) | 🟨 |
| CON-02 ADRs en MADR | [Plantilla](../03-adr/plantilla-madr.md) y registro en [03-adr](../03-adr/README.md) | 🟩 |
| CON-03 Wiki con evolución y labor | [Bitácora](../00-gestion/bitacora.md), [convenciones](../00-gestion/equipo.md#convenciones-de-trabajo) | 🟩 |
| CON-04 Spec-driven development | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17`, [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) y [especificación de pruebas y SLOs](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md) | 🟨 |
| CON-05 Acotar el prototipo | — *(2da entrega)* | ⬜ |
| CON-06 Alojar el módulo avanzado | [Punto de extensión](../02-proceso-add/iteracion-1/README.md#el-punto-de-extensión-para-la-2da-entrega) *(se verifica en iteración 4)* | 🟨 |
| CON-07 APIs estándar | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | 🟩 |
| CON-08 Autorización explícita del correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | 🟩 |
| CON-09 Equipo de 4 | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | 🟩 |
| CON-10 Normativa de datos personales | — *(iteración 4 · riesgo `R-6`)* | ⬜ |

### Inquietudes arquitectónicas

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CRN-01 Estructura general | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) y toda la iteración 1 | 🟩 |
| CRN-02 Asignar trabajo a 4 personas | [Mapa de responsabilidad](../04-vistas/vista-modulos-nivel-1.md#mapa-de-responsabilidad-por-integrante), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) | 🟩 |
| CRN-03 Presupuesto de error | [0008](../03-adr/ADR-0008-alcance-disponibilidad.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md), [catálogo de SLOs](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#catálogo-de-indicadores-y-objetivos-de-nivel-de-servicio-slis--slos) | 🟩 |
| CRN-04 Despliegue sin inactividad | [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) | 🟩 |
| CRN-05 Secretos y tokens | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) *(rotación y detección en iteración 4)* | 🟨 |
| CRN-06 Pruebas y contratos | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), `D17`, [pruebas de carga especificadas](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md) | 🟩 |
| CRN-07 Trazabilidad | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) y esta matriz | 🟩 |
| CRN-08 Costo de infraestructura | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) *(cierra `R-3`)* | 🟩 |
| CRN-09 Cuotas de terceros | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | 🟩 |
| CRN-10 Internacionalización | — *(iteración 4)* | ⬜ |
| CRN-11 Conflictos entre fuentes | `D13`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) | 🟩 |
| CRN-12 Idempotencia de la ingesta | `D14`, [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) *(cierra `R-4`)* | 🟩 |
| CRN-13 Consistencia entre regiones activas | [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) *(cierra `R-1` y `R-4`)* | 🟩 |

---

## Decisión → drivers (sentido inverso)

| ADR / Decisión | Decisión | Drivers que atiende |
|---|---|---|
| [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) | Microservicios orientados a eventos, granularidad acotada | QA-04, QA-05, QA-09, QA-10, QA-15, RF-10, CON-09, CRN-01, CRN-02, CRN-08 |
| [0002](../03-adr/ADR-0002-despliegue-multirregion.md) | Activo-activo en tres regiones | QA-05, QA-02, QA-03, QA-18, CRN-08 |
| [0003](../03-adr/ADR-0003-separacion-planos.md) | Planos operacional y analítico separados | QA-09, QA-02, QA-04, RF-14 |
| [0004](../03-adr/ADR-0004-obtencion-de-correo.md) | *Push* con reconciliación escalonada | QA-01, QA-04, RF-02, CRN-09, CRN-08 |
| [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) | Un BFF por tipo de cliente | QA-02, QA-03, QA-17, RF-09 |
| [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | Anticorrupción con adaptadores como complementos | QA-10, QA-11, QA-15, QA-06, RF-03, RF-05, CON-07 |
| [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | OIDC, delegación OAuth, lista de designados | QA-12, QA-13, RF-01, RF-11, RF-13, CON-08, CRN-05 |
| [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | Alcance de la medición de disponibilidad | QA-05, QA-06, CRN-03 |
| [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | Contratos como artefactos de primera clase | CON-04, CON-02, QA-16, QA-10, CRN-06, CRN-07 |
| `D10`–`D17` ([Iter. 2](../02-proceso-add/iteracion-2/paso-4-alternativas.md)) | Modelo canónico, tipos extensibles, persistencia híbrida, conflictos, idempotencia, confianza, estrella analítica y pruebas de contrato | RF-02…RF-09, RF-14, RF-15, QA-01, QA-02, QA-09, QA-10, QA-11, QA-15, QA-16, CON-04, CRN-06, CRN-11, CRN-12 |
| [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) | Región primaria por usuario + testigo transregional + fusión ante *failover* + lectura causal | QA-05, CRN-13, CRN-12, CRN-11, QA-02, RF-06 |
| [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | Caché multinivel acotada e instantánea/arranque móvil | QA-02, QA-03, QA-01, RF-09, RF-15, QA-13 |
| [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | Plazo propagado, tres carriles de prioridad y tres modos de degradación | QA-04, QA-01, QA-02, QA-09, RF-10, RF-13 |
| [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) | Autoescalado híbrido + separación operativa `itinerary-lectura` / `itinerary-escritura` | QA-04, QA-02, QA-08, CRN-08, CRN-02, CON-09 |
| [0022](../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) | Entrega progresiva canaria secuencial + reversión automática + *expand/contract* | QA-07, CRN-04, QA-05, CON-04 |
| [0023](../03-adr/ADR-0023-particionamiento-y-crecimiento.md) | Particionamiento `hash(usuario_id)` en `64` *buckets*, división en línea y archivo frío | QA-08, QA-02, CRN-08, RF-08, RF-11 |
| [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | Mamparo, cortacircuitos `≤ 25 s`, `cola_pendientes` 24 h y gobierno de cuotas/IMAP | QA-06, CRN-09, QA-01, RF-02, RF-05, RF-12 |
| [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | OpenTelemetry correlacionado, sondas sintéticas/RUM y alertas por *burn rate* | CRN-03, QA-05, QA-06, QA-07, CON-09 |
| [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | Modelo de costo mensual y evolución en 3 etapas sin rediseño | CRN-08, QA-05, QA-08, QA-09, RF-14, CON-09 |

---

## Elemento → por qué existe

Este es el recorrido que QA-16 mide: «¿por qué existe este elemento?», respondido en menos de 10
minutos.

| Elemento | Existe porque… | ADR |
|---|---|---|
| `edge` | El presupuesto de latencia asigna 120 ms a la red del cliente y sirve estáticos/descriptores sin exponer PII | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) |
| `api-gateway` | Autenticación JWT local, límite de tasa y estampado de `X-Deadline-Ms` antes de tocar el dominio | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| `bff-web` / `bff-mobile` | Los presupuestos de QA-02 (`800 ms`) y QA-03 (`≤ 15 KB`, `1,4 s`) más la lectura causal `X-Min-Version` exigen contratos a medida | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) |
| `itinerary` (`-lectura` / `-escritura`) | Dueño único del modelo canónico; se despliega en dos grupos independientes para aislar lectura e ingesta sin abrir otro microservicio (`R-5`) | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) |
| `identity-access` | QA-13 exige que un único elemento pueda descifrar los tokens de correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) |
| `mail-ingest` | E/S contra terceros con mamparo, cortacircuitos, reconciliación y gobierno de cuota | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) |
| `booking-extraction` | Cómputo sin estado; escala hasta 96 consumidores por región sin tocar base de datos | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0021](../03-adr/ADR-0021-estrategia-autoescalado.md) |
| `provider-sync` | QA-10 y QA-06 exigen aislar cada proveedor con su propio adaptador, cortacircuitos y `cola_pendientes` | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) |
| `sharing` | Compartir con designados y publicar en redes tienen modelos de confianza y degradación distintos | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| `notification` | QA-01 y QA-04 exigen despacho prioritario (`P1`) independiente del panel | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| `support-liaison` | RF-12 requiere armar el caso con contexto del viaje y aislar fallos de agencias | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0024](../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) |
| `preferences` | RF-08, RF-12 y RF-15 necesitan configuración por usuario cacheada regionalmente | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) |
| `event-pipeline` / `analytics-store` | QA-09 exige aislamiento físico y pausa automática en disrupción (`P3`) | [0003](../03-adr/ADR-0003-separacion-planos.md), [0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) |
| `modelo-canonico` | QA-15 exige un punto de extensión del dominio independiente de todo proveedor | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), `D10`, `D11` |
| `contratos` y `especificaciones` | CON-04 exige especificaciones contractuales y pruebas de carga/SLOs verificables | [0009](../03-adr/ADR-0009-contratos-spec-driven.md), [0025](../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) |

---

## Huecos de trazabilidad

Los drivers **sin** ADR específico al cierre de la iteración 3, todos correspondientes a la
**iteración 4** o a la **2da entrega**. Los cinco primeros deben quedar vacíos al cerrar la
iteración 4 (criterio de salida 1 de la
[iteración 4](../02-proceso-add/iteracion-4-plan.md#criterios-de-salida--y-cierre-de-la-1ra-entrega)).

| Driver | Iteración asignada | ADR previsto en plan |
|---|---|---|
| QA-14 *(auditoría y supresión de datos personales)* | 4 | `ADR-0030` |
| QA-17 *(uso de ubicación GPS y degradación sin permiso)* | 4 | `ADR-0033` |
| QA-18 *(localización e idioma al abrir región nueva)* | 4 | `ADR-0032` |
| CON-10 *(normativa de protección y residencia de datos · `R-6`)* | 4 | `ADR-0029`, `ADR-0030`, `ADR-0031` |
| CRN-10 *(internacionalización desde el inicio)* | 4 | `ADR-0032` |
| CON-05 *(acotar el alcance del prototipo)* | 2da entrega | — |
