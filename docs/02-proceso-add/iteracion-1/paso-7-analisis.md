# Iteración 1 · Paso 7 — Análisis del diseño y revisión del objetivo

El paso 7 de ADD es el control de honestidad del método: acá se verifica qué drivers quedaron
tratados y, sobre todo, **qué no**. Un paso 7 que declara todo resuelto es un paso 7 mal hecho.

---

## Revisión del objetivo de la iteración

> **Objetivo declarado:** establecer una estructura general del sistema que ofrezca un marco donde
> ubicar la funcionalidad primaria, y que no impida alcanzar los escenarios significativos para la
> arquitectura.

### ¿Hay un marco donde ubicar la funcionalidad primaria?

Sí. Los 9 requisitos funcionales primarios y los 7 casos de uso primarios tienen un elemento
responsable asignado:

| Caso de uso | Recorrido por los elementos de la estructura |
|---|---|
| UC-1 Ingesta desde correo | `mail-ingest` → `booking-extraction` → `itinerary` |
| UC-2 Actualización de un proveedor | `provider-sync` → `itinerary` → `notification` |
| UC-3 Consulta del panel | `edge` → `api-gateway` → `bff-web` / `bff-mobile` → `itinerary` |
| UC-4 Alta manual | `api-gateway` → `bff-*` → `itinerary` |
| UC-5 Notificación de disrupción | `provider-sync` → `notification` |
| UC-6 Consulta analítica | `event-pipeline` → `analytics-store` |
| UC-7 Derivación a la agencia | `support-liaison` → agencia externa |

Ninguno de los siete queda sin recorrido, y ningún recorrido pasa dos veces por el mismo elemento
con responsabilidades distintas, que es el síntoma de una descomposición mal trazada.

### ¿Los ASRs quedan habilitados?

| ASR | Decisión que lo habilita | ¿Alguna decisión lo vuelve inalcanzable? | Veredicto |
|---|---|---|---|
| **ASR-1** QA-01 — propagación ≤ 5 min | D4: *push* en lugar de sondeo, reduciendo la carga contra terceros en tres órdenes de magnitud. D1: el *broker* desacopla y permite consumo concurrente. El presupuesto de 300 s está repartido por tramo y cierra con 60 s de reserva | No | ✅ Habilitado |
| **ASR-2** QA-04 — pico de disrupción | D1: ingesta y lectura escalan por separado. D3: la analítica está en otro plano y puede degradarse primero. Existe una frontera explícita entre lo degradable y lo que no | No | ✅ Habilitado |
| **ASR-3** QA-05 — pérdida de región | D2: activo-activo en tres regiones, sin conmutación que consuma el presupuesto | No, pero **traslada el problema** a la consistencia entre regiones (R-1) | ⚠️ Habilitado con riesgo residual |
| **ASR-4** QA-11 — formato desconocido | D6: la heterogeneidad queda contenida en extractores con puntaje de confianza; el dominio nunca recibe un dato de confianza insuficiente | No | ✅ Habilitado |
| **ASR-5** QA-13 — custodia de tokens | D7: `identity-access` es el único elemento que descifra tokens; `mail-ingest` opera con tokens de uso acotado y vida corta | No | ✅ Habilitado |

### ¿Se respetan las restricciones?

| Restricción | Cómo la satisface esta iteración |
|---|---|
| CON-07 (APIs estándar) | D6: los adaptadores consumen NDC, OTA/HTNG y equivalentes; no hay raspado de pantalla |
| CON-08 (autorización explícita del correo) | D7: delegación OAuth 2.0; en ningún momento se le pide la contraseña al usuario |
| CON-09 / CON-A4 (equipo de 4, < 15 elementos) | 13 elementos en el plano operacional, más 2 en el analítico. Se respeta el techo |
| CON-A2 (nube pública con 3 regiones) | D2 la asume explícitamente |
| CON-06 (alojar el módulo avanzado) | El punto de extensión está definido: suscripción a `ViajeArmado` / `ReservaActualizada`, lectura del `analytics-store`, actuación por las interfaces ya publicadas de `itinerary` y `support-liaison`. **Ninguna interfaz nueva** |

