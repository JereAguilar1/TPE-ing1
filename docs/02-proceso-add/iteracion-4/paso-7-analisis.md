# Iteración 4 · Paso 7 — Análisis del diseño, cierre de la 1ra entrega y kanban final

El paso 7 de la cuarta iteración cumple una doble función: evalúa el logro del objetivo propio de la
iteración 4 y ejecuta la **verificación integral de cierre de la primera entrega**, comprobando que no
queden drivers olvidados, contradicciones entre vistas ni riesgos arquitectónicos sin respuesta antes
de pasar a la construcción del prototipo en la segunda entrega.

---

## Revisión de los criterios de salida — y cierre de la 1ra entrega

Evaluación punto por punto contra los seis criterios fijados en el
[plan de la iteración 4](../iteracion-4-plan.md#criterios-de-salida--y-cierre-de-la-1ra-entrega):

| # | Criterio de salida del plan | Veredicto | Evidencia verificable |
|---|---|---|---|
| 1 | **Ningún driver en ⬜.** Todos están en 🟨 o 🟩, y cada 🟨 documenta qué falta y por qué corresponde a la 2da entrega | ✅ **Cumplido (`0 ⬜`)** | De los **58 drivers** finales, **53 están en 🟩 (91 %)** y solo **5 en 🟨 (9 %)** (`RF-07`, `QA-16`, `CON-04`, `CON-05`, `CON-06`), todos por requerir ejecución o código del prototipo en la 2da entrega |
| 2 | **Los cinco ASRs en 🟩**, o con su limitación explícitamente documentada | ✅ **Cumplido (`5/5 🟩`)** | `QA-01`, `QA-04`, `QA-05` (cerrados en iteración 3) y `QA-11`, `QA-13` (cerrados en esta iteración) quedan en 🟩 a nivel de diseño arquitectónico, con sus criterios de confirmación empírica listos para el prototipo |
| 3 | **La matriz de trazabilidad está completa:** `100 %` de los drivers referenciados por al menos un ADR (`QA-16`) | ✅ **Cumplido (`58/58 = 100 %`)** | [Matriz de trazabilidad](../../05-trazabilidad/matriz-drivers-decisiones.md) actualizada hasta `ADR-0035`, con la tabla de huecos de trazabilidad en **cero entradas** |
| 4 | **`CON-06` verificado:** existe el diseño en papel de las dos opciones de módulo avanzado sobre la estructura actual, sin requerir interfaces nuevas | ✅ **Cumplido** | [Sección 5.7 del README](README.md#57-verificación-en-papel-del-punto-de-extensión-para-la-2da-entrega-d34--con-06-con-05) y [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md): tanto `recommendation-engine` (Opción A) como `virtual-assistant` (Opción B) operan como elemento nº 14 (`< 15`, `CON-A4`) exigiendo **`0` interfaces nuevas** al dominio |
| 5 | **Los riesgos residuales están cerrados** o explícitamente trasladados a la 2da entrega con su mitigación | ✅ **Cumplido** | **`R-1`, `R-3`, `R-4`, `R-5` y `R-6` cerrados** en diseño; únicamente la calibración empírica de precisión sobre corpus real de **`R-2`** pasa como validación experimental acotada al prototipo |
| 6 | **Revisión de consistencia entre vistas** ejecutada y registrada | ✅ **Cumplido** | Auditadas las reglas de consistencia entre vistas y las 7 reglas de dependencia de módulos en la sección siguiente, con **0 violaciones** |

---

## Estado final de los cinco ASRs al cerrar el proceso ADD

| ASR | Escenario `(Alto, Alto)` | Decisiones que lo sostienen (Iteraciones 1 → 4) | Estado final en 1ra entrega | Qué verifica el prototipo en 2da entrega |
|---|---|---|---|---|
| **ASR-1** | `QA-01` — Propagación de cambios ≤ 5 min (p95) | `ADR-0004` (*push* + reconciliación), `D14` (idempotencia), `ADR-0020` (carril `P1`), `ADR-0024` (cuotas e IMAP) y `ADR-0035` (reenvío verificado `< 5 s`) | 🟩 **Satisfecho (`113–190 s` estimados)** | Medición extremo a extremo desde *webhook* simulado hasta actualización visible |
| **ASR-2** | `QA-04` — Pico por disrupción masiva (`9.000 req/s` · `450 ev/s`) | `ADR-0001`, `ADR-0003`, `ADR-0020` (plazo propagado + 3 modos automáticos) y `ADR-0021` (autoescalado híbrido `< 3 min` + `itinerary` desdoblado) | 🟩 **Satisfecho** | Ejecución del Escenario 2 especificado en [pruebas-de-carga-y-slos.md](../iteracion-3/pruebas-de-carga-y-slos.md) |
| **ASR-3** | `QA-05` — Pérdida de una región completa (`RPO = 0`, `≤ 60 s`) | `ADR-0002`, `ADR-0008`, `ADR-0018` (`región_primaria` + testigo síncrono), `ADR-0025` (sondas `15 s`) y `ADR-0031` (testigo cifrado jurisdiccional, `R-6` cerrado) | 🟩 **Satisfecho** | Ejercicio de aislamiento regional verificando `0` pérdida en comandos confirmados |
| **ASR-4** | `QA-11` — Formato de correo desconocido (`0 %` error silencioso) | `ADR-0006` (complementos), `D15` (3 bandas de confianza + disyuntor), `ADR-0027` (`SemVer` de extractor) y `ADR-0035` (huella estructural anónima + alta asistida) | 🟩 **Satisfecho en arquitectura** | Prueba automatizada de rechazo seguro ante formato desconocido y medición sobre corpus (`R-2`) |
| **ASR-5** | `QA-13` — Custodia de credenciales de correo (9 M buzones) | `ADR-0007` (OIDC/OAuth delegado), `ADR-0019`/`0025` (cero tokens en caché/logs), `ADR-0029` (sobres `DEK_u`/`KEK_region`, mTLS, detección `≤ 5 min`, revocación `≤ 15 min`) y `ADR-0035` | 🟩 **Satisfecho** | Verificación automática de políticas de acceso a `VAULT` y prueba de emisión de tokens efímeros |

---

## Verificación de consistencia entre vistas (Criterio de salida 6)

### 1. Las cinco reglas de consistencia transversal ([docs/04-vistas/README.md](../../04-vistas/README.md#reglas-de-consistencia-entre-vistas))

| Regla | Resultado de la auditoría sobre las vistas N1 y N2 | Estado |
|---|---|---|
| **1. Todo módulo de la vista de módulos tiene al menos un componente que lo realiza en C&C** | Los 13 módulos operacionales y los 2 analíticos de [vista-modulos-nivel-1](../../04-vistas/vista-modulos-nivel-1.md) tienen correspondencia exacta en [vista-cyc-nivel-1](../../04-vistas/vista-cyc-nivel-1.md) (`itinerary` se realiza en dos grupos de ejecución `itinerary-lectura` e `itinerary-escritura` del mismo módulo, `ADR-0021`); `modelo-canonico`, `contratos` y `locales-i18n` son artefactos estáticos empacados/consumidos sin procesos huérfanos | ✅ Cumple |
| **2. Todo componente de C&C tiene un destino de despliegue en la vista de despliegue** | Los 13 servicios (con `itinerary` desdoblado), el *broker*, la caché regional, el almacén OLTP (`64` *buckets*), el archivo frío, la bóveda `VAULT`, el colector OpenTelemetry y el plano analítico (`event-pipeline` + `analytics-store`) tienen asignación física, zonas `AZ-1..3` y tabla de réplicas en [vista-despliegue-nivel-2](../../04-vistas/vista-despliegue-nivel-2.md) | ✅ Cumple |
| **3. Toda dependencia de la vista de módulos corresponde a un conector en C&C o es interna** | Verificadas todas las aristas entre [vista-modulos-nivel-1](../../04-vistas/vista-modulos-nivel-1.md), [vista-modulos-adaptadores](../../04-vistas/vista-modulos-adaptadores.md), [vista-cyc-nivel-1](../../04-vistas/vista-cyc-nivel-1.md) y [vista-despliegue-nivel-2](../../04-vistas/vista-despliegue-nivel-2.md): `api-gateway` enruta solo a `bff-*`, `sharing` e `identity-access`; la capa de anticorrupción y el dominio se comunican únicamente vía *broker* sobre `modelo-canonico` | ✅ Cumple |
| **4. Toda interfaz externa del contexto (`E-01`…`E-16`) tiene un componente responsable** | Las 16 interfaces de [02-diagrama-de-contexto](../../01-analisis-inicial/02-diagrama-de-contexto.md) están asignadas sin huecos en [vista-contexto](../../04-vistas/vista-contexto.md) y cuentan con sus controles de frontera en [vista-seguridad-y-datos](../../04-vistas/vista-seguridad-y-datos.md) | ✅ Cumple |
| **5. Toda interfaz entre componentes tiene contrato declarado y regla de evolución** | Todas las APIs REST, los 15 eventos AsyncAPI, los 2 contratos de complementos y los descriptores de segmento declarados en la iteración 2 quedan gobernados por las reglas de evolución y compatibilidad de [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | ✅ Cumple |

### 2. Las siete reglas de dependencia estática ([vista-modulos-nivel-1](../../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia))

| Regla | Estado tras las 4 iteraciones |
|---|---|
| **R1** (flujo descendente `clientes → borde → composición → dominio`) | ✅ Intacta, incluido el módulo avanzado nº 14 (`CON-06`), que solo recibe tráfico de usuario a través de `bff-*` |
| **R2** (anticorrupción y dominio desacoplados, unidos solo por eventos y `modelo-canonico`) | ✅ Confirmada en [vista-modulos-adaptadores](../../04-vistas/vista-modulos-adaptadores.md) y en las guías de `QA-10` y `QA-15` |
| **R3** (ningún tipo externo cruza al dominio) | ✅ Garantizada por `validador-canonico` y la suite de conformidad de complementos (`D17`, `D27`) |
| **R4** (`bff-*` sin lógica de dominio) | ✅ Mantenida: tanto `X-Min-Version` (`D18`) como el ruteo al módulo avanzado (`D34`) son pura composición/adaptación |
| **R5** (solo `identity-access` accede a `VAULT`) | ✅ Blindada criptográficamente en `ADR-0029` (identidad mTLS exclusiva sobre `custodia-boveda`) |
| **R6** (`analytics-store` sin acceso al plano operacional) | ✅ Mantenida incluso en la supresión `QA-14` (`ADR-0030`), que se coordina por eventos y lista de exclusión sin cruzar credenciales de base de datos |
| **R7** (`modelo-canonico` sin dependencias salientes) | ✅ Intacta |

---

## Kanban final de drivers (cierre de la 1ra entrega)

Estado definitivo de los **58 drivers** del proyecto: los 56 de la iteración 3 más **`CRN-14`** y
**`CRN-15`**, que entraron y quedaron completamente resueltos en esta iteración.

- ⬜ **No tratado** — `0` drivers.
- 🟨 **Parcialmente tratado** — el diseño arquitectónico de la 1ra entrega está completo; el tramo restante pertenece exclusivamente a la ejecución o calibración del prototipo en la **2da entrega**.
- 🟩 **Completamente tratado** — las decisiones arquitectónicas lo satisfacen con criterios de confirmación verificables.

La columna **Δ** refleja el cambio respecto del cierre de la [iteración 3](../iteracion-3/paso-7-analisis.md#kanban-de-drivers).

### Requisitos funcionales

| Driver | Estado | Δ | Justificación al cierre de la 1ra entrega | Qué resta en 2da entrega |
|---|---|---|---|---|
| RF-01 Conectar cuenta de correo | 🟩 | 🟨→🟩 | Ciclo de consentimiento OAuth, rotación/revocación masiva (`D29`) y vía segura sin contraseña primaria para cuentas sin OAuth (`D35`) completos | — |
| RF-02 Obtener mensajes de viaje | 🟩 | = | Completo desde la iteración 3 (`ADR-0004`, `ADR-0024`) | — |
| RF-03 Extraer y normalizar reservas | 🟩 | 🟨→🟩 | Cerrados extractores por complemento, 3 bandas de confianza (`D15`) y flujo asistido ante `ExtraccionNoReconocida` (`D35`) | Calibrar precisión sobre corpus en prototipo (`R-2`) |
| RF-04 Filtros y whitelists | 🟩 | = | Completo desde la iteración 2 | — |
| RF-05 Sincronizar con proveedores | 🟩 | 🟨→🟩 | Adaptadores resilientes (`D24`) con contrato canónico versionado (`D27`) y guía `QA-10` verificada | — |
| RF-06 Gestión manual de reservas | 🟩 | = | Completo con `RPO = 0` (`D18`) y precarga asistida desde correos no reconocidos (`D35`) | — |
| RF-07 Agrupar reservas en viajes | 🟨 | = | Reglas por rol y continuidad geográfica definidas (`iteración 2 §5.1`); **sus umbrales heurísticos (`72 h`, cercanía de ciudad) requieren datos reales de ejecución** | Calibración empírica en prototipo |
| RF-08 Ciclo de vida del viaje | 🟩 | = | Transiciones automáticas, archivo frío (`D23`) y retención/supresión legal (`D30`) cerrados | — |
| RF-09 Visualizar el panel | 🟩 | = | Completo en web y móvil, enriquecido con contexto espacial local (`D33`) y localización (`D32`) | — |
| RF-10 Notificar actualizaciones | 🟩 | = | Completo con carriles prioritarios (`D20`) y plantillas localizadas (`D32`) | — |
| RF-11 Compartir con designados | 🟩 | 🟨→🟩 | Cerrados autorización ABAC, caducidad 30 d, revocación `≤ 60 s` y acceso autenticado ligero para designados sin cuenta (`D28`) | — |
| RF-12 Derivar a la agencia | 🟩 | 🟨→🟩 | Caso idempotente, mamparo (`D24`), contrato de adaptador versionado (`D27`) e integración con Opción B (`D34`) verificados | — |
| RF-13 Publicar en redes sociales | 🟩 | 🟨→🟩 | Esquema `ResumenPublicable` por lista blanca sin datos sensibles y confirmación explícita (`D28`) | — |
| RF-14 Consultas analíticas | 🟩 | = | Estrella dimensional, aislamiento `QA-09` y preservación de agregados anónimos ante supresión (`D30`) completos | — |
| RF-15 Preferencias del usuario | 🟩 | = | Agencia, archivado, idioma/formatos (`D32`) y región (`D31`) cerrados | — |

### Escenarios de atributos de calidad

| Driver | Estado | Δ | Justificación al cierre de la 1ra entrega | Qué resta en 2da entrega |
|---|---|---|---|---|
| QA-01 Propagación ≤ 5 min *(ASR-1)* | 🟩 | = | Cerrado en iteración 3 (`113–190 s`); el alias de reenvío (`D35`) también entra en `< 5 s` | Medición en prototipo |
| QA-02 Panel web p95 ≤ 800 ms | 🟩 | = | Cerrado en iteración 3 con especificación de prueba de carga | Ejecución en prototipo |
| QA-03 FCP móvil ≤ 1,4 s | 🟩 | = | Cerrado en iteración 3 (`1.180 ms` en 4G); `D32` y `D33` no agregan saltos de red al arranque | Medición en prototipo |
| QA-04 Pico de disrupción *(ASR-2)* | 🟩 | = | Cerrado en iteración 3; el módulo avanzado (`D34`) se ubica en prioridad degradable 3 | Ejecución en prototipo |
| QA-05 Pérdida de una región *(ASR-3)* | 🟩 | = | Cerrado en iteración 3 (`D18`) y armonizado con residencia normativa en `D31` (`R-6` resuelto) | Simulacro en prototipo |
| QA-06 Proveedor externo caído | 🟩 | = | Cerrado en iteración 3 (`D24`) | — |
| QA-07 Despliegue sin inactividad | 🟩 | = | Cerrado en iteración 3 (`D22`) y complementado con compatibilidad contractual (`D27`) | — |
| QA-08 Crecimiento de la base | 🟩 | = | Cerrado en iteración 3 (`D23`, `D26`) | — |
| QA-09 Aislar la carga analítica | 🟩 | = | Cerrado en iteración 3; la compactación de supresión (`D30`) corre fuera de pico en el plano analítico | Ejecución en prototipo |
| QA-10 Proveedor de viaje nuevo | 🟩 | = | **Verificado paso a paso** en [guias-de-extension.md](guias-de-extension.md#2-guía-cómo-agregar-un-proveedor-de-viaje-nuevo-verificación-de-qa-10): `0` elementos existentes modificados, `≤ 40 h-p` | Prueba con adaptador ficticio en prototipo |
| QA-11 Formato de correo desconocido *(ASR-4)* | 🟩 | 🟨→🟩 | `0 %` de inserción errónea silenciosa, huella estructural sin PII, flujo asistido al usuario y extractor nuevo en `≤ 16 h-p` (`D35`, `D27`) | Validar `≥ 95 %` sobre corpus real (`R-2`) |
| QA-12 Solo personas designadas | 🟩 | = | **Verificado** (`D28`): `100 %` de no designados denegados con respuesta opaca, caducidad 30 d, revocación `≤ 60 s` y flujo OTP para invitados sin cuenta | — |
| QA-13 Custodia de tokens de correo *(ASR-5)* | 🟩 | 🟨→🟩 | Sobres `DEK_u`/`KEK_region`, mTLS exclusivo en `identity-access`, auditoría `100 %`, detección `≤ 5 min` y revocación regional `≤ 15 min` (`D29`) | Verificación de políticas en prototipo |
| QA-14 Auditoría de datos personales | 🟩 | ⬜→🟩 | Catálogo de PII, exportación de inventario e historial en `< 2 h ≤ 72 h` y supresión verificable en `≤ 30 días` en OLTP y `analytics-store` (`D30`) | — |
| QA-15 Nuevo medio de transporte | 🟩 | = | **Verificado paso a paso con `tren`** en [guias-de-extension.md](guias-de-extension.md#1-guía-cómo-agregar-un-nuevo-medio-de-transporte-verificación-de-qa-15-con-tren): `2` artefactos tocados, `0` servicios de dominio, `≤ 80 h-p` | — |
| QA-16 Trazabilidad al código | 🟨 | = | **100 % de trazabilidad documental completada** (`58/58` drivers → ADRs → vistas → contratos en `≤ 10 min`); **falta únicamente el tramo hacia los archivos de código fuente** | Trazar contra el código en 2da entrega |
| QA-17 Contexto de ubicación | 🟩 | ⬜→🟩 | Evaluación local de geocercas en `app-movil` sin rastreo continuo al servidor y degradación automática a orden temporal sin permiso GPS (`D33`) | — |
| QA-18 Región nueva | 🟩 | ⬜→🟩 | `0` cadenas en código (`D32`), perfil declarativo de residencia (`D31`) y guía verificada en `≤ 120 h-p` con `0` cambios en lógica de negocio | — |

### Restricciones

| Driver | Estado | Δ | Justificación al cierre de la 1ra entrega |
|---|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | 🟩 | 🟨→🟩 | **Cuatro iteraciones completas** de ADD documentadas paso a paso con sus artefactos intermedios y finales |
| CON-02 ADRs en formato MADR | 🟩 | = | Decisiones `D1` a `D35` registradas con contexto, drivers, alternativas descartadas y confirmación |
| CON-03 Wiki con evolución y labor individual | 🟩 | = | Bitácora, vistas e historial de entregas individuales por iteración actualizados |
| CON-04 Spec-driven development | 🟨 | = | Contratos, reglas de versionado (`ADR-0027`), catálogo de SLOs y pruebas verificables completos en diseño; **resta implementar el código del prototipo contra ellos en la 2da entrega** |
| CON-05 Acotar el alcance del prototipo | 🟨 | ⬜→🟨 | Criterio arquitectónico de recorte fijado en [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) (tajada vertical de los 5 ASRs + módulo avanzado); **el recorte concreto de implementación se instancia al abrir la 2da entrega** |
| CON-06 Alojar el módulo avanzado | 🟨 | = | **Verificado en papel para Opción A y Opción B** sin cambios estructurales ni interfaces nuevas ([ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md)); **la elección e incorporación efectiva pertenece por enunciado a la 2da entrega** |
| CON-07 APIs estándar del dominio | 🟩 | = | Respetado y versionado en la capa de anticorrupción |
| CON-08 Autorización explícita del correo | 🟩 | = | Reforzado en `ADR-0035`: prohibición total de almacenar contraseñas maestras incluso en cuentas sin OAuth |
| CON-09 Equipo de 4 con dedicación parcial | 🟩 | = | Se cierra toda la arquitectura en `13 + 2` elementos (`14 + 2` en 2da entrega, respetando `CON-A4 < 15`) |
| CON-10 Normativa de datos personales | 🟩 | ⬜→🟩 | GDPR y Ley 25.326 satisfechos mediante `ADR-0029`, `ADR-0030` y `ADR-0031` (catálogo, base legal, acceso `≤ 72 h`, supresión `≤ 30 d` y residencia por jurisdicción) |

### Inquietudes arquitectónicas

| Driver | Estado | Δ | Justificación al cierre de la 1ra entrega |
|---|---|---|---|
| CRN-01 Estructura general del sistema | 🟩 | = | Establecida en iteración 1 y preservada sin retrabajo a lo largo de las 4 iteraciones |
| CRN-02 Asignar trabajo a 4 personas | 🟩 | = | Módulos y despliegues alineados a 4 frentes paralelos |
| CRN-03 Presupuesto de error de disponibilidad | 🟩 | = | Cerrado en iteración 3 (`ADR-0025`) |
| CRN-04 Despliegue continuo sin inactividad | 🟩 | = | Cerrado en iteración 3 (`ADR-0022`) y reforzado con versionado compatible (`ADR-0027`) |
| CRN-05 Gestión de secretos y tokens | 🟩 | 🟨→🟩 | Cerrado en [ADR-0029](../../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md): sobres criptográficos, rotación cada 90 días, auditoría 100 % y revocación masiva |
| CRN-06 Pruebas y verificación de contratos | 🟩 | = | Pruebas CDC, validación de esquemas OpenAPI/AsyncAPI, suite de complementos y especificaciones de carga |
| CRN-07 Trazabilidad driver → código | 🟩 | = | Cadena documental verificada al 100 % en la [matriz de trazabilidad](../../05-trazabilidad/matriz-drivers-decisiones.md) |
| CRN-08 Costo de infraestructura | 🟩 | = | Cerrado en iteración 3 (`ADR-0026`); la compactación quincenal de `D30` y el cifrado por sobres de `D29` cuidan además los costos de KMS y almacenamiento |
| CRN-09 Cuotas de las APIs de terceros | 🟩 | = | Cerrado en iteración 3 (`ADR-0024`) |
| CRN-10 Internacionalización desde el inicio | 🟩 | ⬜→🟩 | Cerrado en [ADR-0032](../../03-adr/ADR-0032-internacionalizacion-y-localizacion.md) |
| CRN-11 Resolución de conflictos entre fuentes | 🟩 | = | Cerrado en iteración 2 y 3 |
| CRN-12 Idempotencia de la ingesta | 🟩 | = | Cerrado en iteración 2 y 3 |
| CRN-13 Consistencia entre regiones activas | 🟩 | = | Cerrado en iteración 3 (`ADR-0018`) |
| **CRN-14** Versionado de contratos publicados | 🟩 | *nuevo* | [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md): evolución compatible, `Deprecation`/`Sunset`, `versionEsquema` y `SemVer` en complementos |
| **CRN-15** Residencia de datos por región | 🟩 | *nuevo* | [ADR-0031](../../03-adr/ADR-0031-residencia-de-datos-por-region.md): clasificación `R1`/`R2`/`R3` y testigo cifrado jurisdiccional (**cierra `R-6`**) |

### Resumen cuantitativo final

| Estado | RF | QA | CON | CRN | **Total** |
|---|---|---|---|---|---|
| ⬜ No tratado | 0 | 0 | 0 | 0 | **0 (0 %)** |
| 🟨 Parcialmente tratado *(solo tramo de 2da entrega)* | 1 | 1 | 3 | 0 | **5 (9 %)** |
| 🟩 Completamente tratado | 14 | 17 | 7 | 15 | **53 (91 %)** |
| **Total** | **15** | **18** | **10** | **15** | **58 (100 %)** |

Evolución completa a lo largo de las cuatro iteraciones de ADD:

| Cierre de iteración | ⬜ No tratado | 🟨 Parcialmente tratado | 🟩 Completamente tratado | Total de drivers |
|---|---|---|---|---|
| Iteración 1 | 15 (28 %) | 27 (51 %) | 11 (21 %) | 53 |
| Iteración 2 | 8 (15 %) | 28 (51 %) | 19 (35 %) | 55 |
| Iteración 3 | 6 (11 %) | 14 (25 %) | 36 (64 %) | 56 |
| **Iteración 4 (cierre 1ra entrega)** | **0 (0 %)** | **5 (9 %)** | **53 (91 %)** | **58** |

---

## Cierre del registro de riesgos arquitectónicos (`R-1` a `R-6`)

| ID | Riesgo identificado durante ADD | Iteración donde surgió | Estado final al cerrar la 1ra entrega | Mecanismo que lo resuelve / acota |
|---|---|---|---|---|
| **R-1** | Divergencia de datos entre regiones activo-activo | Iteración 1 | ✅ **Cerrado** | `ADR-0018`: `región_primaria` por usuario + testigo síncrono en comandos manuales (`RPO = 0`) + lectura causal |
| **R-2** | Fragilidad ante la heterogeneidad de formatos de correo | Iteración 1 | ✅ **Acotado y trasladado a validación en prototipo** | `D15` + `ADR-0035` garantizan `0 %` de corrupción silenciosa, huella anónima y alta asistida; el prototipo mide la cobertura empírica sobre corpus de prueba |
| **R-3** | Costo inicial prohibitivo de 3 regiones + almacén columnar para una *startup* | Iteración 1 | ✅ **Cerrado** | `ADR-0026`: camino escalonado en 3 etapas desde `USD 4.800/mes` (-83 %) sin rediseño |
| **R-4** | Idempotencia (`D14`) y fusión (`D13`) presuponían serialización en una sola partición | Iteración 2 | ✅ **Cerrado** | `ADR-0018`: enrutamiento determinista a la partición primaria del usuario |
| **R-5** | Concentración de responsabilidades y acoplamiento operativo en `itinerary` | Iteración 2 | ✅ **Cerrado** | `ADR-0021`: despliegue desdoblado `itinerary-lectura` / `itinerary-escritura` desde el mismo módulo |
| **R-6** | Tensión entre el registro testigo transregional (`D18`) y la residencia estricta de datos (`CON-10`) | Iteración 3 | ✅ **Cerrado** | `ADR-0031` + `ADR-0029`: confinamiento estricto de `Clase R1` y testigo cifrado en origen con clave bajo custodia jurisdiccional primaria (*ciphertext-only witness*) |

*(Recordatorio operativo de consolidación del repositorio: antes de empaquetar el corte definitivo de evaluación, verificar que queden subidos al árbol principal los archivos individuales `ADR-0010`…`0017`, `vista-modulos-nivel-2.md`, `secuencias-casos-primarios.md` y `contratos/` elaborados en la iteración 2, y retirar el borrador temporal `iteracion-2/verificar-y-borrar.md`).*

---

## Decisión de finalización del método ADD y transición a la 2da entrega

**No se requiere una quinta iteración de ADD:** el propósito de diseño global se alcanzó. La
arquitectura cuenta con decisiones explícitas y verificables para los 58 drivers, vistas consistentes
en los tres tipos de estructuras (módulos, componentes y conectores, y asignación/despliegue/datos) y
costuras demostradas para el alcance obligatorio de la segunda entrega.

### Hoja de ruta de apertura para la 2da entrega

| Paso de arranque en 2da entrega | Insumo directo que entrega esta wiki |
|---|---|
| **1. Elegir Opción A (`recommendation-engine`) u Opción B (`virtual-assistant`)** | Diseño en papel ya verificado de ambas opciones en [README §5.7](README.md#57-verificación-en-papel-del-punto-de-extensión-para-la-2da-entrega-d34--con-06-con-05) y [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) |
| **2. Fijar el recorte ejecutable del prototipo (`CON-05`)** | Criterio de tajada vertical centrado en demostrar los **5 ASRs** + el módulo avanzado elegido, con dobles contractuales para terceros secundarios |
| **3. Implementar *spec-driven* (`CON-04`) y cerrar el último tramo de `QA-16`** | Contratos versionados ([ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md), [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md)) y matriz lista para añadir la columna de enlaces al código fuente |
| **4. Ejecutar las pruebas de confirmación** | Escenarios de carga y aislamiento (`QA-02`, `QA-04`, `QA-09`) en [pruebas-de-carga-y-slos.md](../iteracion-3/pruebas-de-carga-y-slos.md), prueba de complemento `QA-10`/`QA-11` y prueba de aislamiento criptográfico `QA-13` |
