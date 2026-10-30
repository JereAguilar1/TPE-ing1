# Iteración 4 · Paso 4 — Conceptos de diseño y alternativas

En la iteración de cierre se evalúan las alternativas para las nueve decisiones restantes del plan
(`D27` a `D35`). Cada tabla contrasta opciones reales contra los drivers del análisis inicial y deja
documentado por qué se descartan los caminos no elegidos. Cada decisión se formaliza en su ADR de
numeración homónima (`D27` → `ADR-0027`).

Criterio de evaluación: ✅ favorece el driver · ⚠️ lo permite con costo · ❌ lo compromete · — no aplica.

**Relación entre las decisiones de esta iteración.** **D29** (cifrado por sobres con `DEK_u` por
usuario y `KEK_region` jurisdiccional) es la pieza maestra que destraba tanto a **D30** (supresión en
almacenes columnares inmutables mediante cripto-desvinculación + compactación diferida) como a
**D31** (resolver `R-6` cifrando en origen el registro testigo transregional de `D18`). En paralelo,
**D27** fija las reglas de evolución de interfaces que hacen sostenibles en el tiempo a **D34**
(módulo avanzado de la 2da entrega) y a las guías de extensión de `QA-10` y `QA-15`.

---

## D27 — Versionado y evolución de los contratos publicados (`CRN-14`, `QA-10`, `QA-15`)

**Problema:** el sistema publica cuatro clases de contratos (`OpenAPI` en borde/BFF/dominio,
`AsyncAPI` en el *broker*, contratos de complementos `Extractor`/`AdaptadorDeProveedor` y descriptores
`TipoDeSegmento`). Con despliegues progresivos independientes (`D22`) y clientes móviles que el
usuario no actualiza el mismo día, cambiar un contrato sin disciplina rompe consumidores en vivo;
pero multiplicar rutas versionadas (`/v1`, `/v2`, `/v3`) duplica controladores y fragmenta cachés.

| Alternativa | Despliegue independiente (`CRN-04` / `D22`) | Clientes móviles desactualizados | Carga de mantenimiento (`CON-09`: 4 personas) | Claridad en eventos y plugins (`QA-10`, `QA-15`) | Rutas existentes (`Iter. 2 y 3`) |
|---|---|---|---|---|---|
| **A1. Versionado sistemático en la ruta URL (`/v1/...`, `/v2/...`) y tópicos duplicados por versión** | ✅ | ✅ | ❌ prolifera rutas y tópicos paralelos por cambios menores | ⚠️ partir un tópico rompe el orden por `usuario_id` | ❌ obliga a renombrar todas las rutas ya definidas |
| **A2. Evolución estrictamente aditiva eterna (prohibir para siempre cualquier cambio incompatible)** | ✅ | ✅ | ⚠️ | ❌ irreal ante un cambio regulatorio o semántico profundo | ✅ |
| **A3. Despliegue sincronizado (*lockstep*) de productor y consumidores** | ❌ acopla despliegues y destruye la reversión canaria de 75 s | ❌ imposible forzar actualización instantánea en móviles | ❌ | ❌ | ✅ |
| **A4. Evolución compatible por omisión (*expand/contract* + *tolerant reader*) + negociación por cabecera de medio en rupturas HTTP + `versionEsquema` con doble emisión acotada en eventos + `SemVer` en complementos** ⬅ **elegido** | ✅ versiones `N` y `N+1` conviven siempre | ✅ ventana de retiro `≥ 90 días` (`Sunset`) | ✅ el 95 % de los cambios son aditivos sin duplicar código | ✅ mantiene un solo tópico ordenado por usuario y valida plugins al cargar | ✅ conserva intactas `GET /panel`, `GET /viajes/{id}`, etc. |

### Por qué A4