**Conclusión: el objetivo de la iteración 1 se alcanzó.** El propósito de diseño global **no**,
y falta explícitamente todo el refinamiento de las iteraciones 2 a 4.

---

## Kanban de drivers

Estado de los 53 drivers al cierre de la iteración.

- ⬜ **No tratado** — ninguna decisión tomada lo aborda todavía.
- 🟨 **Parcialmente tratado** — hay una decisión estructural que lo habilita, pero falta refinarlo.
- 🟩 **Completamente tratado** — las decisiones tomadas lo satisfacen y se puede verificar.

### Requisitos funcionales

| Driver | Estado | Justificación | Iteración que lo completa |
|---|---|---|---|
| RF-01 Conectar cuenta de correo | 🟨 | `identity-access` es responsable y D7 fija el mecanismo; falta el ciclo de vida del consentimiento | 2, 4 |
| RF-02 Obtener mensajes de viaje | 🟨 | D4 fija el mecanismo; falta el diseño interno de suscripciones y reconciliación | 2, 3 |
| RF-03 Extraer y normalizar reservas | 🟨 | D6 fija la estructura de extractores; falta el modelo canónico y las reglas | 2 |
| RF-04 Filtros y whitelists | ⬜ | Asignado a `mail-ingest`, sin diseño | 2 |
| RF-05 Sincronizar con proveedores | 🟨 | D6 fija la estructura de adaptadores; faltan los contratos concretos | 2, 4 |
| RF-06 Gestión manual de reservas | ⬜ | Asignado a `itinerary`, sin diseño. Involucra CRN-11 (conflictos entre fuentes) | 2 |
| RF-07 Agrupar reservas en viajes | ⬜ | Es el corazón del dominio y requiere el modelo canónico | 2 |
| RF-08 Ciclo de vida del viaje | ⬜ | AMB-08 resolvió la política (archivar por omisión); falta el diseño | 2 |
| RF-09 Visualizar el panel | 🟨 | D5 fija la capa de clientes y los BFF | 2, 3 |
| RF-10 Notificar actualizaciones | 🟨 | `notification` es responsable y los eventos están definidos; faltan canales y reglas | 2 |
| RF-11 Compartir con designados | 🟨 | D7 fija el mecanismo de autorización; falta el diseño de la interfaz | 4 |
| RF-12 Derivar a la agencia | ⬜ | Asignado a `support-liaison`, sin diseño | 2 |
| RF-13 Publicar en redes sociales | 🟨 | AMB-10 lo separó estructuralmente de RF-11; falta qué campos incluye el resumen | 4 |
| RF-14 Consultas analíticas | 🟨 | D3 fija el plano analítico; falta el modelo dimensional | 2, 3 |
| RF-15 Preferencias del usuario | ⬜ | Elemento asignado, sin diseño | 2 |

### Escenarios de atributos de calidad

