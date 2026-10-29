# Iteración 3 — Refinar las estructuras para rendimiento, disponibilidad y escalabilidad

> **Estado:** ✅ Completa · **Fecha:** 2026-10-29 · **Responsable de la iteración:** Ivo Iriarte · **Participantes:** los cuatro integrantes

| Página de esta iteración | Contenido |
|---|---|
| Esta página | Pasos 1, 2, 3, 5 y 6 del método, verificación de presupuestos y modelo de costo |
| [Paso 4 — Conceptos de diseño y alternativas](paso-4-alternativas.md) | Las 9 decisiones de la iteración (D18 a D26), con las alternativas evaluadas y descartadas |
| [Paso 7 — Análisis y kanban de drivers](paso-7-analisis.md) | Verificación del objetivo, criterios de salida, estado de los 56 drivers y transición a la iteración 4 |
| [Pruebas de carga y catálogo de SLOs](pruebas-de-carga-y-slos.md) | Especificaciones ejecutables para QA-02, QA-04 y QA-09, e indicadores por función crítica |

Plan que guió la iteración: [iteracion-3-plan.md](../iteracion-3-plan.md).

---

## Paso 1 — Revisar las entradas

Esta iteración recibe la estructura general de la [iteración 1](../iteracion-1/README.md) **y** el
interior de los elementos diseñado en la [iteración 2](../iteracion-2/README.md). Ese orden no es
intercambiable: no se puede dimensionar una caché ni fijar políticas de replicación o de
cortacircuitos antes de saber qué agregados existen, qué tablas escriben y en qué orden viajan los
eventos.