**A3** convierte microservicios en un monolito distribuido e invalida `ADR-0022`. **A1** incentiva a
crear `/v2/panel` ante cualquier ajuste menor, fragmentando las claves `ETag` de la caché regional
(`D19`) y rompiendo el orden por partición si se crean tópicos nuevos en el *broker*. **A2** funciona
en el caso habitual pero deja al equipo sin protocolo de salida el día que una norma o un cambio de
dominio exige retirar un campo.

**A4** convierte la compatibilidad aditiva y los lectores tolerantes en la regla cotidiana (validada
automáticamente por `openapi-diff`, esquemas `AsyncAPI` y pruebas CDC en CI), preserva limpias las
rutas de recursos definidas en las iteraciones 2 y 3, y reserva el salto de versión mayor (por
cabecera `Accept` en HTTP, doble emisión de 14 días en eventos y `SemVer` en manifiestos de
complementos) como válvula de escape explícita y con fecha de caducidad (`Sunset`).

→ [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md)

---

## D28 — Autorización, compartición con designados (con y sin cuenta) y publicación segura (`QA-12`, `RF-11`, `RF-13`)

**Problema:** `ADR-0007` decidió exigir identidad autenticada contra una lista de designados (`QA-12`:
`100 %` de no designados rechazados, `0` fugas de existencia, caducidad 30 días, revocación `≤ 60 s`)
y dejó abierto qué ocurre cuando el familiar o colega designado **no tiene cuenta en Trotamundos**,
además de cómo impedir el antipatrón de *diputado confundido* entre servicios internos y cómo blindar
la publicación en redes (`RF-13` / `AMB-10`).

| Alternativa | QA-12: 100 % no designados denegados | Caso del designado sin cuenta previa | Fricción para el invitado legítimo | Protección contra *diputado confundido* interno | Prevención de fuga en redes (`AMB-10`) |
|---|---|---|---|---|---|
| **B1. Rebajar a enlace firmado con token aleatorio para quienes no tienen cuenta** | ❌ quien reenvía el enlace en un chat transfiere el acceso | ✅ cero registro | ✅ mínima | ⚠️ | — |
| **B2. Obligar al designado a crear una cuenta completa de viajero antes de ver** | ✅ | ⚠️ lo resuelve forzando alta permanente | ❌ abandono alto y retención innecesaria de datos personales (`CON-10`) | ⚠️ | — |
| **B3. RBAC grueso en `api-gateway` confiando en cabeceras internas sin firma** | ⚠️ | — | — | ❌ un servicio interno comprometido suplanta cualquier `usuario_id` | ⚠️ si filtra por lista negra, un campo nuevo se escapa |
| **B4. Autenticación OIDC en borde + políticas declarativas ABAC con vales firmados + verificación ligera por código de un solo uso (OTP) al correo designado + DTO de lista blanca para redes** ⬅ **elegido** | ✅ verifica posesión real del correo designado en el 100 % de los casos | ✅ acceso invitado de alcance acotado sin obligar a abrir cuenta completa | ⚠️ un único paso de código al correo | ✅ cada servicio verifica el JWT/vale firmado contra el recurso | ✅ los campos sensibles no existen en `ResumenPublicable` |

### Por qué B4

**B1** es la trampa habitual cuando se busca bajar fricción: un enlace con token secreto sigue siendo
un enlace de capacidad, descartado en `ADR-0007` porque un reenvío o captura de pantalla viola
literalmente el `100 %` exigido por `QA-12`. **B2** obliga a una persona que solo quería mirar a qué
hora aterriza un familiar a aceptar términos y abrir una cuenta permanente, chocando además con el
principio de minimización de datos (`CON-10`). **B3** expone el interior del clúster al *confused
deputy*.

**B4** demuestra la propiedad exacta que importa —que quien abre el enlace controla efectivamente la
dirección de correo incluida en `designados`— mediante un desafío OIDC sin contraseña (OTP de 6
dígitos al correo autorizado, con mensaje neutro anti-enumeración) que emite un token efímero de
alcance exclusivo `lectura:comparticion:{id}`, sin crear perfil permanente de viajero. Para las redes
sociales (`RF-13`), en lugar de «borrar campos prohibidos» (lista negra frágil ante evoluciones del
modelo), construye un tipo separado por **lista blanca** donde jamás pueden viajar localizadores ni
documentos.

