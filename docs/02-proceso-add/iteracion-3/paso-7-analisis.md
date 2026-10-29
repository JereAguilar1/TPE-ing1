# Iteración 3 · Paso 7 — Análisis del diseño y revisión del objetivo

El paso 7 de ADD es el control de honestidad del método: verifica con números qué objetivos y
criterios de salida se alcanzaron, revisa si las nuevas decisiones comprometieron algún ASR previo,
actualiza el kanban de drivers y deja explícito qué pasa a la última iteración.

---

## Revisión del objetivo de la iteración

> **Objetivo declarado:** refinar las estructuras existentes aplicando tácticas concretas de
> rendimiento, disponibilidad y escalabilidad hasta que los tres presupuestos derivados (latencia,
> frescura y error) cierren tramo por tramo, los escenarios críticos cuenten con especificaciones de
> prueba ejecutables, y queden resueltos los riesgos de consistencia multirregión (`R-1` y `R-4`),
> costo de infraestructura (`R-3`) y acoplamiento operativo de `itinerary` (`R-5`).

### ¿Se cumplen los criterios de salida del plan?

| # | Criterio del [plan de la iteración 3](../iteracion-3-plan.md#criterios-de-salida) | Veredicto | Evidencia |
|---|---|---|---|
| 1 | **`R-1` resuelto** (y junto con él **`R-4`**): hay una decisión de consistencia entre regiones que satisface `QA-05` con cero pérdida de datos confirmados, registrada en un ADR | ✅ | [D18](paso-4-alternativas.md#d18--modelo-de-consistencia-de-datos-entre-regiones-r-1--r-4--crn-13) y [ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md): `región_primaria` por usuario + testigo transregional en comandos manuales (`RPO = 0`) + fusión determinista ante *failover* |
| 2 | **`R-3` resuelto**: hay un modelo de costo y un camino escalonado que no exige rediseñar la estructura | ✅ | [Sección 5.10 del README](README.md#510-modelo-de-costo-mensual-y-camino-escalonado-de-infraestructura-d26--r-3) y [ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md): tres etapas desde `USD 4.800/mes` hasta `USD 51.200/mes` sobre los mismos módulos y contratos |
| 3 | Los **tres presupuestos** (latencia, frescura y error) tienen cada tramo justificado con un número | ✅ | [Sección 5.9 del README](README.md#59-verificación-tramo-por-tramo-de-los-tres-presupuestos-derivados): latencia web `497–568 ms ≤ 800 ms`; FCP móvil `1.180 ms ≤ 1.400 ms`; frescura `113–190 s ≤ 300 s`; presupuesto de error `< 5,0 min/mes` |
| 4 | **`QA-01` a `QA-09` están en 🟩**, o el motivo de no estarlo está documentado | ✅ con salvedad honesta | Los nueve quedan en 🟩 a nivel de diseño arquitectónico; la validación empírica sobre tráfico ejecutado corresponde al prototipo de la 2da entrega, y la excepción de buzones IMAP sin *push* queda acotada con su propio SLO (`≤ 20 min` en viaje activo) |
| 5 | Los escenarios **`QA-02`, `QA-04` y `QA-09`** existen como especificación de prueba ejecutable | ✅ | Documentados con precondiciones, perfil de etapas y predicados cuantitativos de aceptación en [Pruebas de carga y catálogo de SLOs](pruebas-de-carga-y-slos.md) |

---

## ¿Los cinco ASRs quedan satisfechos por el diseño?

Tres de los cinco escenarios del cuadrante `(Alto, Alto)` tenían su cierre previsto en esta
iteración (`ASR-1`, `ASR-2`, `ASR-3`); se verifica además que ninguna táctica introducida debilite a
los otros dos (`ASR-4`, `ASR-5`).

| ASR | Estado tras iteración 2 | Efecto de la iteración 3 | Veredicto |
|---|---|---|---|
| **ASR-1** `QA-01` — propagación ≤ 5 min | Habilitado en papel | Contabilizados `bandeja_entrada`, fusión y *outbox* (`113 s` p95 normal, `190 s` en disrupción); carriles prioritarios `P1`/`P2` evitan bloqueo por correo frío; reconciliación e IMAP sin *push* especificados | ✅ **Satisfecho en diseño** (se mide en prototipo) |
| **ASR-2** `QA-04` — pico de disrupción | Habilitado sin políticas | Tres modos automáticos de degradación (`D20`), autoescalado híbrido con reserva tibia del 15 % listo en `≤ 150 s < 3 min` (`D21`) y especificación formal del escenario en [pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md#escenario-2--qa-04-pico-súbito-por-disrupción-masiva) | ✅ **Satisfecho en diseño** |
| **ASR-3** `QA-05` — pérdida de región | ⚠️ Habilitado con riesgos `R-1` y `R-4` | **Cerrados `R-1` y `R-4`** (`D18`): detección sintética `≤ 30 s` (`D25`), redirección `≤ 60 s`, promoción de `región_respaldo` y testigo síncrono en comandos manuales (`RPO = 0`). Introduce el matiz normativo `R-6` para la iteración 4 | ✅ **Satisfecho en diseño** |
| **ASR-4** `QA-11` — formato desconocido | Mitigado con 3 bandas (`R-2` abierto) | El carril de ingesta y los límites de tasa no alteran las bandas de confianza ni fuerzan descartes silenciosos | ✅ Sin regresión (cierra en iteración 4 / prototipo) |
| **ASR-5** `QA-13` — custodia de tokens | Habilitado | La caché regional (`D19`) y los registros de OpenTelemetry (`D25`) prohíben explícitamente almacenar tokens o datos personales; `identity-access` sigue siendo el único custodio | ✅ Sin regresión (se refina en iteración 4) |

### ¿Se respetan las restricciones?

| Restricción | Cómo la satisface esta iteración |
|---|---|
| `CON-01` (ADD ≥ 4 iteraciones) | 3 de 4 iteraciones completas, trazables paso a paso |
| `CON-02` (ADRs en MADR) | 9 ADRs nuevos (`ADR-0018` a `ADR-0026`) con alternativas descartadas y criterio de confirmación |
| `CON-04` (*spec-driven*) | Catálogo formal de SLIs/SLOs y especificaciones verificables de pruebas de carga redactadas antes del prototipo de la 2da entrega |
| `CON-09` / `CON-A4` (4 personas, < 15 elementos) | **Cero servicios lógicos nuevos** (se mantiene en 13 + 2); `itinerary` se separa en dos despliegues del mismo código (`D21`), cerrando `R-5` |
| `CON-10` (normativa de datos personales) | La `región_primaria` por usuario (`D18`) deja lista la base estructural para la residencia de datos de la iteración 4, y se señala `R-6` sobre el testigo transregional |

---

## Precisiones sobre iteraciones previas

Ninguna decisión de las iteraciones 1 y 2 se revierte ni se contradice. Tres puntos que aquellas
habían dejado explícitamente delegados quedan ahora cerrados:

1. **Cierre del pendiente de `ADR-0004` (buzones sin *push*).** Queda fijado el intervalo adaptativo
   (`15 min` en viaje activo, `60 min` en viaje planificado, `6 h` en reposo) y el objetivo propio de
   frescura (`p95 ≤ 20 min` en viaje activo) para el ~10 % de cuentas IMAP genéricas.
2. **Materialización del ajuste 3 de la iteración 2 (`itinerary` lectura/escritura).** Lo que la
   iteración 2 declaró como intención queda instanciado en la [vista de despliegue nivel 2](../../04-vistas/vista-despliegue-nivel-2.md)
   con dimensionamiento, *pools* de conexión y políticas de escalado independientes (`D21`).
3. **Cierre de `CRN-12` (idempotencia).** La iteración 2 dejó `CRN-12` en `🟨` porque su bandeja de
   entrada requería que todos los eventos de un usuario pasaran por una misma partición (`R-4`). Con
   `D18`, esa precondición se cumple en operación normal y la fusión determinista cubre la ventana de
   conmutación regional, por lo que `CRN-12` pasa a `🟩`.

### Verificación del riesgo propio de la iteración

El [plan de la iteración 3](../iteracion-3-plan.md#riesgo-propio-de-esta-iteración) advertía que, si
resolver `R-1` exigía convertir las entidades de dominio en estructuras convergentes puras (CRDT), se
produciría **retrabajo sobre el modelo canónico de la iteración 2**. La elección de `D18`
([ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md)) evita por completo ese
retrabajo: en operación normal las escrituras de cada usuario se serializan en su `región_primaria`,
y en la ventana acotada de conmutación regional basta exactamente con la propiedad que `D10` y `D13`
ya habían diseñado en la iteración 2 (`Observacion` solo agregable con consolidación determinista por
precedencia). **Retrabajo sobre la iteración 2: cero.**

---

## Kanban de drivers

Estado de los **56** drivers al cierre de la iteración 3: los 55 de la iteración 2 más **`CRN-13`**
(consistencia entre regiones activas), que entra y se resuelve en esta iteración. `CRN-14` y `CRN-15`
entrarán en la iteración 4 tal como prevé su plan.

- ⬜ **No tratado** — ninguna decisión tomada lo aborda todavía.
- 🟨 **Parcialmente tratado** — hay decisiones que lo habilitan, pero falta refinamiento en la iteración 4 o calibración en el prototipo.
- 🟩 **Completamente tratado** — las decisiones arquitectónicas lo satisfacen y tienen criterio verificable.

La columna **Δ** muestra el cambio respecto del cierre de la [iteración 2](../iteracion-2/paso-7-analisis.md#kanban-de-drivers).

### Requisitos funcionales

| Driver | Estado | Δ | Justificación | Iteración que lo completa |
|---|---|---|---|---|
| RF-01 Conectar cuenta de correo | 🟨 | = | Falta revocación masiva (`QA-13`), buzones sin OAuth (`ADR-0035`) y normativa (`CON-10`) | 4 |
| RF-02 Obtener mensajes de viaje | 🟩 | 🟨→🟩 | Cerrados los intervalos de reconciliación, las cuotas por proveedor (`D24`) y el presupuesto de `QA-01` | — |
| RF-03 Extraer y normalizar reservas | 🟨 | = | Falta cerrar el flujo al usuario ante formato desconocido y medir sobre corpus real (`R-2`) | 4, 2da entrega |
| RF-04 Filtros y whitelists | 🟩 | = | Completo desde la iteración 2 | — |
| RF-05 Sincronizar con proveedores | 🟨 | = | Completados cortacircuitos, reintentos y cola de 24 h (`D24`); falta versionado del contrato de adaptador (`CRN-14`) | 4 |
| RF-06 Gestión manual de reservas | 🟩 | = | Completo desde la iteración 2; `D18` asegura además `RPO = 0` y *read-your-writes* | — |
| RF-07 Agrupar reservas en viajes | 🟨 | = | Los parámetros heurísticos se calibran con datos en el prototipo | 2da entrega |
| RF-08 Ciclo de vida del viaje | 🟩 | = | Completo desde la iteración 2 (la supresión legal corresponde a `QA-14` / `CON-10`) | — |
| RF-09 Visualizar el panel | 🟩 | 🟨→🟩 | Cerrados caché multinivel, arranque móvil en frío y carga diferida (`D19`) | — |
| RF-10 Notificar actualizaciones | 🟩 | = | Completo desde la iteración 2; protegido ahora por carril prioritario `P1` (`D20`) | — |
| RF-11 Compartir con designados | 🟨 | = | Fuera del alcance de esta iteración | 4 |
| RF-12 Derivar a la agencia | 🟨 | = | Resiliencia cubierta por `D24`; falta verificación documental de heterogeneidad | 4 |
| RF-13 Publicar en redes sociales | 🟨 | = | Definida su degradación bajo pico (`D20`); el resumen sin datos sensibles se cierra en la iteración 4 | 4 |
| RF-14 Consultas analíticas | 🟩 | 🟨→🟩 | Dimensionado el almacén en las 3 etapas (`D26`), verificada frescura ≤ 1 h (micro-lotes de 5 min) y prueba de aislamiento `QA-09` (la supresión de datos personales va en `QA-14`) | — |
| RF-15 Preferencias del usuario | 🟩 | = | Completo desde la iteración 2; replicado en caché regional (`D19`) | — |

### Escenarios de atributos de calidad

| Driver | Estado | Δ | Justificación | Iteración que lo completa |
|---|---|---|---|---|
| QA-01 Propagación ≤ 5 min | 🟩 | 🟨→🟩 | Presupuesto verificado en `113 s` (normal) / `190 s` (disrupción), reconciliación e IMAP sin *push* acotados (`D20`, `D24`) | — *(se mide en prototipo)* |
| QA-02 Panel web p95 ≤ 800 ms | 🟩 | 🟨→🟩 | Caché regional invalidada por eventos (`D19`), presupuesto cerrado en `497–568 ms` y especificación de prueba en [pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md) | — |
| QA-03 FCP móvil ≤ 1,4 s | 🟩 | 🟨→🟩 | Arranque en frío cerrado en `1.180 ms` con `GET /panel/resumen ≤ 15 KB`, carga diferida e instantánea local (`D19`) | — |
| QA-04 Pico de disrupción | 🟩 | 🟨→🟩 | Contrapresión, 3 modos de degradación (`D20`), autoescalado híbrido `< 3 min` (`D21`) y especificación de prueba en [pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md) | — |
| QA-05 Pérdida de una región | 🟩 | 🟨→🟩 | **Resueltos `R-1` y `R-4`** (`D18`): detección `≤ 30 s`, redirección `≤ 60 s`, testigo transregional (`RPO = 0`) | — |
| QA-06 Proveedor externo caído | 🟩 | 🟨→🟩 | Mamparo, cortacircuitos `≤ 25 s`, cola persistente `24 h` con *backoff* + *jitter* y `marcaFrescura` (`D24`) | — |
| QA-07 Despliegue sin inactividad | 🟩 | ⬜→🟩 | Canario `5 %` por región, reversión automática `≤ 75 s < 2 min` y migraciones *expand/contract* (`D22`) | — |
| QA-08 Crecimiento de la base | 🟩 | 🟨→🟩 | 64 *buckets* por `hash(usuario_id)`, división en línea, compactación, archivo frío y costo `1,80×` para `2×` cuentas (`D23`, `D26`) | — |
| QA-09 Aislar la carga analítica | 🟩 | = | Verificado con dimensionamiento, pausa automática en disrupción y especificación de prueba en [pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md) | — |
| QA-10 Proveedor de viaje nuevo | 🟩 | = | Se verifica documentalmente en la iteración 4 | — *(se verifica en 4)* |
| QA-11 Formato de correo desconocido | 🟨 | = | Falta flujo final al usuario y medición sobre corpus (`R-2`) | 4 |
| QA-12 Solo personas designadas | 🟩 | = | Se verifica y detalla el caso del designado sin cuenta en la iteración 4 | — *(se verifica en 4)* |
| QA-13 Custodia de tokens de correo | 🟨 | = | Faltan detección de extracción masiva, revocación en bloque y rotación de claves | 4 |
| QA-14 Auditoría de datos personales | ⬜ | = | Excluido deliberadamente; asignado a la iteración 4 | 4 |
| QA-15 Nuevo medio de transporte | 🟩 | = | Validado en la iteración 2; guía paso a paso en la iteración 4 | — *(se verifica en 4)* |
| QA-16 Trazabilidad al código | 🟨 | = | Matriz actualizada hasta `ADR-0026`; cierre total de la 1ra entrega en iteración 4 y código en la 2da | 4, 2da entrega |
| QA-17 Contexto de ubicación | ⬜ | = | Excluido deliberadamente; asignado a la iteración 4 | 4 |
| QA-18 Región nueva | ⬜ | = | La topología multirregión y `región_primaria` ya están; falta externalización de localización y residencia | 4 |

### Restricciones

| Driver | Estado | Δ | Justificación |
|---|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | 🟨 | = | 3 de 4 iteraciones completas; la 4ta queda lista para ejecutarse |
| CON-02 ADRs en formato MADR | 🟩 | = | Decisiones D1 a D26 documentadas con alternativas descartadas; ADRs 0018–0026 publicados en MADR |
| CON-03 Wiki con evolución y labor individual | 🟩 | = | Bitácora, vistas e índices actualizados |
| CON-04 Spec-driven development | 🟨 | = | Se incorporan especificaciones verificables de pruebas de carga y catálogo de SLOs en [pruebas-de-carga-y-slos.md](pruebas-de-carga-y-slos.md); el código corresponde al prototipo de la 2da entrega |
| CON-05 Acotar el alcance del prototipo | ⬜ | = | Corresponde al inicio de la 2da entrega |
| CON-06 Alojar el módulo avanzado | 🟨 | = | Se verifica en papel para Opción A y Opción B en la iteración 4 |
| CON-07 APIs estándar del dominio | 🟩 | = | Sin cambios |
| CON-08 Autorización explícita del correo | 🟩 | = | Sin cambios |
| CON-09 Equipo de 4 con dedicación parcial | 🟩 | = | 13 + 2 elementos mantenidos; `R-5` mitigado sin agregar microservicios nuevos |
| CON-10 Normativa de datos personales | ⬜ | = | Asignado a la iteración 4 (`ADR-0030`, `ADR-0031`) |

### Inquietudes arquitectónicas

| Driver | Estado | Δ | Justificación |
|---|---|---|---|
| CRN-01 Estructura general del sistema | 🟩 | = | Sin cambios |
| CRN-02 Asignar trabajo a 4 personas | 🟩 | = | Reforzado por el desacoplamiento operativo de `itinerary-lectura` e `itinerary-escritura` (`D21`) |
| CRN-03 Presupuesto de error de disponibilidad | 🟩 | 🟨→🟩 | `D25` ([ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md)): SLIs/SLOs versionados, sondas sintéticas, RUM y freno automático al 75 % del presupuesto |
| CRN-04 Despliegue continuo sin inactividad | 🟩 | ⬜→🟩 | `D22` ([ADR-0022](../../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md)): entrega canaria secuencial por región + *expand/contract* |
| CRN-05 Gestión de secretos y tokens | 🟨 | = | Rotación y detección de acceso anómalo se cierran en la iteración 4 |
| CRN-06 Pruebas y verificación de contratos | 🟩 | = | Ampliado con especificaciones verificables de pruebas de carga y aislamiento |
| CRN-07 Trazabilidad driver → código | 🟩 | = | Matriz actualizada hasta la iteración 3 |
| CRN-08 Costo de infraestructura | 🟩 | 🟨→🟩 | `D26` ([ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md)): modelo mensual y camino escalonado en 3 etapas (**`R-3` cerrado**) |
| CRN-09 Cuotas de las APIs de terceros | 🟩 | 🟨→🟩 | `D24` ([ADR-0024](../../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md)): tope al 80 %, alerta al 70 % y reparto por prioridad |
| CRN-10 Internacionalización desde el inicio | ⬜ | = | Asignado a la iteración 4 (`ADR-0032`) |
| CRN-11 Resolución de conflictos entre fuentes | 🟩 | = | Eliminada la salvedad multirregión gracias a `D18` |
| CRN-12 Idempotencia de la ingesta | 🟩 | 🟨→🟩 | Cerrada su precondición de partición única por usuario en operación normal y convergencia ante *failover* (`D18`) |
| **CRN-13** Consistencia entre regiones activas | 🟩 | *nuevo* | `D18` ([ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md)): **cierra `R-1` y `R-4`** |

### Resumen

| Estado | RF | QA | CON | CRN | **Total** |
|---|---|---|---|---|---|
| ⬜ No tratado | 0 | 3 | 2 | 1 | **6** |
| 🟨 Parcialmente tratado | 7 | 3 | 3 | 1 | **14** |
| 🟩 Completamente tratado | 8 | 12 | 5 | 11 | **36** |
| **Total** | **15** | **18** | **10** | **13** | **56** |

Evolución acumulada a lo largo del proceso ADD:

| Cierre de iteración | ⬜ No tratado | 🟨 Parcialmente tratado | 🟩 Completamente tratado | Total de drivers |
|---|---|---|---|---|
| Iteración 1 | 15 (28 %) | 27 (51 %) | 11 (21 %) | 53 |
| Iteración 2 | 8 (15 %) | 28 (51 %) | 19 (35 %) | 55 |
| **Iteración 3** | **6 (11 %)** | **14 (25 %)** | **36 (64 %)** | **56** |

De los **6 drivers que quedan en ⬜**, cinco (`QA-14`, `QA-17`, `QA-18`, `CON-10`, `CRN-10`) son
exactamente los que el plan asignó a la **iteración 4**, y el sexto (`CON-05`, acotar el alcance del
prototipo) pertenece por definición al inicio de la **2da entrega**.

---

## Riesgos residuales

Cuatro de los cinco riesgos heredados quedan cerrados en esta iteración, `R-2` continúa hacia la
iteración 4 y el prototipo, y aparece un riesgo nuevo (`R-6`) derivado honestamente de `D18`:

| ID | Riesgo | Estado tras iteración 3 | Resolución / Próximo paso |
|---|---|---|---|
| **R-1** | Consistencia de datos entre regiones activas | ✅ **Cerrado** | Resuelto en [ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md) (`región_primaria` por usuario + testigo transregional + fusión convergente + lectura causal) |
| **R-2** | Fragilidad de la extracción desde correo | ⚠️ **Mitigado, abierto** | En la **iteración 4** se cierra el flujo hacia el usuario y el tratamiento de buzones sin OAuth (`ADR-0035`); el 95 % se valida empíricamente sobre corpus real en la **2da entrega** |
| **R-3** | Costo de la infraestructura para una *startup* | ✅ **Cerrado** | Resuelto en [ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md): Etapa 1 arranca en `USD 4.800/mes` (-83 %) sin tocar estructura ni contratos |
| **R-4** | Idempotencia y fusión dependían de una única partición por usuario | ✅ **Cerrado** | Resuelto junto con `R-1` en [ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md); permite pasar `CRN-12` a 🟩 |
| **R-5** | Concentración de responsabilidades y acoplamiento operativo en `itinerary` | ✅ **Mitigado / Cerrado para 1ra entrega** | [ADR-0021](../../03-adr/ADR-0021-estrategia-autoescalado.md) separa `itinerary-lectura` e `itinerary-escritura` en ejecución, recursos y despliegues canarios. Si durante el prototipo hubiera contención de equipo en el código, la frontera de extracción al elemento 14 ya coincide con esa línea sin tocar contratos |
| **R-6** *(nuevo)* | **Tensión entre replicación transregional de contingencia (`D18`) y residencia estricta de datos personales (`CON-10` / `CRN-15`)** | 🟨 **Abierto para iteración 4** | `D18` replica proyecciones y el registro testigo hacia una `región_respaldo` para garantizar `QA-05`. En jurisdicciones como GDPR (`UE`), cruzar datos identificables fuera del Espacio Económico Europeo requiere definir qué campos viajan cifrados con claves regionales o seudonimizados y cómo se ejecuta la supresión transregional. **Se resuelve en la iteración 4 (`ADR-0029`, `ADR-0030`, `ADR-0031`)** |

---

## Decisión sobre la continuación y guía de entrada para la Iteración 4

El propósito de diseño global aún **no** está alcanzado porque restan los atributos de seguridad y
privacidad normativa, interoperabilidad/versionado, internacionalización y la verificación del punto
de extensión para la 2da entrega. **Se continúa con la iteración 4** (última de la 1ra entrega).

### Lo que recibe listo quien ejecute la Iteración 4

Para facilitar el trabajo del cierre de la 1ra entrega, esta iteración deja preparado lo siguiente:

1. **Numeración y base de ADRs lista (`ADR-0027` a `ADR-0035`).** Tal como prevé
   [iteracion-4-plan.md](../iteracion-4-plan.md#adrs-previstos), los ADRs `0018` a `0026` ya están
   publicados y aceptados en `docs/03-adr/`, por lo que la iteración 4 arranca directamente en
   `ADR-0027` con `CRN-14` y `CRN-15` llevando el total final a **58 drivers**.
2. **Riel estructural para residencia y supresión de datos (`ADR-0030`, `ADR-0031`).** Cada usuario
   ya tiene `región_primaria` (`D18`) y partición por `usuario_id` (`D23`), y el plano analítico ya
   opera con seudónimos (`D16`). La iteración 4 solo debe resolver `R-6` (cifrado/alcance de la
   réplica de respaldo) y el mecanismo de supresión criptográfica o física en ambos planos (`QA-14`).
3. **Lista exacta de drivers que debe cerrar la iteración 4 para dejar cero `⬜` de diseño:**
   - En `⬜` hoy (5): `QA-14`, `QA-17`, `QA-18`, `CON-10`, `CRN-10` (recordando que `CON-05` es de
     la 2da entrega).
   - En `🟨` que dependen de la iteración 4: `RF-01`, `RF-03`, `RF-05`, `RF-11`, `RF-12`, `RF-13`,
     `QA-11`, `QA-13`, `QA-16`, `CON-01` (pasa a 🟩 al completar la 4ta iteración), `CON-06` y
     `CRN-05`, más los nuevos `CRN-14` y `CRN-15`.
   - Pendiente paralelo de equipo: recordar materializar los archivos externos referenciados por la
     iteración 2 (`ADR-0010`..`0017`, `vista-modulos-nivel-2.md`, `secuencias-casos-primarios.md` y
     `contratos/`) antes de la revisión final de consistencia de la 1ra entrega.

→ [Plan de la iteración 4](../iteracion-4-plan.md)