| Categoría de entrada | Contenido | Dónde está |
|---|---|---|
| **Propósito de diseño** | Diseñar el sistema completo hasta el punto en que un prototipo demuestre la viabilidad frente a los escenarios más riesgosos | [1.1](../../01-analisis-inicial/01-proposito-y-alcance.md#propósito-de-diseño-en-el-sentido-de-add) |
| **Escenarios de atributos de calidad** | **QA-01 a QA-09** entran como foco central: tres de los cinco ASRs del cuadrante `(A, A)` (`QA-01`, `QA-04`, `QA-05`) se cierran acá | [1.4](../../01-analisis-inicial/04-escenarios-de-calidad.md) · [1.8](../../01-analisis-inicial/08-arbol-de-utilidad.md) |
| **Carga derivada y presupuestos** | 3.000 req/s normales (9.000 en disrupción), 45 eventos/s de correo (450 en disrupción), 12 TB operacionales, y los tres presupuestos (800 ms, 300 s, 5 min/mes) | [1.7](../../01-analisis-inicial/07-supuestos-y-carga-derivada.md) |
| **Restricciones** | CON-01…CON-10 y CON-A1…CON-A4 | [1.5](../../01-analisis-inicial/05-restricciones.md) |
| **Inquietudes arquitectónicas** | CRN-03, CRN-04, CRN-08, CRN-09, CRN-12 (pendiente de cierre) **más CRN-13**, que entra ahora | [1.6](../../01-analisis-inicial/06-concerns-arquitectonicos.md) |
| **Productos de las iteraciones 1 y 2** | 13 + 2 elementos, agregados `Reserva` y `Viaje` con observaciones inmutables y fusión determinista (D10, D13), persistencia particionada por `usuario_id` (D12), bandeja de entrada e idempotencia (D14), y el [kanban de 55 drivers](../iteracion-2/paso-7-analisis.md#kanban-de-drivers) con **cinco riesgos residuales** (`R-1`…`R-5`) | [iteración 1](../iteracion-1/README.md) · [iteración 2](../iteracion-2/README.md) |

### Lo que las entradas dicen antes de diseñar nada

Tres conclusiones del cierre de la iteración 2 gobiernan el trabajo de esta iteración:

1. **`R-1` y `R-4` son un único problema arquitectónico, no dos.** La iteración 1 dejó abierta la
   consistencia entre las tres regiones activas (`R-1`), y la iteración 2 demostró que tanto la
   bandeja de entrada de idempotencia (`D14` / `CRN-12`) como la resolución de conflictos (`D13` /
   `CRN-11`) presuponen que todas las escrituras de un mismo usuario se serializan en la misma
   partición (`R-4`). Resolver `CRN-13` con un modelo de propiedad de escritura por usuario y
   conmutación determinista cierra ambos riesgos en el mismo acto.
2. **Los tres presupuestos ya tienen pasos internos reales que contabilizar.** La iteración 2 sumó
   al camino de ingesta la bandeja de entrada, la fusión de observaciones y la publicación por
   *outbox*, y desdobló operativamente a `itinerary` en lectura y escritura (`R-5`). En esta
   iteración la aritmética de `1.7` tiene que verificarse contra esos mecanismos concretos.
3. **La disponibilidad extrema (`99,9884 %`) y la restricción de startup (`CRN-08` / `R-3`) tiran en
   sentidos opuestos.** Tres regiones activas simétricas desde el primer día sostienen `QA-05` pero
   comprometen la viabilidad financiera; replegarse a activo-pasivo ahorra dinero pero destruye
   `QA-05`. La salida no es relajar el atributo ni ignorar el costo, sino diseñar una topología cuya
   **estructura sea invariante** mientras su capacidad se despliega en etapas.

---

## Paso 2 — Establecer el objetivo de la iteración

> **Objetivo de la iteración 3:** refinar las estructuras existentes aplicando tácticas concretas de
> rendimiento, disponibilidad y escalabilidad hasta que los tres presupuestos derivados (latencia,
> frescura y error) cierren tramo por tramo, los escenarios críticos cuenten con especificaciones de
> prueba ejecutables, y queden resueltos los riesgos de consistencia multirregión (`R-1` y `R-4`),
> costo de infraestructura (`R-3`) y acoplamiento operativo de `itinerary` (`R-5`).

### Drivers seleccionados para esta iteración

| Driver | Estado al cerrar la iteración 2 | Qué debe lograr esta iteración |
|---|---|---|
| **QA-01** *(ASR-1)* | 🟨 | Verificar el presupuesto de 300 s incluyendo *inbox*, fusión y *outbox*; fijar intervalos de reconciliación y el objetivo propio de los buzones sin *push* |
| **QA-02** | 🟨 | Estrategia de caché multinivel con invalidación por eventos; verificar el presupuesto de 800 ms y especificar prueba de carga a 3.000 req/s |
| **QA-03** | 🟨 | Diseño del arranque en frío móvil, presupuesto de 1.400 ms en 4G y carga diferida |
| **QA-04** *(ASR-2)* | 🟨 | Contrapresión, colas con prioridad, degradación automática por niveles y autoescalado en ≤ 3 min; prueba ejecutable a 9.000 req/s y 450 ev/s |
| **QA-05** *(ASR-3)* | 🟨 | **Resolver `R-1` y `R-4`:** modelo de consistencia multirregión con pérdida de datos confirmados = 0 y redirección ≤ 60 s |
| **QA-06** | 🟨 | Umbrales de cortacircuitos (apertura ≤ 30 s), mamparos, reintentos con retroceso exponencial y cola persistente de 24 h |
| **QA-07** | ⬜ | Entrega progresiva canaria (radio de impacto ≤ 5 %), reversión automática ≤ 2 min y migraciones compatibles *expand/contract* |
| **QA-08** | 🟨 | Esquema físico de particionamiento y plan de crecimiento de 15 M a 30 M de cuentas sin inactividad ni cambios de contrato |
| **QA-09** | 🟩 | Dimensionar el plano analítico y especificar prueba ejecutable de aislamiento (< 5 % de degradación operacional y frescura ≤ 1 h) |
| **CRN-03** | 🟨 | Instrumentación distribuida, catálogo versionado de SLIs/SLOs y tablero/alertas de presupuesto de error |
| **CRN-04** | ⬜ | Despliegue continuo sin ventanas de mantenimiento |
| **CRN-08** | 🟨 | **Resolver `R-3`:** modelo de costo mensual cuantificado y camino escalonado sin rediseño |
| **CRN-09** | 🟨 | Presupuestos de cuota por proveedor externo, alertas al 70 % y degradación ordenada al alcanzarlos |
| **CRN-12** | 🟨 | Cerrar la garantía de idempotencia asegurando la serialización por usuario entre regiones (`R-4`) |
| **CRN-13** | *nuevo* | **Consistencia de datos entre regiones activas** y comportamiento ante partición o caída regional |
| RF-02, RF-09, RF-14 | 🟨 | Completar las partes operativas pendientes de ingesta de correo, lectura del panel y frescura/dimensionamiento analítico |
| CON-01…CON-10, CON-A1…CON-A4 | — | Se respetan en toda iteración; en especial CON-A4 (< 15 elementos) y CON-09 (equipo de 4) |

### Drivers explícitamente excluidos de esta iteración

| Excluido | Se trata en |
|---|---|
| QA-11 (medición sobre corpus real y cierre de `R-2`), buzones sin OAuth | Iteración 4 y 2da entrega |
| RF-11, RF-13, QA-12 — diseño detallado de compartición con designados sin cuenta y publicación en redes | Iteración 4 |
| QA-13 (detección de extracción masiva, rotación de claves), QA-14 (inventario y supresión de datos personales en ambos planos), CRN-05 | Iteración 4 |
| QA-17 (uso de GPS y degradación sin permiso), QA-18 y CRN-10 (i18n/localización), CON-10 y CRN-15 (normativa y residencia estricta de datos) | Iteración 4 |
| CRN-14 (versionado de contratos publicados) y CON-06 (verificación documental de Opción A y Opción B sobre la estructura) | Iteración 4 |

---

## Paso 3 — Elegir los elementos del sistema a refinar

Esta iteración es transversal: no agrega ningún servicio lógico nuevo al catálogo de 13 + 2
elementos (CON-A4 se mantiene intacto), sino que refina las estructuras dinámicas y de asignación de
cuatro planos completos:

| Ámbito a refinar | Elementos involucrados | Por qué entra en la iteración 3 |
|---|---|---|
| **Camino de lectura y arranque cliente** | `edge`, `api-gateway`, `bff-web`, `bff-mobile`, `itinerary-lectura`, caché regional, `app-movil` | Sostiene `QA-02` (800 ms), `QA-03` (1,4 s) y el Nivel 1 de la frontera de degradación de `QA-04` |
| **Plano de ingesta e integración** | `mail-ingest`, `booking-extraction`, `provider-sync`, *broker* de eventos, `itinerary-escritura`, `notification` | Sostiene `QA-01` (300 s), `QA-04` (450 ev/s), `QA-06` (aislamiento de terceros) y `CRN-09` (cuotas) |
| **Plano de datos operacional y analítico** | Almacén operacional particionado, registro testigo transregional, proyección `panel_usuario`, `event-pipeline`, `analytics-store` | Resuelve `R-1` y `R-4` (`QA-05`, `CRN-13`, `CRN-12`), sostiene `QA-08` (30 M cuentas) y verifica `QA-09` |
| **Infraestructura de despliegue y observabilidad** | Topología en 3 regiones × 3 zonas de disponibilidad, controlador de entrega progresiva, autoescalador, colector de telemetría | Sostiene `QA-07` / `CRN-04` (0 s inactividad), `CRN-03` (presupuesto de error), `CRN-08` (`R-3`) y desacopla operativamente `itinerary` (`R-5`) |

---

## Paso 4 — Elegir los conceptos de diseño

El análisis comparativo completo de alternativas y tácticas está en su propia página:

### → [Paso 4 — Conceptos de diseño y alternativas](paso-4-alternativas.md)

Resumen de las siete decisiones tácticas y estructurales:

| # | Decisión | Concepto de diseño elegido | ADR |
|---|---|---|---|
| D18 | Consistencia de datos entre regiones | Región primaria por usuario con quórum intra-región, testigo transregional para comandos manuales, conmutación con fusión determinista (D10/D13) y lectura causal por sesión | [ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md) |
| D19 | Caché de lectura y arranque móvil | Caché multinivel acotada (estáticos/descriptores en borde + proyección en caché regional invalidada por eventos + instantánea local cifrada y carga diferida en móvil) | [ADR-0019](../../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) |
| D20 | Contrapresión y sobrecarga | Presupuesto de plazo propagado, colas con prioridad por severidad y degradación automática escalonada en tres modos operativos | [ADR-0020](../../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| D21 | Autoescalado y despliegue de `itinerary` | Autoescalado híbrido (predictivo por calendario + reactivo por indicadores adelantados), reducción conservadora y separación operativa `itinerary-lectura` / `itinerary-escritura` | [ADR-0021](../../03-adr/ADR-0021-estrategia-autoescalado.md) |
| D22 | Despliegue sin inactividad y esquemas | Entrega progresiva canaria secuencial por región (5 % inicial) con reversión automática ≤ 75 s gobernada por SLIs y migraciones *expand/contract* | [ADR-0022](../../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) |
| D23 | Particionamiento y crecimiento | Particionamiento por *hash* consistente sobre `usuario_id` (64 particiones lógicas), división en línea, compactación de observaciones y archivo frío | [ADR-0023](../../03-adr/ADR-0023-particionamiento-y-crecimiento.md) |
| D24 | Resiliencia ante terceros y cuotas | Mamparo + cortacircuitos de ventana deslizante (≤ 25 s) + cola persistente (24 h) con retroceso exponencial y *jitter* + presupuesto de cuota por proveedor (80 % tope, 70 % alerta) | [ADR-0024](../../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) |

Y dos decisiones de gobierno operativo y económico (`CRN-03` y `CRN-08` / `R-3`):

| # | Decisión | Concepto de diseño elegido | ADR |
|---|---|---|---|
| D25 | Observabilidad y presupuesto de error | Telemetría unificada OpenTelemetry con `correlation_id`, monitoreo sintético + RUM desde el cliente y gobierno activo del presupuesto de error por tasa de consumo (*burn rate*) | [ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) |
| D26 | Costo y camino escalonado | Despliegue evolutivo en tres etapas sobre la misma arquitectura (2 activas + 1 testigo y analítica pago por consulta → 3 activas asimétricas → escala 30 M) | [ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) |

---

## Paso 5 — Instanciar elementos, asignar responsabilidades y definir parámetros operativos

### 5.1 Topología de datos multirregión y resolución de `R-1` + `R-4` (D18)

Cada usuario tiene asignada una **`región_primaria`** (`AM`, `EU` o `AP`, inicialmente determinada en
el alta según cercanía geográfica / preferencia y codificada como atributo en el token OIDC y en un
directorio global liviano cacheado en `edge` y `api-gateway`) y una **`región_respaldo`**
determinista derivada por `hash(usuario_id)`.

| Operación | Dónde se ejecuta en operación normal | Garantía de durabilidad y consistencia | Qué ocurre si cae la `región_primaria` (`QA-05`) |
|---|---|---|---|
| **Lectura del panel** (`GET /panel`, `GET /panel/resumen`, `GET /viajes/{id}`) | En la **región sana más cercana** al viajero (aunque esté de viaje fuera de su región primaria) | Réplica local alimentada en `< 1 s` (p95). Si el cliente envía `X-Min-Version` superior a la réplica local tras editar, el BFF sirve desde caché de sesión o redirige esa lectura a la región primaria (*read-your-writes*) | El DNS redirige en `≤ 60 s` a la siguiente región sana, que ya posee la proyección replicada |
| **Ingesta automática** (`mail-ingest`, `booking-extraction`, `provider-sync`, `itinerary-escritura`) | En la **`región_primaria`** del dueño del buzón o reserva (los webhooks recibidos en otra región se reenvían por red troncal interna a la cola regional primaria) | Quórum síncrono intra-región en 2 de 3 zonas de disponibilidad (`~3 ms` RTT). **Toda evaluación de `bandeja_entrada` y fusión ocurre en una única partición** (`R-4` cerrado) | La `región_respaldo` asume el arrendamiento de los buzones y particiones afectadas en `≤ 45 s`. Si quedó `< 1 s` sin replicar, la fuente externa reentrega o la reconciliación recupera, y la fusión determinista de observaciones (D10/D13) converge sin duplicados |
| **Comando manual del usuario** (`POST/PUT/DELETE /reservas`, resolución de conflictos, `POST /casos`) | Enrutado por `api-gateway` y `bff-*` a `itinerary-escritura` (o `support-liaison`) de su **`región_primaria`** | Antes de confirmar `200/201`, escribe en quórum local **más un registro testigo síncrono** en la `región_respaldo` (`~70–90 ms` RTT por red troncal; aplica solo a escrituras manuales, `< 15 req/s` globales) | **Pérdida de datos confirmados = 0 (`RPO = 0`).** La `región_respaldo` aplica el registro testigo antes de abrir escrituras locales para esa partición |

**Reintroducción de una región recuperada.** Cuando la región caída vuelve, entra en modo
*sincronización pasiva*: consume el flujo acumulado de observaciones y eventos desde la región que
actuó como respaldo, verifica paridad de versiones por partición y recién entonces vuelve a
anunciarse como sana al enrutamiento global, transfiriendo el liderazgo de partición sin ventana de
doble primario.

---

### 5.2 Caché del camino de lectura y arranque en frío móvil (D19)

Siguiendo la regla de oro de cachear en la menor cantidad de lugares posible para no acumular
desfases invisibles de TTL, se instancian **tres mecanismos con alcances disjuntos**:

| Nivel | Qué almacena | Qué **prohíbe** almacenar | Política de frescura e invalidación |
|---|---|---|---|
| **1. Borde (`edge` / CDN)** | Bundles estáticos versionados de `app-web` e íconos, más `GET /tipos-de-segmento` | **Cualquier dato personal o itinerario** (`Cache-Control: private, no-cache` en rutas autenticadas) | Inmutables con *hash* en el nombre (`max-age=31536000`); descriptores de tipo con `max-age=300, stale-while-revalidate=3600` |
| **2. Caché distribuida regional** (clúster en memoria particionado por `usuario_id` en cada región) | `panel_usuario` (para `bff-web`), `panel_resumen` (≤ 15 KB comprimido para `bff-mobile`) y copia de `preferences` | Estado autoritativo sin respaldo en la base operacional | **Actualización e invalidación guiada por eventos:** `proyeccion-panel` actualiza o invalida la clave en `< 5 ms` ante cada evento de `itinerary` o `preferences`. TTL de seguridad de `15 min`, cabecera `ETag` (`304 Not Modified`) y atributo obligatorio `marcaFrescura` |
| **3. Instantánea local en `app-movil`** | Último `panel_resumen` y detalle del viaje `EnCurso` en almacenamiento local cifrado del dispositivo | Tokens delegados de correo | En reingresos pinta en `≤ 250 ms` mostrando `marcaFrescura` mientras revalida en segundo plano con `If-None-Match` |

#### Desglose del arranque en frío móvil sin caché local (`QA-03`: p75 ≤ 1.400 ms en 4G)

El caso más exigente de `QA-03` ocurre cuando no hay instantánea local previa (primera apertura de
sesión o caché limpia) sobre red 4G (`RTT = 150 ms`, `1,6 Mbps` de bajada, dispositivo gama media):

| Etapa del arranque en frío | Presupuesto p75 | Táctica que lo sostiene |
|---|---|---|
| Inicialización del entorno nativo y *bundle* precompilado (AOT / bytecode) | **320 ms** | Árbol de módulos mínimo en la pantalla inicial; carga diferida de pantallas de edición, archivo, soporte y compartición |
| Resolución DNS + establecimiento TLS 1.3 hacia el `edge` regional | **300 ms** | 1 RTT de transporte + 1 RTT de TLS 1.3 en frío (`2 × 150 ms`; en reconexiones baja a `150 ms` con reanudación de sesión) |
| Procesamiento `edge → api-gateway → bff-mobile → itinerary-lectura` (acierto en caché regional ≥ 92 %) | **180 ms** | Validación local de JWT y lectura de `panel_resumen` precalculado en una única operación |
| Descarga de `GET /panel/resumen` (tope contractual **≤ 15 KB comprimido**) | **225 ms** | `15 KB × 8 bits ÷ 1,6 Mbps = 75 ms` de transmisión + `150 ms` de RTT de la petición HTTP |
| Trazado y pintado del primer marco con los viajes próximos (*First Contentful Paint*) | **155 ms** | Esqueleto liviano sin imágenes remotas bloqueantes; fuentes del sistema e íconos vectoriales empacados |
| **Subtotal estimado (p75 en frío real)** | **1.180 ms** | — |
| **Reserva de margen** | **220 ms** | Absorbe variabilidad de radio 4G o fallo de caché regional (`+46 ms`) |
| **Objetivo `QA-03`** | **≤ 1.400 ms** | Detalles de segmentos pasados y viajes archivados se piden **después** del FCP |

---

### 5.3 Contrapresión, colas con prioridad y niveles de degradación (D20)

#### Camino sincrónico: presupuesto de plazo y límite adaptativo

1. **Propagación del presupuesto restante (`X-Deadline-Ms`).** `api-gateway` estampa el plazo máximo
   de la operación (`800 ms` en modo normal, `1.500 ms` en modo disrupción). Cada salto descuenta el
   tiempo ya transcurrido; si quedan `< 20 ms`, aborta sin iniciar trabajo aguas abajo. Esto evita
   la falla en cascada por agotamiento de hilos ante respuestas lentas.
2. **Límite de tasa en el borde.** Cubeta de fichas (*token bucket*) por usuario autenticado (`60
   req/min`, ráfaga de `20`) y por dirección IP en rutas públicas, devolviendo `429 Too Many
   Requests` con `Retry-After` aleatorio entre `2` y `8 s` para desincronizar reintentos de clientes.
3. **Concurrencia acotada por servicio.** Cada instancia de `bff-*` e `itinerary-lectura` limita sus
   peticiones en vuelo; al superarse la cola corta de entrada (`máx. 50` en espera), rechaza rápido
   (`503`) antes de degradar la latencia de las peticiones que ya se están procesando.

#### Camino asíncrono: tres carriles de prioridad en el *broker*

Para que una avalancha de `450 eventos/s` de correo durante una tormenta (`QA-04`) no atrase las
cancelaciones de vuelos que salen en una hora, los consumidores operan sobre **tres carriles de
prioridad** (todos particionados por `usuario_id` para preservar el orden por usuario dentro de cada
flujo):

| Carril | Qué viaja | Asignación de consumidores | Política bajo sobrecarga |
|---|---|---|---|
| **P1 — Crítico** | `DisrupcionDetectada`, `ReservaObservada` de proveedores, cambios sobre viajes `EnCurso` o con salida `< 48 h` | Grupo dedicado con piso garantizado | **Nunca se frena**; escala primero |
| **P2 — Estándar** | `MensajeDeViajeRecibido` y `ReservaExtraida` de viajes futuros (`Planificado` > 48 h) | Grupo elástico principal | Puede acumular retraso dentro de los 300 s de `QA-01` (y hasta 480 s en el p99) |
| **P3 — Diferible** | Trabajos de reconciliación periódica, transiciones de archivado (`RF-08`) y `event-pipeline` analítico | Capacidad oportunista | **Se pausa o reduce** automáticamente en modo disrupción; los eventos quedan retenidos en el *broker* (7 días) con **cero pérdida** |

#### Máquina automática de modos operativos (`QA-04`)

| Modo | Condición de entrada (regional) | Comportamiento del sistema | Criterio de salida |
|---|---|---|---|
| **Normal** | `< 1.400 req/s` regionales (`< 3.500` globales) y p95 `< 600 ms` | Todos los servicios activos; objetivo `p95 ≤ 800 ms` | — |
| **Pico elevado** | `≥ 1.400 req/s` regionales o retraso en P2 `> 45 s` durante `60 s` | Se posponen sondeos de reconciliación de buzones inactivos; `sharing` desactiva publicaciones a redes sociales (`RF-13`); se extiende `stale-while-revalidate` de la caché regional | Carga `< 1.100 req/s` y p95 `< 500 ms` sostenidos `10 min` |
| **Disrupción masiva** | `≥ 2.500 req/s` regionales (`~7.000–9.000` globales) o p95 `> 900 ms` durante `30 s` | Se pausa `event-pipeline` (la analítica queda con foto fija temporal sin perder eventos); se omiten sugerencias difusas en el alta manual; ante fallo de `itinerary-lectura`, `bff-*` sirve la última proyección en caché con `marcaFrescura`. Se sostiene **p95 ≤ 1.500 ms y 0 actualizaciones perdidas** | Carga `< 1.800 req/s` y colas P1/P2 normalizadas durante `15 min` |

---

### 5.4 Autoescalado híbrido y separación operativa de `itinerary` (D21 · `R-5`)

1. **Despliegue separado `itinerary-lectura` e `itinerary-escritura` (`R-5`).** El módulo `itinerary`
   se empaqueta desde su mismo árbol de código en dos unidades de ejecución independientes:
   `itinerary-lectura` (ejecuta solo `proyeccion-panel` y las rutas `GET` de `api`) e
   `itinerary-escritura` (ejecuta `ingesta`, `fusion`, `reservas`, `viajes`, `gestion-manual`,
   `publicacion` y las rutas de comando). Cada una tiene su propio grupo de réplicas, su propio
   *pool* de conexiones a datos y su propio despliegue canario. Así se elimina el riesgo de que un
   cambio o una ráfaga en la fusión degrade o fuerce a redesplegar la lectura del panel, manteniendo
   CON-A4 (sigue siendo un único elemento lógico de dominio con contratos sin cambios).
2. **Escalado predictivo por calendario.** Treinta minutos antes de las ventanas históricas de pico
   declaradas en el enunciado (domingo-lunes y jueves-viernes en el horario local de cada región),
   el planificador eleva el piso de réplicas al `100 %` de la capacidad de pico normal (`3.000 req/s`
   globales). Los picos previsibles se absorben con **cero latencia de escalado**.
3. **Escalado reactivo por métricas adelantadas y reserva tibia.** Para disrupciones sin aviso
   (`QA-04`), cada clúster regional mantiene un **colchón del 15 % de nodos tibios** con las imágenes
   de contenedor precargadas:
   - Servicios HTTP sin estado (`api-gateway`, `bff-web`, `bff-mobile`, `itinerary-lectura`): escalan
     cuando `peticiones/s por réplica > 65 %` de su capacidad nominal **o** `p95 > 500 ms` durante
     `60 s`. Nuevas réplicas listas en **`≤ 45 s`**; nuevos nodos en **`≤ 150 s`** (cumpliendo
     holgadamente el tope de **`≤ 3 min`** de `QA-04`).
   - Consumidores de eventos (`mail-ingest`, `booking-extraction`, `provider-sync`,
     `itinerary-escritura`, `notification`): escalan por **`edad_mensaje_mas_antiguo > 20 s`** en P1
     (`> 45 s` en P2), con un techo máximo de réplicas acotado por la cantidad de particiones y el
     cupo de conexiones de la base de datos para no saturar el almacén aguas abajo.
4. **Reducción conservadora.** Ventana de estabilización de `15 min` y baja máxima del `20 %` de
   réplicas cada `5 min`, drenando conexiones HTTP y particiones antes de terminar cada contenedor.

---

### 5.5 Despliegue progresivo sin inactividad y migraciones *expand/contract* (D22)

Con `5 minutos/mes` de presupuesto total, `QA-07` exige **0 s de inactividad**, **radio de afectación
≤ 5 %** y **reversión automática ≤ 2 min**:

1. **Secuencia regional escalonada.** Ninguna versión nueva se despliega en las tres regiones al
   mismo tiempo: comienza siempre por la región que se encuentra en valle horario, continúa por la
   segunda tras `15 min` de observación estable al `100 %`, y finaliza en la tercera.
2. **Rampa canaria gobernada por SLIs.** Dentro de cada región:
   - **Paso 1 (`5 %` del tráfico regional, durante `5 min`):** equivale a `~1,7 %` del tráfico
     global, respetando estrictamente el tope de `≤ 5 %` incluso a escala de una sola región.
   - **Evaluación continua cada `30 s`:** el controlador compara tasa de error `5xx`, latencia `p95`
     y excepciones de consumo del canario frente al grupo base. Si dos ventanas consecutivas (`60 s`)
     superan el umbral (`error > 0,5 %` o `p95 > 800 ms`), el enrutador retira el peso del canario a
     `0 %` en `≤ 15 s`: **tiempo total de reversión automática ≤ 75 s (`< 2 min`)**.
   - **Pasos 2 y 3:** `25 %` (`10 min`) → `100 %`, con drenaje ordenado (`SIGTERM` + espera de
     peticiones en curso) que garantiza **0 s de corte**.
3. **Evolución de esquemas y eventos en tres fases (*expand/contract*).** Como durante todo canario y
   toda replicación asíncrona conviven la versión anterior (`N`) y la nueva (`N+1`), se prohíben
   migraciones destructivas o bloqueantes en un único despliegue:
   - *Fase 1 — Expandir:* agregar columnas anulables, tablas o campos opcionales de evento, e índices
     creados de forma concurrente sin bloquear escrituras.
   - *Fase 2 — Migrar:* desplegar el código que escribe ambos formatos y lee con tolerancia
     (*tolerant reader*); rellenar datos históricos en lotes acotados.
   - *Fase 3 — Contraer:* eliminar el campo obsoleto recién en una versión posterior cuando quedan
     cero instancias de `N` activas. Así, revertir un canario en `75 s` nunca choca contra un esquema
     incompatible.

---

### 5.6 Particionamiento físico y plan de crecimiento a 30 M de cuentas (D23)

| Aspecto | Diseño para 15 M de cuentas (actual) | Escala a 30 M de cuentas / 4 M WAU (`QA-08`) |
|---|---|---|
| **Clave de partición** | `hash(usuario_id)` dentro de la `región_primaria` del usuario | **Sin cambios.** Evita puntos calientes y colocaliza `Reserva`, `Segmento`, `Observacion`, `Conflicto`, `Viaje` y `panel_usuario` |
| **Particiones lógicas (*buckets*)** | **64 particiones virtuales** por región asignadas inicialmente a `4` fragmentos físicos (*shards*) | Se reasignan en línea a `8` o `16` fragmentos físicos mediante replicación lógica y conmutación por *bucket*, **sin inactividad ni cambio de contratos** |
| **Particiones del *broker*** | **96 particiones** por tópico regional de dominio (clave `usuario_id`) | Soporta escalar hasta `96` consumidores en paralelo por región sin reparticionar tópicos |
| **Control de volumen operacional** | Compactación asíncrona de `observacion` en viajes archivados `> 90 días` (conserva última por fuente + resumen de auditoría; ahorra `~60 %`) y particionado diario de `bandeja_entrada`/`bandeja_salida` (`DROP PARTITION` tras 14 días) | Detalles de viajes `Archivado > 12 meses` pasan a almacenamiento de objetos frío manteniendo el índice de cabecera en caliente: el conjunto activo en SSD crece con los usuarios activos semanales, no con la historia inerte |

---

### 5.7 Cortacircuitos, reintentos, cola de pendientes y cuotas de terceros (D24)

Instanciación concreta del módulo `proteccion` de `provider-sync`, del `descargador` de `mail-ingest`
y de los adaptadores de `support-liaison`:

| Mecanismo | Parámetro concreto | Justificación contra drivers |
|---|---|---|
| **Tiempos de espera (*timeouts*)** | Conexión `2 s`, lectura `5 s` hacia APIs de viajes y correo; `3 s` hacia agencias (`support-liaison`) | Ninguna llamada a terceros ocurre en el camino de `GET /panel` → **0 lecturas fallidas del panel por caída externa (`QA-06`)** |
| **Mamparo (*bulkhead*)** | Un grupo de hilos/conexiones (`máx. 50` concurrentes por instancia) y cola aislada **por adaptador** | Un proveedor lento jamás agota descriptores ni frena a los otros 11 terceros |
| **Cortacircuitos** | Ventana deslizante de `20 s` (mínimo `10` llamadas): abre si fallos/`5xx`/timeouts `≥ 50 %` o `5` timeouts seguidos → **apertura en ≤ 25 s (`< 30 s` de `QA-06`)**. Permanece `Abierto` `30 s`; en `Semiabierto` lanza `3` sondas | Corta cascadas rápido y prueba la recuperación sola. Errores `400/401/404` **no** cuentan como caída del proveedor ni se reintentan (`401/403` en correo dispara `RequiereReautorizacion`) |
| **Cola persistente de pendientes y reintento** | Retención **24 h** (`cola_pendientes` particionada). Retroceso exponencial `5 s × 2^n` con tope `15 min` y variación aleatoria (*full jitter*) `±30 %` | Recupera el **100 % de las actualizaciones** de una caída de `15 min` (y de hasta `24 h`) sin golpear en manada al proveedor cuando vuelve |
| **Gobierno de cuotas (`CRN-09`)** | Limitador distribuido por `(proveedor, región)` fijado al **80 % de la cuota publicada**; alerta operativa al **70 %**. ante `429`, respeta `Retry-After` sin abrir el cortacircuitos de salud | Reparto interno del cupo: `60 %` webhooks/viajes `EnCurso`, `25 %` viajes futuros, `15 %` reconciliación de fondo (que estira su intervalo automáticamente si el consumo supera el `70 %`) |

#### Intervalos de reconciliación y objetivo de frescura para buzones sin *push* (`ADR-0004` + `QA-01`)

| Tipo de buzón | Proporción estimada | Camino principal | Intervalo de reconciliación escalonada | Objetivo de frescura comprometido |
|---|---|---|---|---|
| **Con soporte *push*** (Gmail `watch`, Microsoft Graph — `E-05`) | ~90 % (`~8,1 M` buzones) | Notificación *push* (`p95 ≤ 5 min`) | Cada **6 h** si tiene viaje activo o en los próximos 14 días; cada **24 h** en reposo (distribuido por `hash(buzon_id)` ≈ `160 sondeos/s` globales) | **p95 ≤ 5 min** (`QA-01` pleno) |
| **Sin soporte *push*** (IMAP genérico — `E-06`) | ~10 % (`~0,9 M` buzones) | `IMAP IDLE` donde el servidor lo admita; si no, verificación liviana de `UIDNEXT` | Cada **15 min** con viaje en curso o salida `< 72 h`; cada **60 min** con viaje planificado; cada **6 h** sin viajes futuros | **p95 ≤ 20 min** en ventana de viaje activo · **p95 ≤ 60 min** en viaje planificado *(excepción documentada en `ADR-0004`)* |

---

### 5.8 Observabilidad, SLIs/SLOs y tablero de presupuesto de error (D25)

1. **Correlación de punta a punta.** `edge` inyecta `traceparent` / `correlation_id` en toda
   petición HTTP y todo productor lo copia al atributo `idDeCorrelacion` del sobre AsyncAPI. Todos
   los servicios emiten registros estructurados JSON (sin datos personales) y métricas/trazas vía
   OpenTelemetry, con muestreo de cola (*tail-based sampling*): `1 %` del tráfico sano y **`100 %`**
   de errores, respuestas `> 800 ms` y ejecuciones en modo degradado.
2. **Medición desde afuera (`ADR-0008` §3).** El cumplimiento de disponibilidad no se calcula solo
   con métricas internas del servidor: se combina telemetría de usuarios reales agregada sin
   identificadores personales (RUM) con **transacciones sintéticas cada `15 s`** ejecutadas desde 6
   puntos geográficos externos contra las tres regiones, capaces de detectar una caída regional en
   `≤ 30 s` incluso en horario de bajo tráfico nocturno.
3. **Gobierno del presupuesto de error (`CRN-03`).** El tablero calcula en tiempo real los minutos
   consumidos de los `5,0 min/mes` desglosados por los tres planos de `ADR-0008`. Alertas por
   velocidad de consumo (*multi-window burn rate*): una tasa `≥ 14,4×` sostenida `5 min` despierta a
   guardia; una tasa `≥ 3×` abre incidente diurno. Si una región o servicio consume **más del 75 %
   (`3,75 min`)** del presupuesto mensual, la tubería de despliegue congela automáticamente los
   cambios funcionales no urgentes y solo habilita parches de confiabilidad o seguridad hasta
   recomponer la ventana móvil de 30 días.

El catálogo completo de SLIs y SLOs está documentado en
[pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md#catálogo-de-indicadores-y-objetivos-de-nivel-de-servicio-slis--slos).

---

### 5.9 Verificación tramo por tramo de los tres presupuestos derivados

Esta sección cierra el criterio de salida 3 de la iteración: cada tramo de los presupuestos fijados
en [1.7 Supuestos y carga derivada](../../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuestos-derivados)
se contrasta contra los mecanismos diseñados en las iteraciones 2 y 3.

#### 1. Presupuesto de latencia web (`QA-02`: p95 ≤ 800 ms a 3.000 req/s)

| Tramo | Presupuesto (`1.7`) | Valor estimado p95 (acierto caché, 92 %) | Valor estimado p95 (fallo caché, 8 %) | Mecanismo que lo sostiene |
|---|---|---|---|---|
| DNS, TLS 1.3 y red cliente → `edge` | 120 ms | **95 ms** | **95 ms** | Borde regional cercano (`D2`) + reutilización de sesión HTTP/2 |
| `edge` + `api-gateway` (enrutamiento, JWT local, cuota) | 60 ms | **35 ms** | **35 ms** | Verificación criptográfica local con claves JWKS en memoria y cubeta local |
| `bff-web` (composición de respuesta) | 70 ms | **45 ms** | **45 ms** | Una sola llamada interna; preferencias leídas de caché regional (`D19`) |
| `itinerary-lectura` (procesamiento sin contención) | 120 ms | **55 ms** | **55 ms** | Despliegue separado de escritura (`D21`) + presupuesto `X-Deadline-Ms` (`D20`) |
| Acceso al almacén de lectura | 80 ms | **12 ms** | **58 ms** | Clúster en memoria (`D19`) o lectura por clave primaria `(usuario_id)` en `panel_usuario` (`D12`, `D23`) |
| Serialización comprimida y red de vuelta | 150 ms | **115 ms** | **115 ms** | Compresión Brotli/gzip (`~35 KB` en red) |
| **Subtotal de camino** | 600 ms | **357 ms** | **403 ms** | — |
| Variabilidad de cola bajo carga pico (p95 a 3.000 req/s) | *(dentro de reserva)* | **+140 ms** | **+165 ms** | Concurrencia acotada al 65 % de utilización por réplica (`D21`) |
| **Total p95 estimado en el borde** | **≤ 800 ms** | **497 ms** | **568 ms** | **Margen libre real: 232 a 303 ms** (supera los 200 ms de reserva de `1.7`) |

#### 2. Presupuesto de frescura (`QA-01`: p95 ≤ 300 s desde la generación en la fuente)

Incluye explícitamente los pasos agregados en la iteración 2 (`bandeja_entrada`, fusión determinista
en `itinerary-escritura` y relevo de `bandeja_salida` / *outbox*):

| Tramo | Presupuesto (`1.7`) | Estimado p95 (pico normal) | Estimado p95 (disrupción `QA-04`, 450 ev/s) | Mecanismo que lo sostiene |
|---|---|---|---|---|
| Fuente externa genera el cambio → webhook recibido | 60 s | **45 s** | **55 s** | Suscripciones *push* renovadas anticipadamente (`D4`, `iteración 2 §5.4`) y receptor liviano (`202 Accepted` en `≤ 15 ms`) |
| Validación, encolado en carril prioritario y despacho | 15 s | **4 s** | **14 s** | Separación en carriles `P1`/`P2`/`P3` (`D20`) y autoescalado por edad de mensaje (`D21`) |
| Token acotado (`identity-access`) + metadatos + descarga | 45 s | **18 s** | **34 s** | Filtro antes del cuerpo, *timeout* `5 s` + 1 reintento con *backoff* de `5 s` (`D24`) y mamparo por proveedor |
| Extracción (`booking-extraction`) + `bandeja_entrada` + fusión (`itinerary-escritura`) | 45 s | **12 s** | **31 s** | Extracción sin estado (`~3 s`) + transacción en partición primaria (`~120 ms`, `D18`/`D23`) + paso de cola |
| Persistencia, relevo de *outbox* e invalidación de caché | 15 s | **4 s** | **8 s** | Lector de `bandeja_salida` cada `500 ms`, actualización de `panel_usuario`/caché (`< 5 ms`, `D19`) y replicación inter-región (`< 1 s`, `D18`) |
| `notification` (canal interno inmediato; *push* externo) | 60 s | **30 s** | **48 s** | Primera notificación crítica sale sin ventana de coalescencia (`iteración 2 §5.7`) |
| **Total p95 extremo a extremo** | **≤ 300 s** | **113 s** | **190 s** | **Margen libre: 187 s en pico normal y 110 s en disrupción** (supera los 60 s de reserva) |

#### 3. Presupuesto de error de disponibilidad (`ADR-0008`: ≤ 5,0 min/mes = 99,9884 %)

| Plano (`ADR-0008`) | Presupuesto asignado | Consumo máximo esperado en escenario de falla | Por qué cierra |
|---|---|---|---|
| **Borde, DNS y enrutamiento global** | **1,0 min/mes** | **≤ 0,43 min/mes** | DNS Anycast y CDN gestionados con SLA `99,999 %`, sin estado y con conmutación automática |
| **Plano de aplicación** (despliegues y fallos de contenedor, `QA-07`) | **2,0 min/mes** | **≈ 0,02 min** ponderados por canario defectuoso (`75 s × 5 % × 1/3 región ≈ 1,25 s` globales) | Mínimo 3 réplicas repartidas en 3 zonas de disponibilidad + reversión automática en `≤ 75 s` (`D22`) + freno al 75 % del presupuesto (`D25`) |
| **Plano de datos y caída regional** (`QA-05`, tope 1,5 min) | **2,0 min/mes** | **1,0 min** ante caída regional completa (`30 s` detección sintética + `30 s` convergencia DNS/promoción de respaldo); **0 s** ante caída de 1 zona de disponibilidad | Quórum 2 de 3 AZs intra-región + promoción automática a `región_respaldo` con registro testigo (`RPO = 0` en comandos confirmados, `D18`). Fallos de terceros consumen **0 min** (`QA-06`, `D24`) |
| **Total mensual** | **5,0 min/mes** | **Holgura positiva en los tres planos** | Verificable en el tablero de `CRN-03` (`D25`) |

---

### 5.10 Modelo de costo mensual y camino escalonado de infraestructura (D26 · `R-3`)

Para resolver `R-3` (`CRN-08`) sin abandonar la arquitectura de `ADR-0001`, `ADR-0002` y `ADR-0003`,
se modela el costo mensual estimado sobre precios públicos de referencia en nube (instancias
reservadas a 1 año para la línea base y capacidad bajo demanda para picos) y se definen **tres
etapas evolutivas que usan exactamente los mismos módulos, contratos y esquemas**:

| Rubro de infraestructura | **Etapa 1 — Lanzamiento** (`≤ 1,5 M` cuentas · `200 K` WAU) | **Etapa 2 — Escala enunciado** (`15 M` cuentas · `2 M` WAU · `3.000 req/s`) | **Etapa 3 — Crecimiento `QA-08`** (`30 M` cuentas · `4 M` WAU · `6.000 req/s`) |
|---|---|---|---|
| **Topología activa** | **2 regiones activas** (`AM`, `EU`) + **3ra región testigo solo datos** (`AP`, sin cómputo de aplicación activo) | **3 regiones activas asimétricas** (`45 % AM · 35 % EU · 20 % AP` en base, elásticas en pico) | **3 regiones activas** con duplicación horizontal de fragmentos |
| Cómputo de aplicación e ingesta (contenedores + funciones episódicas) | USD 1.650 | USD 9.800 | USD 17.900 |
| Plano de datos operacional (base particionada + caché en memoria en regiones) | USD 1.500 | USD 8.400 | USD 15.100 *(compactación + archivo frío)* |
| *Broker* de eventos y transferencia inter-regional | USD 650 | USD 4.100 | USD 7.600 |
| Borde global (DNS con salud, CDN, WAF) y bóveda de secretos | USD 400 | USD 1.900 | USD 3.200 |
| Plano analítico (`event-pipeline` + `analytics-store`) | **USD 250** *(almacenamiento de objetos + motor SQL pago por consulta)* | **USD 2.600** *(capacidad reservada en horario laboral + almacenamiento columnar)* | **USD 4.500** |
| Observabilidad (registros JSON, métricas, trazas muestreadas al 1 %, sondas) | USD 350 | USD 1.700 | USD 2.900 |
| **Total mensual estimado** | **USD 4.800 / mes** | **USD 28.500 / mes** | **USD 51.200 / mes** |
| **Costo unitario por usuario activo semanal (WAU)** | **USD 0,024 / WAU-mes** | **USD 0,0143 / WAU-mes** | **USD 0,0128 / WAU-mes** |

**Dos conclusiones verificables sobre `R-3` y `QA-08`:**

1. **La Etapa 1 reduce en un 83 % el desembolso inicial** respecto de la escala plena (`USD 4.800`
   vs. `USD 28.500/mes`) preservando `QA-05` entre las dos regiones activas, el testigo de datos en
   la tercera y la separación física del plano analítico. Pasar de Etapa 1 a Etapa 2 consiste
   únicamente en cambiar parámetros de infraestructura como código (`replicas_min_ap > 0` y
   modalidad de cómputo de `analytics-store`): **cero código reescrito y cero contratos tocados**.
2. **Al duplicar la plataforma de 15 M a 30 M de cuentas (`2,00×`), el costo crece `1,80×`** (`USD
   28.500 → USD 51.200/mes`), cumpliendo de forma estricta la medida de respuesta de `QA-08` («el
   costo de infraestructura crece a lo sumo de forma lineal con los usuarios activos»).

---

### 5.11 Parámetros iniciales (supuestos a calibrar)

Al igual que en la [sección 5.11 de la iteración 2](../iteracion-2/README.md#511-parámetros-iniciales-supuestos-a-calibrar),
estos umbrales operativos **no modifican ni reemplazan ningún driver inmutable**: son los valores de
partida que vuelven verificable el diseño y se calibran en las pruebas del prototipo.

| Parámetro operativo | Valor inicial | Se calibra con |
|---|---|---|
| Utilización objetivo por réplica HTTP y colchón de nodos tibios | `65 %` nominal · `15 %` reserva tibia | Escenarios `QA-02` y `QA-04` en el prototipo |
| Disparo de autoescalado en consumidores del *broker* | Edad de mensaje `> 20 s` en `P1` · `> 45 s` en `P2` | Prueba de ráfaga `450 ev/s` (`QA-04`) |
| Ventana deslizante del cortacircuitos externo | `20 s` (`mín. 10` llamadas; abre al `50 %` de fallos o `5` *timeouts*) | Tope inmutable `< 30 s` de `QA-06` |
| Tope preventivo de consumo sobre cuota externa | `80 %` máximo · alerta al `70 %` | `CRN-09` según proveedor real |
| Antigüedad para compactar `observacion` y archivar en frío | `> 90 días` (compactación) · `> 12 meses` (objetos fríos) | Curva real de almacenamiento (`QA-08`, `CRN-08`) |
| Muestreo de cola en trazas exitosas rápidas | `1 %` en sanas · `100 %` en errores o lentas | Presupuesto de observabilidad (`D25`, `D26`) |

---

## Paso 6 — Bosquejar vistas y registrar las decisiones de diseño

### Vistas y especificaciones producidas en esta iteración

| Artefacto | Qué muestra o especifica | Enlace |
|---|---|---|
| **Despliegue — nivel 2** | Topología interna de una región en 3 zonas de disponibilidad, separación `itinerary-lectura` / `itinerary-escritura`, replicación multirregión sin `R-1`, tabla de dimensionamiento por componente y políticas de autoescalado | [vista-despliegue-nivel-2](../../04-vistas/vista-despliegue-nivel-2.md) |
| **Pruebas de carga y catálogo de SLOs** | Escenarios `QA-02`, `QA-04` y `QA-09` especificados con perfiles de carga, precondiciones y umbrales verificables de aceptación para la 2da entrega, más el catálogo formal de SLIs/SLOs por función de `ADR-0008` | [pruebas-de-carga-y-slos](pruebas-de-carga-y-slos.md) |

### Decisiones registradas

Nueve ADRs nuevos en formato MADR, todos en estado `aceptado`:
[ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md) ·
[ADR-0019](../../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) ·
[ADR-0020](../../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) ·
[ADR-0021](../../03-adr/ADR-0021-estrategia-autoescalado.md) ·
[ADR-0022](../../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) ·
[ADR-0023](../../03-adr/ADR-0023-particionamiento-y-crecimiento.md) ·
[ADR-0024](../../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) ·
[ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) ·
[ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md)

---

## Paso 7 — Analizar el diseño y revisar el logro del objetivo

### → [Paso 7 — Análisis y kanban de drivers](paso-7-analisis.md)

**Veredicto:** el objetivo de la iteración 3 se alcanzó. Los escenarios `QA-01` a `QA-09` quedan
completamente tratados (`🟩`), los tres presupuestos cierran tramo por tramo con margen positivo, y
quedan resueltos los riesgos `R-1`, `R-3`, `R-4` y `R-5`. Al cierre de esta iteración hay **36 de 56
drivers en 🟩** (eran 19 de 55 en la iteración 2) y **solo 6 en ⬜**, cinco de los cuales son el foco
declarado de la **iteración 4** (más `CON-05` de la 2da entrega). El análisis detecta además una
tensión nueva entre la replicación transregional de contingencia y la residencia estricta de datos
personales (`R-6`), que se entrega documentada como entrada directa a la iteración 4.