→ [ADR-0028](../../03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md)

---

## D29 — Cifrado por sobres, custodia, detección anómala y revocación de claves (`QA-13`, `CRN-05`)

**Problema:** custodiar el acceso delegado a `9 millones` de buzones de correo (`ASR-5` / `QA-13`)
bajo la hipótesis de que un atacante **ya comprometió otro servicio interno** exige que ningún otro
proceso pueda descifrar tokens, auditar el `100 %` de los accesos, detectar extracción masiva en
`≤ 5 minutos`, rotar claves sin corte y poder revocar toda una región en `≤ 15 minutos`.

| Alternativa | Aislamiento ante servicio comprometido (`QA-13`) | Rotación de claves sin inactividad (`CRN-05`) | Revocación regional ≤ 15 min (`QA-13`) | Apoyo a supresión por usuario (`QA-14`) | Latencia / Costo KMS (`CRN-08`) |
|---|---|---|---|---|---|
| **C1. Clave simétrica única por entorno inyectada por variable de entorno** | ❌ cualquier lectura de configuración o volcado de memoria entrega los 9 M de buzones | ❌ rotar obliga a recifrar toda la tabla de golpe | ❌ | ❌ | ✅ |
| **C2. Cifrar cada token llamando directo al HSM/KMS en cada operación (sin `DEK` intermedia)** | ✅ si se restringe IAM a `identity-access` | ✅ gestionada en KMS | ✅ inhabilitando la clave KMS | ❌ no hay clave individual por usuario para cripto-supresión | ❌ cuotas y costo por llamada KMS a escala de millones de buzones |
| **C3. Cifrado por sobres (*envelope encryption*: `KEK_region` en HSM/KMS + `DEK_u` por usuario) + mTLS por identidad de carga + detector de tasa en tiempo real (`≤ 2 min`) + revocación en dos fases (`≤ 12 min`)** ⬅ **elegido** | ✅ solo `identity-access` (mTLS/SPIFFE) puede desenvolver `DEK_u` en KMS | ✅ `key_version` permite convivir `KEK vN` y `vN+1` sin corte | ✅ bloqueo KMS en `< 30 s` + revocación OAuth paralela en `≤ 12 min` | ✅ destruir `DEK_u` inutiliza al instante todo cifrado del usuario | ✅ cacheo efímero acotado en enclave de memoria reduce llamadas KMS |

### Por qué C3

**C1** fracasa ante el modelo de amenaza explícito de `QA-13`. **C2** protege bien el perímetro de
`identity-access`, pero ata cada lectura de buzón a una llamada directa a KMS (cara y sujeta a límites
de tasa) y no brinda aislamiento criptográfico entre un usuario y otro.

**C3** adopta el estándar industrial de bóvedas a gran escala: una clave de datos única por usuario
(`DEK_u`) envuelta bajo la clave maestra del HSM regional (`KEK_region`), accesible exclusivamente a
la identidad criptográfica de `identity-access` (`Regla R5`). Esto multiplica los beneficios hacia el
resto de la iteración: rotar `KEK_region` solo re-envuelve claves pequeñas sin tocar datos masivos;
destruir `DEK_u` resuelve la cripto-supresión instantánea de `D30`; y si el detector de auditoría ve
una ráfaga anómala de emisiones, corta la credencial de la instancia en `≤ 2 minutos` (`< 5 min`) y
ejecuta el *kill-switch* regional dentro de los `15 minutos` comprometidos.

→ [ADR-0029](../../03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md)

---

## D30 — Auditoría e implementación de supresión de datos personales en ambos planos (`QA-14`, `CON-10`)

