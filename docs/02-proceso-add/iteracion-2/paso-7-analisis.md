# Iteración 2 · Paso 7 — Análisis del diseño y revisión del objetivo

El paso 7 de ADD es el control de honestidad del método: acá se verifica qué drivers quedaron
tratados y, sobre todo, **qué no**. Un paso 7 que declara todo resuelto es un paso 7 mal hecho. En
esta iteración además aparece algo que en la primera no podía aparecer: el diseño de las partes
**encontró errores en el diseño del conjunto**, y están declarados en
[Ajustes a la iteración 1](#ajustes-a-la-iteración-1).

---

## Revisión del objetivo de la iteración

> **Objetivo declarado:** identificar las estructuras internas que soportan los 9 requisitos
> funcionales primarios y los 7 casos de uso primarios, de modo que cada caso de uso tenga un
> recorrido completo y especificado entre elementos con interfaces declaradas.

### ¿Cada caso de uso tiene un recorrido completo y especificado?

Sí. Cada recorrido está numerado paso a paso; los diagramas están en
[secuencias-casos-primarios](../../04-vistas/secuencias-casos-primarios.md). Se indica en cada
paso el elemento y el mecanismo, y no hay pasos «por definir».

| Caso de uso | Recorrido |
|---|---|
| **UC-1** Ingesta desde correo | ① `mail-ingest` recibe el aviso del proveedor de correo (o lo origina la reconciliación) y encola «buzón con cambios» → ② obtiene un token de uso acotado de `identity-access`, baja los metadatos y aplica los filtros → ③ baja el mensaje, lo normaliza, aplica la bandeja de entrada `(buzón, mensaje)` y publica `MensajeDeViajeRecibido` → ④ `booking-extraction` elige el extractor, extrae, valida y fija la banda → ⑤ publica `ReservaExtraida` (banda alta o media) o `ExtraccionNoReconocida` → ⑥ `itinerary` resuelve la identidad por identificadores, agrega la observación y consolida → ⑦ `viajes` asigna o crea el viaje → ⑧ publica `ReservaActualizada` / `ViajeArmado` (y `ConflictoDeFuentesDetectado` si corresponde) → ⑨ `notification` aplica sus reglas y emite |
| **UC-2** Actualización de un proveedor | ① El proveedor notifica a `provider-sync` por webhook, o lo detecta un trabajo programado → ② el adaptador traduce a observación canónica y `seguimiento` identifica reserva y usuario → ③ publica `ReservaObservada` (y `DisrupcionDetectada` si corresponde) → ④ `itinerary` consolida con precedencia del proveedor; si choca con un campo fijado abre un conflicto → ⑤ publica `ReservaActualizada` o `ReservaCancelada` → ⑥ `notification` correlaciona con la disrupción y emite **un** aviso → ⑦ `proyeccion-panel` actualiza la lectura |
| **UC-3** Consulta del panel | ① El cliente llega por `edge` → ② `api-gateway` autentica y autoriza con `identity-access` → ③ el BFF del cliente llama a `itinerary-lectura` → ④ se lee `panel_usuario` (viajes activos, reservas por confirmar, conflictos abiertos) → ⑤ el BFF completa con las copias locales de preferencias y devuelve una respuesta compuesta en una sola ida y vuelta |
| **UC-4** Alta manual | ① El cliente envía `POST /reservas` con `Idempotency-Key` → ② `api-gateway` y BFF → ③ `gestion-manual` valida el detalle contra el descriptor del tipo → ④ `fusion` busca por identificadores; si hay coincidencia, agrega la observación a esa reserva; si no, crea una, y si hay candidatas difusas las devuelve como sugerencia → ⑤ `viajes` asigna el viaje → ⑥ responde con el estado resultante → ⑦ publica los eventos por *outbox* |
| **UC-5** Notificación de disrupción | ① El proveedor informa la disrupción a `provider-sync` → ② `detector-de-disrupciones` la expande a los usuarios afectados con `seguimiento` → ③ publica `DisrupcionDetectada` → ④ `notification` emite un aviso crítico inmediato, con la acción «pedir ayuda» que lleva a UC-7 → ⑤ en paralelo sigue el camino de UC-2 para consolidar el cambio |
| **UC-6** Consulta analítica | ① `itinerary`, `notification` y `support-liaison` publican eventos → ② `event-pipeline` los retiene crudos → ③ los transforma en hechos y dimensiones en micro-lotes → ④ los carga en `analytics-store` → ⑤ el analista ejecuta SQL sobre el esquema en estrella; no hay datos personales, solo seudónimos |
| **UC-7** Derivación a la agencia | ① El usuario pide ayuda (desde el panel o un aviso) con `Idempotency-Key` → ② `support-liaison` obtiene la instantánea del viaje de `itinerary` y la agencia de su copia de `preferences` → ③ crea el `Caso` → ④ el adaptador de agencia lo deriva → ⑤ publica `CasoDerivado` → ⑥ `notification` confirma al usuario → ⑦ el estado vuelve por la interfaz de la agencia o lo marca el usuario |

### ¿Se cumplen los criterios de salida del plan?

| # | Criterio | Veredicto | Evidencia |
|---|---|---|---|
| 1 | Los 7 casos de uso primarios tienen un diagrama de secuencia completo, sin pasos «por definir» | ✅ | Tabla anterior y [secuencias](../../04-vistas/secuencias-casos-primarios.md) |
| 2 | Los 15 requisitos funcionales están en 🟨 o 🟩; ninguno en ⬜ | ✅ | 5 en 🟩, 10 en 🟨, 0 en ⬜ ([kanban](#kanban-de-drivers)) |
| 3 | Todas las interfaces de la vista C&C de nivel 1 tienen contrato declarado | ✅ con una salvedad | [Tabla de contratos](README.md#contratos-declarados-en-el-repositorio). El de `sharing` es un **borrador**: está declarado, no completo; se cierra en la iteración 4 |
| 4 | R-2 tiene una mitigación concreta y verificable, no solo la regla de «no inventar» | ✅ | Cinco mecanismos medibles ([D15](paso-4-alternativas.md#mitigación-concreta-y-verificable-de-r-2)). R-2 queda **mitigado, no cerrado** |
| 5 | El modelo canónico se valida contra QA-15: agregar «tren» toca a lo sumo dos elementos | ✅ con un matiz | Sección siguiente |

### Validación del modelo canónico contra los cinco tipos de segmento

Este es el control que el plan marca como mitigación del riesgo propio de la iteración. Se
verificó **en papel** que el modelo representa los cinco tipos sin cambios, y la verificación **sí
encontró un defecto**, que se corrigió.

| Tipo | Cómo se representa | Rol | Identificadores | Detalle propio | ¿Requiere cambiar el modelo? |
|---|---|---|---|---|---|
| **Vuelo** | Una reserva con un segmento por tramo | `traslado` | Localizador de la aerolínea; número de orden de la agencia | Aerolínea, número de vuelo, terminal, puerta, asiento, clase | No *(implementado)* |
| **Hotel** | Un segmento; inicio = ingreso, fin = salida, **mismo lugar** | `alojamiento` | Código de la cadena o de la agencia | Habitaciones, huéspedes, régimen, política de cancelación | No *(implementado)* |
| **Auto** | Un segmento; inicio = retiro, fin = devolución, **lugares que pueden diferir** | `movilidadLocal` | Código de la rentadora | Categoría, kilometraje, cobertura | No *(implementado)* |
| **Tren** | Un segmento por tramo; estaciones de inicio y fin | `traslado` | Código del operador | Número de tren, coche, asiento, clase | **Descubrió un defecto** (abajo) |
| **Autobús** | Un segmento por tramo | `traslado` | Código del boleto | Línea, andén, asiento, operador | **Descubrió un defecto** (abajo) |

**Hallazgo de la validación.** Los boletos abiertos o flexibles de tren y autobús valen «ese día»
y no tienen hora. El primer borrador del modelo tenía un `instante` obligatorio en inicio y fin,
que **no podía representar** esos boletos. Se corrigió agregando `precision` (`instante` o `dia`)
al inicio y al fin del segmento. Detectarlo ahora cuesta una línea en el esquema; detectarlo
cuando se implemente el tren costaría una migración. Un segundo hallazgo menor: las estaciones de
tren y autobús no tienen un código universal como el IATA, así que `Lugar.codigo` es opcional y
el lugar se identifica también por nombre y coordenadas.

#### Qué toca agregar «tren»

| Elemento | ¿Se toca? | Qué |
|---|---|---|
| `itinerary` | **Sí (configuración)** | Alta del descriptor `tren` en el registro. Cero líneas de código |
| `provider-sync` | Si se integra un intercambio ferroviario | Un adaptador nuevo cargado como complemento |
| `booking-extraction` | Si se leen correos de operadores | Extractores nuevos cargados como complemento |
| `bff-web`, `bff-mobile` | No | Renderizan por la plantilla del descriptor (`GET /tipos-de-segmento`) |
| `notification` | No | Los campos relevantes salen del descriptor |
| `event-pipeline`, `analytics-store` | No | Fila nueva en `dim_tipo_segmento`; el detalle pasa como JSON |
| Clientes | No, salvo un ícono propio | Hay ícono por omisión |

**Veredicto y matiz.** El criterio se cumple: el **código existente modificado es cero** y se
toca un elemento por configuración (`itinerary`) más **un** elemento por cada canal de datos que
se quiera aprovechar. Con un canal son dos; **con los dos canales (proveedor y correo) son tres
elementos tocados**, aunque en los otros dos solo se agrega un complemento sin modificar nada. La
lectura de «a lo sumo dos» es entonces la de **elementos con código modificado**, igual que la de
QA-10. Se registra para que no se afirme de más: si la evaluación leyera «tocar» como «alojar un
complemento nuevo», el caso de dos canales no cumpliría.

### ¿Los ASRs siguen habilitados?

Esta iteración agregó pasos a los recorridos y podría haber hecho inalcanzable algún ASR de la
iteración 1; se revisó cada uno.

| ASR | ¿Alguna decisión de esta iteración lo compromete? | Veredicto |
|---|---|---|
| **ASR-1** QA-01 — propagación ≤ 5 min | Se agregan la bandeja de entrada, la fusión y el *outbox* al camino. Son operaciones transaccionales de un agregado pequeño, de milisegundos, y el *outbox* agrega la latencia de su retransmisión. Cabe en la reserva de 60 s, **pero ya no es solo aritmética de papel**: se mide en la iteración 3. La coalescencia de avisos no cuenta porque el canal interno se actualiza siempre | ✅ Sigue habilitado |
| **ASR-2** QA-04 — pico de disrupción | La expansión de una disrupción a muchos usuarios (`seguimiento`) y los avisos coalescidos acotan la demanda. Las copias locales de preferencias evitan llamadas sincrónicas en el pico | ✅ Sigue habilitado |
| **ASR-3** QA-05 — pérdida de región | Sin cambios. D10 y D12 **preparan** las dos salidas de R-1 pero no deciden ninguna. **D13 y D14 agregan una dependencia nueva** sobre ese riesgo (R-4) | ⚠️ Habilitado con riesgo residual, **ahora ampliado** |
| **ASR-4** QA-11 — formato desconocido | D15 lo refuerza con las tres bandas, aunque obliga a precisar una frase de la iteración 1 (ver ajustes) | ✅ Sigue habilitado |
| **ASR-5** QA-13 — custodia de tokens | El filtrado previo a la descarga reduce la exposición. Nada de lo decidido toca la custodia | ✅ Sigue habilitado |

### ¿Se respetan las restricciones?

| Restricción | Cómo la satisface esta iteración |
|---|---|
| CON-04 (*spec-driven*) | Todos los contratos y los descriptores de tipo viven en el repositorio; D17 deriva las pruebas de ellos |
| CON-06 (alojar el módulo avanzado) | El punto de extensión sigue sin interfaces nuevas, y ahora consume `ReservaActualizada` **ya consolidada** |
| CON-07 (APIs estándar) | El contrato de adaptador sigue consumiendo NDC, OTA/HTNG y equivalentes |
| CON-09 / CON-A4 (equipo de 4, < 15 elementos) | **Cero elementos nuevos.** La complejidad se absorbió dentro de `itinerary`, lo que se declara como R-5 |
| CON-02 (ADRs en MADR) | 17 ADRs, con alternativas descartadas |

**Conclusión: el objetivo de la iteración 2 se alcanzó.** El propósito de diseño global **no**, y
falta el tratamiento de la consistencia entre regiones, el dimensionamiento y las tácticas de las
iteraciones 3 y 4.

---

## Ajustes a la iteración 1

Al diseñar el interior de los elementos aparecieron inconsistencias en el diseño del conjunto.
**Ninguna decisión de la iteración 1 se revierte**, pero cinco puntos se corrigen o se precisan, y
conviene dejarlos explícitos porque modifican páginas ya escritas.

| # | Qué se descubrió | Ajuste | Dónde hay que actualizar |
|---|---|---|---|
| 1 | La tabla de eventos de la iteración 1 hacía que `notification` consumiera `ReservaActualizada` publicada **directamente por `provider-sync`**: se habría avisado al usuario con un dato sin fusionar, sin deduplicar y sin pasar por los conflictos. Además contradecía el recorrido de UC-2 (`provider-sync → itinerary → notification`) | Se crea `ReservaObservada` (`provider-sync` → `itinerary`). `ReservaActualizada` y `ReservaCancelada` pasan a ser publicados **solo por `itinerary`**, ya consolidados | [README de la iteración 1](../iteracion-1/README.md), tabla de eventos; vista C&C de nivel 1; nota en [ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md) |
| 2 | El paso 7 de la iteración 1 afirmaba que «el dominio nunca recibe un dato de confianza insuficiente» | Se precisa: el dominio nunca lo recibe **como confirmado**. La banda media entra como `PorConfirmar`, separada del itinerario. Es un refinamiento, no una contradicción | Paso 7 de la iteración 1, fila de ASR-4 |
| 3 | D1 dice que la ingesta y la lectura escalan por separado, pero `itinerary` es un solo elemento con ambas cargas | `itinerary` se despliega en dos modos (`escritura` y `lectura`) desde el mismo código. El dimensionamiento es de la iteración 3 | Vista de despliegue de nivel 1 |
| 4 | `DisrupcionDetectada` no decía a **quién** afectaba, y `provider-sync` no tenía cómo saberlo | `provider-sync` mantiene `seguimiento` (qué reservas de qué usuarios sigue) y el evento lleva los usuarios afectados | Catálogo de eventos |
| 5 | Los filtros de correo (RF-04) podían haberse colocado en `preferences`, lo que ataba el camino caliente de ingesta a otro elemento | Viven en `mail-ingest`. `preferences` solo publica sus cambios para que los demás guarden copia local | — |

El catálogo de eventos pasa de 8 a 15 ([README](README.md#510-catálogo-de-eventos-actualizado)).

---

## Kanban de drivers

Estado de los **55** drivers al cierre de la iteración. Son los 53 de la iteración 1 más CRN-11 y
CRN-12, que entran ahora. CRN-13, CRN-14 y CRN-15 entrarán cuando se traten.

- ⬜ **No tratado** — ninguna decisión tomada lo aborda todavía.
- 🟨 **Parcialmente tratado** — hay una decisión estructural que lo habilita, pero falta refinarlo.
- 🟩 **Completamente tratado** — las decisiones tomadas lo satisfacen y se puede verificar.

La columna **Δ** muestra el cambio respecto de la iteración 1.

### Requisitos funcionales

| Driver | Estado | Δ | Justificación | Iteración que lo completa |
|---|---|---|---|---|
| RF-01 Conectar cuenta de correo | 🟨 | = | Se diseñó el ciclo de vida del buzón (`Solicitado → Activo → RequiereReautorizacion → Revocado`) y el evento `EstadoDeBuzonCambiado`. Falta la revocación en bloque (QA-13) y la normativa (CON-10) | 4 |
| RF-02 Obtener mensajes de viaje | 🟨 | = | Suscripciones con renovación anticipada, reconciliación y camino único tras la convergencia. Faltan las cuotas por proveedor (CRN-09) y la medición de QA-01 | 3 |
| RF-03 Extraer y normalizar reservas | 🟨 | = | Modelo canónico, contrato de extractor y bandas de confianza. **Falta medir el acierto sobre un corpus real (R-2)** | 4, 2da entrega |
| RF-04 Filtros y whitelists | 🟩 | ⬜→🟩 | Tres listas con precedencia, evaluadas sobre metadatos antes de descargar el cuerpo | — |
| RF-05 Sincronizar con proveedores | 🟨 | = | Contrato de adaptador concreto y suite de conformidad. Faltan reintentos y umbrales del cortacircuitos (QA-06) | 3, 4 |
| RF-06 Gestión manual de reservas | 🟩 | ⬜→🟩 | Alta, edición y baja como observaciones de fuente manual, campos fijados y resolución de conflictos | — |
| RF-07 Agrupar reservas en viajes | 🟨 | ⬜→🟨 | Reglas por rol y lugar, con asignación fijable por el usuario. Los parámetros de la heurística solo se calibran con datos | 2da entrega |
| RF-08 Ciclo de vida del viaje | 🟩 | ⬜→🟩 | Máquina de estados y archivado por omisión con gracia configurable (AMB-08). La eliminación definitiva depende de CON-10, que es otro driver | — |
| RF-09 Visualizar el panel | 🟨 | = | Contratos de los dos BFF y proyección de lectura. Faltan las tácticas de caché y el arranque de la app | 3 |
| RF-10 Notificar actualizaciones | 🟩 | 🟨→🟩 | Severidades, canales, coalescencia, correlación con disrupciones y horas de silencio | — |
| RF-11 Compartir con designados | 🟨 | = | Fuera del alcance de esta iteración | 4 |
| RF-12 Derivar a la agencia | 🟨 | ⬜→🟨 | Caso de soporte con instantánea, estados e idempotencia; agencia como complemento. Falta verificarlo con agencias de interfaz heterogénea | 4 |
| RF-13 Publicar en redes sociales | 🟨 | = | Fuera del alcance de esta iteración | 4 |
| RF-14 Consultas analíticas | 🟨 | = | Modelo dimensional con dos hechos y seis dimensiones. Falta dimensionar el almacén y verificar la frescura ≤ 1 h | 3 |
| RF-15 Preferencias del usuario | 🟩 | ⬜→🟩 | Modelo, evento de cambio y copias locales en los consumidores | — |

### Escenarios de atributos de calidad

| Driver | Estado | Δ | Justificación | Iteración que lo completa |
|---|---|---|---|---|
| QA-01 Propagación ≤ 5 min | 🟨 | = | El camino ganó pasos transaccionales que caben en la reserva; **falta medirlo** | 3 |
| QA-02 Panel web p95 ≤ 800 ms | 🟨 | = | La proyección `panel_usuario` y el núcleo indexado de D12 sostienen el presupuesto de datos. Faltan las tácticas de caché | 3 |
| QA-03 FCP móvil ≤ 1,4 s | 🟨 | = | Sin cambios: falta el diseño del arranque de la app | 3 |
| QA-04 Pico de disrupción | 🟨 | = | La coalescencia, la expansión controlada y las copias de preferencias ayudan. Faltan el autoescalado y la contrapresión | 3 |
| QA-05 Pérdida de una región | 🟨 | = | **R-1 sigue sin resolverse**; D10 y D12 dejan abiertos los dos caminos | 3 |
| QA-06 Proveedor externo caído | 🟨 | = | Sin cambios: faltan umbrales y política de reintento | 3 |
| QA-07 Despliegue sin inactividad | ⬜ | = | Excluido deliberadamente | 3 |
| QA-08 Crecimiento de la base | 🟨 | ⬜→🟨 | Partición por usuario y compactación de observaciones (D12). Falta el modelo de crecimiento | 3 |
| QA-09 Aislar la carga analítica | 🟩 | = | Se mantiene por construcción; el modelo dimensional no toca la base operacional | — (se verifica en 3) |
| QA-10 Proveedor de viaje nuevo | 🟩 | = | La suite de conformidad del adaptador vuelve verificable «0 elementos modificados» | — (se verifica en 4) |
| QA-11 Formato de correo desconocido | 🟨 | = | Tres bandas y cinco mecanismos de mitigación. **Falta medir el 95 % sobre un corpus** | 4 |
| QA-12 Solo personas designadas | 🟩 | = | Sin cambios | — (se verifica en 4) |
| QA-13 Custodia de tokens de correo | 🟨 | = | Sin cambios | 4 |
| QA-14 Auditoría de datos personales | ⬜ | = | Excluido deliberadamente | 4 |
| QA-15 Nuevo medio de transporte | 🟩 | 🟨→🟩 | Validado en papel contra los cinco tipos, con el matiz declarado arriba | — (se verifica en 4) |
| QA-16 Trazabilidad al código | 🟨 | = | Los contratos y descriptores versionados extienden la trazabilidad; falta el tramo hacia el código | 4, 2da entrega |
| QA-17 Contexto de ubicación | ⬜ | = | Excluido deliberadamente | 4 |
| QA-18 Región nueva | ⬜ | = | Excluido deliberadamente | 4 |

### Restricciones

| Driver | Estado | Δ | Justificación |
|---|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | 🟨 | = | 2 de 4 completas, las otras 2 planificadas |
| CON-02 ADRs en formato MADR | 🟩 | = | 17 ADRs en formato MADR, con alternativas descartadas |
| CON-03 Wiki con evolución y labor individual | 🟩 | = | Sin cambios |
| CON-04 Spec-driven development | 🟨 | = | Los contratos de nivel 1 están declarados; falta que la verificación corra en integración continua y el tramo de implementación |
| CON-05 Acotar el alcance del prototipo | ⬜ | = | Corresponde a la 2da entrega |
| CON-06 Alojar el módulo avanzado | 🟨 | = | El punto de extensión sigue definido; se verifica en la iteración 4 |
| CON-07 APIs estándar del dominio | 🟩 | = | Sin cambios |
| CON-08 Autorización explícita del correo | 🟩 | = | Sin cambios |
| CON-09 Equipo de 4 con dedicación parcial | 🟩 | = | 13 + 2 elementos; la complejidad nueva se absorbió en módulos (ver R-5) |
| CON-10 Normativa de datos personales | ⬜ | = | Excluido. El filtrado previo y el seudónimo ayudan, pero **no son tratamiento** de la normativa |

### Inquietudes arquitectónicas

| Driver | Estado | Δ | Justificación |
|---|---|---|---|
| CRN-01 Estructura general del sistema | 🟩 | = | Sin cambios |
| CRN-02 Asignar trabajo a 4 personas | 🟩 | = | Sigue siendo posible; los módulos de `itinerary` son un riesgo de reparto (R-5) |
| CRN-03 Presupuesto de error de disponibilidad | 🟨 | = | Falta la instrumentación |
| CRN-04 Despliegue continuo sin inactividad | ⬜ | = | Iteración 3 |
| CRN-05 Gestión de secretos y tokens | 🟨 | = | Sin cambios |
| CRN-06 Pruebas y verificación de contratos | 🟩 | 🟨→🟩 | D17: pruebas derivadas de la especificación, con suite de conformidad y corpus |
| CRN-07 Trazabilidad driver → código | 🟩 | = | Sin cambios |
| CRN-08 Costo de infraestructura | 🟨 | = | Sin cambios |
| CRN-09 Cuotas de las APIs de terceros | 🟨 | = | Sin cambios |
| CRN-10 Internacionalización desde el inicio | ⬜ | = | Los descriptores usan claves de texto, pero no se tomó ninguna decisión: iteración 4 |
| **CRN-11** Resolución de conflictos entre fuentes | 🟩 | *nuevo* | D13: identificadores múltiples, precedencia por fuente e intervención del usuario. Se verifica con pruebas de propiedades. **Salvedad:** la fusión entre regiones es parte de R-4 |
| **CRN-12** Idempotencia de la ingesta | 🟨 | *nuevo* | D14: dos capas diseñadas. **La bandeja de entrada solo es correcta si todos los mensajes de un usuario pasan por la misma partición (R-4)**, de modo que no se puede cerrar antes de la iteración 3 |

### Resumen

| Estado | RF | QA | CON | CRN | **Total** |
|---|---|---|---|---|---|
| ⬜ No tratado | 0 | 4 | 2 | 2 | **8** |
| 🟨 Parcialmente tratado | 10 | 10 | 3 | 5 | **28** |
| 🟩 Completamente tratado | 5 | 4 | 5 | 5 | **19** |
| **Total** | **15** | **18** | **10** | **12** | **55** |

Respecto de la iteración 1: los ⬜ bajan de 15 a 8, los 🟩 suben de 11 a 19 y los 🟨 pasan de 27 a
28 (entran 3 que estaban en ⬜, salen 3 hacia 🟩, y entra CRN-12). Que solo **cinco** requisitos
funcionales queden completamente tratados es razonable: los diez que quedan en 🟨 dependen de la
medición, de la calibración con datos reales o de iteraciones posteriores, no de decisiones
estructurales pendientes.

---

## Riesgos residuales

Cinco riesgos quedan abiertos. Los tres primeros vienen de la iteración 1; **R-4 y R-5 son nuevos
y son consecuencia directa de decisiones de esta iteración**.

| ID | Riesgo | Origen | Impacto si se materializa | Dónde se resuelve |
|---|---|---|---|---|
| **R-1** | **Consistencia de datos entre regiones activas.** Sin cambios respecto de la iteración 1 | D2 (ADR-0002) | Compromete QA-05 (pérdida de datos confirmados = 0) y MN-1 | **Iteración 3**, CRN-13. D10 y D12 no cierran ninguna salida: la fusión determinista admite tipos convergentes y la partición por usuario admite región de origen |
| **R-2** | **Fragilidad de la extracción desde correo.** **Mitigado, no cerrado.** Hay mecanismos medibles, pero el 95 % solo es cierto sobre un corpus, y un formato nuevo sin corpus no está cubierto | D6, D15 | Degrada la propuesta de valor: el itinerario queda incompleto y el usuario vuelve a revisar su correo | **Iteración 4** y el prototipo, midiendo sobre un corpus real |
| **R-3** | **Costo de la infraestructura.** Sin cambios | D2, D3 (CRN-08) | Fuerza a replegarse a activo-pasivo y compromete QA-05 | **Iteración 3** |
| **R-4** | **Idempotencia y fusión dependen de la partición por usuario.** La bandeja de entrada de D14 y la fusión de D13 asumen que todo lo de un usuario pasa por la misma partición. Con el activo-activo de D2, dos regiones podrían procesar a la vez dos copias del mismo mensaje: duplicados o fusiones que divergen | D12, D13, D14 (con D2) | Reservas duplicadas o versiones contradictorias del mismo viaje, que compromete MN-1 | **Iteración 3, junto con R-1.** Comparten la raíz: si R-1 se resuelve con partición por usuario y región de origen, R-4 se resuelve en el mismo acto |
| **R-5** | **Concentración de responsabilidades en `itinerary`.** Fusión, agrupación, ciclo de vida, gestión manual y proyección viven en un solo elemento, para respetar CON-A4. Es el cuello de botella más probable del reparto de trabajo entre cuatro personas, y un cambio en la fusión obliga a redesplegar también la lectura | D10, D13, D14 | Retrasa la implementación del prototipo y encarece el cambio en el módulo más crítico | **Iteración 3**: los dos modos de despliegue acotan el despliegue. Si no alcanza, queda la salida de dividir por la línea lectura/escritura, que no cambia ningún contrato y llevaría los elementos a 14, todavía bajo el techo |

## Decisión sobre la continuación

El propósito de diseño global no está alcanzado, de modo que **se continúa con la iteración 3**,
cuyo foco son los atributos de calidad que esta iteración dejó habilitados pero sin tácticas ni
medición, y en particular **R-1 y R-4 como un único problema**: la consistencia de datos entre
regiones activas, CRN-13, y de ella dependen QA-05, CRN-12 y la credibilidad de MN-1. Además,
las exclusiones declaradas: QA-01 a QA-08 y CRN-04, CRN-08 y CRN-09.

→ [Plan de la iteración 3](../iteracion-3-plan.md)