| Driver | Estado | Justificación | Iteración que lo completa |
|---|---|---|---|
| QA-01 Propagación ≤ 5 min | 🟨 | D4 lo habilita y el presupuesto por tramo cierra en papel; falta verificarlo con mediciones | 3 |
| QA-02 Panel web p95 ≤ 800 ms | 🟨 | D5 y D3 lo habilitan y el presupuesto cierra con 200 ms de reserva; faltan las tácticas de caché | 3 |
| QA-03 FCP móvil ≤ 1,4 s | 🟨 | D5 lo habilita con *payload* reducido; falta el diseño del arranque de la app | 3 |
| QA-04 Pico de disrupción | 🟨 | D1 y D3 lo habilitan y existe la frontera de degradación; faltan las políticas de autoescalado y contrapresión | 3 |
| QA-05 Pérdida de una región | 🟨 | D2 lo habilita; **falta resolver la consistencia entre regiones (R-1)** | 3 |
| QA-06 Proveedor externo caído | 🟨 | D6 ubica el cortacircuitos y el mamparo; faltan umbrales y política de reintento | 3 |
| QA-07 Despliegue sin inactividad | ⬜ | Excluido deliberadamente de esta iteración | 3 |
| QA-08 Crecimiento de la base | ⬜ | Excluido deliberadamente de esta iteración | 3 |
| QA-09 Aislar la carga analítica | 🟩 | D3 separa físicamente los planos: la consulta analítica no puede tocar la base operacional. La medida de «< 5 % de degradación» se satisface por construcción | — (se verifica en 3) |
| QA-10 Proveedor de viaje nuevo | 🟩 | D6 + G4: el adaptador se registra por configuración, de modo que «0 elementos existentes modificados» es literal | — (se verifica en 4) |
| QA-11 Formato de correo desconocido | 🟨 | La estructura contiene la heterogeneidad; falta la política de umbral de confianza y el flujo hacia el usuario | 2, 4 |
| QA-12 Solo personas designadas | 🟩 | D7/H4 decide verificar contra la identidad autenticada y no contra la posesión del enlace, que es lo que el driver exige | — (se verifica en 4) |
| QA-13 Custodia de tokens de correo | 🟨 | D7 segmenta el privilegio; faltan la detección de extracción masiva y la revocación en bloque | 4 |
| QA-14 Auditoría de datos personales | ⬜ | Excluido deliberadamente de esta iteración | 4 |
| QA-15 Nuevo medio de transporte | 🟨 | D6 da el punto de extensión en los adaptadores; depende del modelo canónico de la iteración 2 | 2, 4 |
| QA-16 Trazabilidad al código | 🟨 | La convención de identificadores y la matriz existen; el tramo hacia el código depende del prototipo | 4, 2da entrega |
| QA-17 Contexto de ubicación | ⬜ | Excluido deliberadamente de esta iteración | 4 |
| QA-18 Región nueva | ⬜ | D2 deja la topología preparada, pero no se tomó ninguna decisión de localización | 4 |

### Restricciones

| Driver | Estado | Justificación |
|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | 🟨 | 1 de 4 completa, las otras 3 planificadas |
| CON-02 ADRs en formato MADR | 🟩 | 9 ADRs en formato MADR, con alternativas descartadas |
| CON-03 Wiki con evolución y labor individual | 🟩 | Estructura de wiki, bitácora y convención de commits atribuidos |
| CON-04 Spec-driven development | 🟨 | D9 lo decide; los contratos concretos se escriben en la iteración 2 |
| CON-05 Acotar el alcance del prototipo | ⬜ | Corresponde a la 2da entrega |
| CON-06 Alojar el módulo avanzado | 🟨 | El punto de extensión está definido; se verifica en la iteración 4 |
| CON-07 APIs estándar del dominio | 🟩 | D6 lo satisface |
| CON-08 Autorización explícita del correo | 🟩 | D7 lo satisface |
| CON-09 Equipo de 4 con dedicación parcial | 🟩 | CON-A4 respetado: 13 + 2 elementos |
| CON-10 Normativa de datos personales | ⬜ | Excluido deliberadamente; iteración 4 |

### Inquietudes arquitectónicas