**Problema:** `QA-14` exige entregar el inventario de datos personales y su historial de accesos en
`≤ 72 horas` y completar la supresión verificable en **`≤ 30 días` en el 100 % de los almacenes,
incluido `analytics-store`**. En un almacén columnar sobre archivos Parquet inmutables (`ADR-0003`),
ejecutar un `DELETE` fila por fila tras cada baja reescribiría terabytes continuamente, arruinando el
costo (`CRN-08`) y el rendimiento analítico (`QA-09`).

| Alternativa | Cumple supresión en 100 % de almacenes ≤ 30 días (`QA-14`) | Preserva métricas históricas de negocio (`RF-14`) | Costo e impacto en `analytics-store` (`CRN-08` / `QA-09`) | Verificabilidad ante auditoría (`CON-10`) |
|---|---|---|---|---|
| **E1. Borrar solo en OLTP y argumentar que `analytics-store` ya tiene seudónimos** | ❌ un seudónimo fijo con tabla de enlace viva **sigue siendo dato personal bajo GDPR** (Art. 4.5) | ✅ | ✅ cero costo en Parquet | ❌ incumplimiento legal |
| **E2. Reescribir inmediatamente los archivos Parquet ante cada baja individual** | ✅ | ❌ si borra hechos enteros distorsiona series históricas de cancelaciones/destinos | ❌ amplificación masiva de escritura en almacenamiento de objetos | ✅ |
| **E3. Cripto-supresión pura sin tocar nunca Parquet** | ⚠️ suficiente para copias cifradas, pero deja filas individuales por seudónimo en tablas analíticas activas | ✅ | ✅ | ⚠️ discutible ante auditores que exigen purga de registros individuales |
| **E4. Protocolo híbrido en dos fases: borrado físico OLTP + destrucción inmediata de `DEK_u` y `mapa_seudonimo_usuario` (`< 24 h`) + lista de exclusión en lectura + compactación Parquet quincenal (`≤ 25 d`) que purga filas individuales conservando solo agregados anónimos** ⬅ **elegido** | ✅ desvinculado en `< 24 h` y purgado físicamente de Parquet en `≤ 25 d < 30 d` | ✅ los cubos agregados anónimos de tendencias/destinos no pierden exactitud | ✅ agrupa todas las bajas de 15 días en una única pasada de compactación | ✅ emite certificado verificable con `0` filas vinculables |

### Por qué E4

**E1** comete el error jurídico más común en ingeniería de datos: confundir *seudonimización* con
*anonimización*. Mientras exista forma de reidentificar o singularizar la trayectoria completa de una
persona, GDPR aplica íntegramente. **E2** resuelve lo legal destruyendo la economía del almacén
columnar.

**E4** aprovecha la ventana legal de `30 días` de `QA-14` con rigor técnico y jurídico: en las
primeras `24 horas` borra físicamente todo el *bucket* operacional del usuario, destruye `DEK_u` e
invalida para siempre el vínculo `usuario_id ↔ seudonimo_analitico`, filtrando además el seudónimo en
la vista de consulta analítica desde el minuto uno; y cada `15 días` un trabajo por lotes reescribe de
una sola vez las particiones Parquet tocadas, consolidando su aporte en contadores agregados no
individualizables (`k ≥ 50`) y purgando las filas individuales antes del día `30`.

→ [ADR-0030](../../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md)

---

## D31 — Residencia de datos por región y resolución de `R-6` (`CRN-15`, `CON-10`, `QA-18`)

**Problema:** cerrar **`R-6`**: en `D18` ([ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md)),
confirmar comandos manuales con `RPO = 0` (`QA-05`) utiliza un registro testigo y réplicas en una
`región_respaldo`. Si para un ciudadano europeo los datos personales en claro cruzaran libremente a
otra jurisdicción sin salvaguarda técnica, se violaría `CON-10` (GDPR); pero si se prohibiera todo
respaldo fuera de una única región física, al caer esa región se violaría `QA-05`.

| Alternativa | Cumple residencia normativa (`CON-10` / `CRN-15`) | Mantiene `QA-05` (`RPO = 0` y redirección ≤ 60 s ante caída regional) | Viajero consultando su viaje desde otro continente (`QA-02`) | Incorporar nueva región (`QA-18`) |
|---|---|---|---|---|
| **F1. Confinar el 100 % de los datos y réplicas dentro de una única región de nube** | ✅ trivial | ❌ **destruye `QA-05`:** si cae la región europea, sus usuarios quedan caídos y pierden disponibilidad | ⚠️ siempre paga RTT intercontinental | ✅ |
| **F2. Replicar todos los datos personales en texto claro a las 3 regiones amparándose solo en cláusulas contractuales** | ❌ exposición innecesaria de PII en jurisdicciones ajenas; alto riesgo ante *Schrems II* / equivalencia | ✅ | ✅ | ❌ bloquea entrar en países con residencia estricta |
| **F3. Clasificación en 3 clases (`R1` estricto local, `R2` contingencia cifrada en origen con clave jurisdiccional —*ciphertext-only witness*—, `R3` analítica anónima global) + motor declarativo de política por región** ⬅ **elegido** | ✅ `R1` nunca sale de la región; `R2` fuera de origen es texto cifrado ilegible sin `KEK` jurisdiccional | ✅ el testigo transregional persiste el bloque cifrado con `RPO = 0` | ✅ lectura en tránsito amparada por ejecución del viaje en caché efímera cifrada | ✅ nueva región = nueva entrada declarativa en `politica_residencia` |

### Por qué F3

**F1** y **F2** sacrifican un driver innegociable cada una (`QA-05` o `CON-10`). **F3** arbitra la
tensión separando **qué datos existen** y **quién posee la capacidad criptográfica de leerlos**:

1. Los datos de identidad directa y los tokens de correo (`Clase R1`) viven **exclusivamente** en la
   `región_primaria`.
2. El registro testigo y la réplica de contingencia de `D18` (`Clase R2`) almacenan el sobre cifrado
   con `DEK_u` (envuelta por la `KEK` bajo custodia jurisdiccional primaria, p. ej. HSM dentro del
   Espacio Económico Europeo multi-región KMS): el nodo testigo garantiza durabilidad física (`RPO =
   0`) sin poder inspeccionar un solo carácter personal en reposo.
3. Los eventos que cruzan a `analytics-store` (`Clase R3`) salen ya truncados y seudonimizados en el
   borde regional de `event-pipeline`.

Así **`R-6` queda cerrado** preservando intactas tanto `ADR-0018` como `CON-10`.

→ [ADR-0031](../../03-adr/ADR-0031-residencia-de-datos-por-region.md)

---

## D32 — Estrategia de internacionalización y localización (`QA-18`, `CRN-10`)

**Problema:** operar en múltiples mercados e incorporar una región nueva en `≤ 120 horas-persona` con
**`0` cadenas embebidas en código** y **`0` modificaciones en servicios de lógica de negocio**,
soportando pluralización compleja, monedas diversas y múltiples husos horarios dentro de un mismo
viaje.

| Alternativa | QA-18: 0 servicios de dominio tocados al sumar idioma | Despliegue de correcciones de traducción | Viajes que cruzan múltiples husos horarios | Funciona sin red en móvil (`QA-03` / `QA-17`) |
|---|---|---|---|---|
| **G1. Traducir y formatear cadenas dentro de cada microservicio de dominio** | ❌ cada servicio acopla idioma y presentación | ❌ corregir un texto obliga a redesplegar *backend* | ⚠️ propenso a convertir horas al huso del servidor | ⚠️ |
| **G2. Paquetes de localización compilados únicamente dentro del binario móvil/web** | ✅ | ❌ corregir una traducción en móvil exige revisión de tienda de aplicaciones | ✅ | ✅ |
| **G3. Dominio neutral (`UTC + IANA TZ` y códigos ISO) + catálogos ICU MessageFormat externalizados en CDN con paquete base empacado en móvil + formateo CLDR nativo en bordes de presentación (`app-*`, `notification`)** ⬅ **elegido** | ✅ `0` lógica de dominio conoce idiomas | ✅ actualización en caliente desde CDN con versión e integridad | ✅ cada tramo conserva la zona IANA física de su lugar de salida/llegada | ✅ `app-movil` empaca el idioma activo y actualiza deltas en segundo plano |