| Driver | Estado | Justificación |
|---|---|---|
| CRN-01 Estructura general del sistema | 🟩 | Es el objetivo de esta iteración y se alcanzó |
| CRN-02 Asignar trabajo a 4 personas | 🟩 | 13 elementos agrupables en cuatro áreas de responsabilidad |
| CRN-03 Presupuesto de error de disponibilidad | 🟨 | D8 fija el alcance y el reparto; falta la instrumentación |
| CRN-04 Despliegue continuo sin inactividad | ⬜ | Iteración 3 |
| CRN-05 Gestión de secretos y tokens | 🟨 | D7 fija la custodia; faltan rotación y detección |
| CRN-06 Pruebas y verificación de contratos | 🟨 | D9 lo decide; la estrategia concreta va en la iteración 2 |
| CRN-07 Trazabilidad driver → código | 🟩 | Convención de identificadores y matriz de trazabilidad establecidas |
| CRN-08 Costo de infraestructura | 🟨 | D2 lo acota a tres regiones; no hay modelo de costo todavía |
| CRN-09 Cuotas de las APIs de terceros | 🟨 | D4 reduce la carga en tres órdenes de magnitud; faltan los límites por proveedor |
| CRN-10 Internacionalización desde el inicio | ⬜ | Iteración 4 |

### Resumen

| Estado | RF | QA | CON | CRN | **Total** |
|---|---|---|---|---|---|
| ⬜ No tratado | 6 | 5 | 2 | 2 | **15** |
| 🟨 Parcialmente tratado | 9 | 10 | 3 | 5 | **27** |
| 🟩 Completamente tratado | 0 | 3 | 5 | 3 | **11** |
| **Total** | **15** | **18** | **10** | **10** | **53** |

Que ningún requisito funcional esté completamente tratado es lo **esperado** al cierre de una
primera iteración: esta iteración decidió la forma del sistema, no el comportamiento de sus
partes. Eso es exactamente el objetivo de la iteración 2.

---

## Riesgos residuales

Tres riesgos quedan abiertos. Están acá y no en una lista genérica de riesgos porque cada uno es
**consecuencia directa de una decisión de esta iteración**: el costo de haber elegido lo que se
eligió.

| ID | Riesgo | Origen | Impacto si se materializa | Dónde se resuelve |
|---|---|---|---|---|
| **R-1** | **Consistencia de datos entre regiones activas.** El activo-activo de D2 admite escrituras concurrentes sobre el mismo viaje desde dos regiones (el usuario viajando, el proveedor notificando). Si se resuelve mal, el usuario puede ver dos versiones distintas de su itinerario según desde dónde consulte | D2 (ADR-0002) | Compromete QA-05 (pérdida de datos confirmados = 0) y la credibilidad del «único punto de verdad» (MN-1) | **Iteración 3**, CRN-13. Caminos a evaluar: partición por usuario con región de origen, o tipos de datos convergentes para la fusión |
| **R-2** | **Fragilidad de la extracción desde correo.** D6 contiene la heterogeneidad, pero no la elimina: los formatos cambian sin aviso y sin contrato. La medida de QA-11 exige 95 % de acierto en los 20 remitentes más frecuentes, y eso solo se sabe midiendo | D6 (ADR-0006) | Degrada la propuesta de valor: el itinerario queda incompleto, y el usuario vuelve a revisar su correo a mano | **Iteración 2** (estructura de extractores y umbral de confianza) e **iteración 4**. Mitigación estructural ya tomada: ante confianza insuficiente el sistema no inventa, ofrece carga manual |
| **R-3** | **Costo de la infraestructura.** D2 y D3 implican triple capacidad más un plano analítico propio. Para una *startup* esto puede ser inviable antes de tener ingresos | D2, D3 (CRN-08) | Fuerza a replegarse a activo-pasivo, lo que compromete QA-05 de forma irreparable | **Iteración 3**: modelar el costo y evaluar un camino escalonado (empezar con dos regiones y una tercera solo para el plano de datos) sin cambiar la estructura |

## Decisión sobre la continuación

El propósito de diseño global no está alcanzado, de modo que **se continúa con la iteración 2**,
cuyo objetivo es identificar las estructuras que soportan la funcionalidad primaria —justamente los
15 drivers que esta iteración dejó en ⬜ y los 9 requisitos funcionales en 🟨.

→ [Plan de la iteración 2](../iteracion-2-plan.md)