### Por qué G3

En un sistema de viajes, el error clásico de internacionalización no es solo dejar textos fijos en
español: es convertir un horario de vuelo al huso horario actual del teléfono del usuario y hacerle
perder el avión. **G3** impone por contrato que todo instante de segmento transporte `{ instanteUTC,
zonaHorariaIANA }` del lugar físico del evento (`iteración 2 §5.2`), mantiene al dominio libre de
cadenas humanas, sirve catálogos `ICU MessageFormat` desde `edge` y verifica con análisis estático en
CI la ausencia total de literales embebidos (`QA-18`).

→ [ADR-0032](../../03-adr/ADR-0032-internacionalizacion-y-localizacion.md)

---

## D33 — Capacidades nativas de ubicación (GPS) y degradación en móvil (`QA-17`)

**Problema:** destacar sin interacción adicional el segmento pertinente del viaje cuando el viajero
abre la app cerca del aeropuerto, estación u hotel (`≥ 90 %` de los casos), garantizando que la
aplicación siga siendo completamente funcional si el permiso de GPS está denegado o no hay red, y sin
convertir a Trotamundos en un recolector permanente de geolocalización personal (`CON-10`).

| Alternativa | QA-17: segmento pertinente visible ≥ 90 % | Privacidad y minimización (`CON-10`) | Consumo de batería móvil y red (`QA-03`) | Funciona sin señal / en modo avión o sin permiso GPS |
|---|---|---|---|---|
| **H1. Envío continuo de coordenadas GPS en segundo plano al servidor (`bff-mobile`)** | ✅ | ❌ crea un historial sensible de movimientos físicos del usuario en el servidor | ❌ drena batería y suma un salto de red en el arranque | ❌ falla en modo avión o subte |
| **H2. Selección puramente por reloj sin usar nunca el GPS** | ❌ falla en escalas demoradas, llegadas tempranas al aeropuerto o estadías con varios segmentos el mismo día | ✅ | ✅ | ✅ |
| **H3. Geocodificación previa de lugares del viaje + resolución espacial en el dispositivo (*on-device*) al abrir la app + caída automática a heurística temporal cuando no hay permiso o señal** ⬅ **elegido** | ✅ combina cercanía física a los puntos del viaje con ventana horaria | ✅ la posición GPS nunca sale del teléfono del viajero | ✅ lectura puntual en primer plano (`0` rastreo continuo de fondo) | ✅ degrada instantáneamente a orden cronológico sobre la instantánea local |

### Por qué H3

Para saber a cuál de las **propias reservas del viajero** está llegando hoy no hace falta mandar su
GPS a la nube: el teléfono ya tiene descargado el viaje `EnCurso` con las coordenadas de sus
aeropuertos, estaciones y hoteles (`D19`). **H3** resuelve el cruce geométrico y temporal en pocos
microsegundos dentro de `app-movil`, cumple `QA-17` incluso sin conectividad móvil en una terminal
subterránea, ahorra batería, elimina de raíz una categoría entera de datos personales sensibles en el
servidor (`CON-10`), y trata la denegación del permiso GPS como un camino ciudadano de primera clase.

→ [ADR-0033](../../03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md)

---

## D34 — Punto de extensión para el módulo avanzado y recorte de la 2da entrega (`CON-06`, `CON-05`)

**Problema:** garantizar que cualquiera de los dos módulos avanzados obligatorios de la 2da entrega
(Opción A — recomendación *human-in-the-loop*, u Opción B — asistente virtual conversacional) pueda
incorporarse **sin rediseñar servicios ni interfaces existentes**, manteniendo `< 15` elementos
(`CON-A4`).

| Alternativa | Cero cambios estructurales al elegir A o B (`CON-06`) | Respeta `CON-A4` (`< 15` elementos) | Aislamiento de fallas y degradación (`QA-04`) | Claridad de frontera con el dominio |
|---|---|---|---|---|
| **J1. Embeber la lógica de recomendación o del chatbot dentro de `itinerary`** | ❌ infla y modifica el núcleo más crítico del sistema (`R-5`) | ✅ | ❌ una consulta lenta de IA/recomendación compite con el dominio | ❌ contamina el modelo canónico |
| **J2. Construir un *framework* genérico especulativo de agentes/plugins antes de elegir A o B** | ⚠️ | ❌ sobreingeniería costosa para 4 personas (`CON-09`, `CON-05`) | ⚠️ | ❌ abstracción prematura |
| **J3. Alojar el módulo elegido como el elemento autónomo nº 14 acoplado únicamente a los eventos del *broker* y a las APIs existentes de `itinerary`, `support-liaison` y `analytics-store`, exponiendo sus rutas propias vía `bff-*`** ⬅ **elegido** | ✅ verificado en papel para A y para B con `0` interfaces nuevas en el dominio | ✅ `13 + 1 = 14 < 15` | ✅ entra en el nivel degradable sin afectar el panel | ✅ el dominio sigue siendo dueño único de `Reserva`, `Viaje` y `Caso` |

### Por qué J3

Tanto un sistema de recomendación como un asistente virtual son **consumidores de contexto y emisores
de intenciones**, nunca dueños del estado autoritativo de una reserva. Como `itinerary` ya publica
eventos de ciclo de vida en el *broker* y expone lectura/comandos REST, `support-liaison` ya expone
`POST /casos` y `analytics-store` ya concentra el historial analítico, **J3** demuestra que la
arquitectura actual ya contiene todas las costuras necesarias sin escribir ni una línea de código
especulativo hoy, y establece además la regla de recorte vertical sobre los 5 ASRs (`CON-05`) para la
implementación del prototipo.

→ [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md)

---

## D35 — Tratamiento de buzones sin OAuth y flujo ante formatos desconocidos (`CON-08`, `QA-11`)

**Problema:** cerrar los dos bordes pendientes del plano de correo: (1) cómo soportar usuarios cuyo
servidor de correo corporativo o regional no ofrece OAuth 2.0 (`E-06`, asunto abierto de `ADR-0007`)
sin pedir ni guardar jamás su contraseña primaria (`CON-08`), y (2) cómo cerrar la experiencia y la
evolución cuando un correo válido de viaje viene en un formato desconocido (`QA-11` / `R-2`).

| Alternativa | Cumple `CON-08` (acceso seguro y autorizado, sin clave maestra) | Cobertura de usuarios sin Gmail/Microsoft (`RF-01`, `RF-02`) | QA-11: 0 % datos erróneos silenciosos | QA-11: incorporar nuevo formato ≤ 16 h-p |
|---|---|---|---|---|
| **K1. Pedir y guardar cifrada la contraseña principal IMAP del usuario** | ❌ **viola `CON-08`** y amplifica el impacto de `QA-13` (acceso total a la cuenta) | ✅ | — | — |
| **K2. Bloquear por completo a todo usuario cuyo correo no sea Gmail o Microsoft 365** | ✅ | ❌ deja sin ingesta automática a usuarios con correo propio o corporativo | — | — |
| **K3. Prohibir contraseñas primarias + ofrecer dirección de reenvío dedicada verificada (`DKIM/SPF`) como vía universal + IMAP solo con `XOAUTH2` o clave de aplicación revocable + cuarentena de huella estructural anónima y borrador asistido al usuario** ⬅ **elegido** | ✅ jamás se solicita ni almacena la contraseña primaria del buzón | ✅ el reenvío verificado cubre el 100 % de proveedores de correo | ✅ nunca inserta en `Reserva` sin confianza alta o confirmación explícita | ✅ agrupa huellas estructurales sin PII y genera esqueleto de prueba |

### Por qué K3

**K1** está prohibida por la restricción `CON-08`, y **K2** recorta artificialmente el mercado
internacional (`QA-18`). **K3** combina el patrón probado en la industria de viajes (alias único de
reenvío autenticado por criptografía de correo `DKIM/SPF` y revocable sin credenciales) con soporte
IMAP restringido a mecanismos delegados revocables; y del lado de la extracción, transforma un formato
desconocido en un flujo seguro de dos salidas: **asistencia inmediata al viajero** (alta manual
pre-poblada sin ensuciar el itinerario) y **telemetría estructural sin PII** para escribir el nuevo
complemento extractor en `≤ 16 horas-persona`.

→ [ADR-0035](../../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md)

---

## Tácticas y patrones de atributos de calidad aplicados en esta iteración

Trazabilidad explícita hacia el catálogo de tácticas arquitectónicas (§5 del enunciado):

| Atributo | Táctica / Patrón | Dónde se aplica | Decisión |
|---|---|---|---|
| Seguridad (Resistir ataques) | Autenticar actores + Autorizar actores (OIDC + ABAC con vales firmados) | Federación en `autenticacion-oidc`, OTP para designados sin cuenta y validación ABAC en `sharing`/`itinerary` evitando *diputado confundido* | D28 |
| Seguridad (Resistir ataques) | Cifrar datos y separar custodia de claves (*Envelope Encryption*) | `DEK_u` por usuario envuelta con `KEK_region` en HSM/KMS; `identity-access` único con permiso `Decrypt` vía mTLS | D29 |
| Seguridad (Resistir ataques) | Limitar exposición y alcance (*Least Privilege* / tokens efímeros + proyección por lista blanca) | Tokens de correo con `TTL ≤ 15 min` en memoria para `mail-ingest`; DTO `ResumenPublicable` sin campos sensibles; prohibición de claves maestras IMAP | D28, D29, D35 |
| Seguridad (Detectar y Reaccionar) | Detectar intrusión por anomalía de tasa + Revocar acceso | Detector sobre auditoría de `VAULT` que corta credenciales en `≤ 2 min` (`< 5 min`) y *kill-switch* regional en `≤ 12 min` (`< 15 min`) | D29 |
| Seguridad / Privacidad (Auditar y Recuperar) | Mantener rastro de auditoría inmutable + Cripto-supresión y compactación diferida | `registro_auditoria` encadenado (`≤ 72 h` acceso) + destrucción de `DEK_u`/vínculo y barrido Parquet quincenal (`≤ 30 días`) | D30 |
| Privacidad / Cumplimiento | Minimización de datos en origen y confinamiento jurisdiccional | Sin cuerpo de correo (`AMB-09`), GPS evaluado en el dispositivo (`D33`) y registro testigo cifrado bajo clave jurisdiccional (`R-6` cerrado) | D31, D33, D35 |
| Interoperabilidad / Integrabilidad | Adherir a protocolos + Gestionar evolución de interfaces (*Tolerant Reader* / *SemVer*) | Reglas de compatibilidad OpenAPI/AsyncAPI, cabeceras `Deprecation`/`Sunset` y contratos versionados de complementos | D27 |
| Modificabilidad / Evolucionabilidad | Restringir dependencias + Diferir enlace (*Plugin* / Configuración declarativa) | Incorporación de proveedores (`QA-10`), medios de transporte (`QA-15`), regiones (`QA-18`) y módulo avanzado nº 14 (`CON-06`) sin tocar servicios de dominio | D27, D32, D34 |
| Usabilidad e Internacionalización | Soportar iniciativa del sistema con degradación + Externalizar localización | Tarjeta contextual por geocerca local con caída a reloj si no hay GPS (`QA-17`); catálogos ICU en CDN e instantes `UTC + IANA TZ` (`QA-18`) | D32, D33 |
