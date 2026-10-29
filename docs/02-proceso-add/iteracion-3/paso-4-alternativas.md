# Iteración 3 · Paso 4 — Conceptos de diseño y alternativas

Este es el paso donde ADD exige **considerar alternativas antes de elegir**. Para cada una de las
nueve decisiones de la iteración (`D18` a `D26`) se evalúan conceptos de diseño candidatos contra los
drivers seleccionados, dejando explícito qué se gana, qué se sacrifica y por qué se descartan las
opciones no elegidas. Cada decisión queda normada en su ADR de numeración homónima (`D18` →
`ADR-0018`).

Criterio de evaluación usado en todas las tablas: ✅ favorece el driver · ⚠️ lo permite con costo ·
❌ lo compromete · — no aplica.

**Relación entre las decisiones de esta iteración.** La decisión central es **D18** (consistencia
multirregión): condiciona a **D19** (cómo evitar que un usuario vea desaparecer su propia escritura
en la caché), a **D23** (cómo se particionan físicamente los almacenes) y a **D26** (por qué una
región testigo alcanza en la primera etapa). Por su parte, **D20**, **D21** y **D24** forman un
sistema acoplado de control de carga: autoescalar sin contrapresión ni mamparos solo traslada el
cuello de botella al almacén o al proveedor externo.

---

## D18 — Modelo de consistencia de datos entre regiones (`R-1` + `R-4` / `CRN-13`)

**Problema:** [ADR-0002](../../03-adr/ADR-0002-despliegue-multirregion.md) adoptó tres regiones
activas para cumplir `QA-05` (`≤ 60 s` de redirección, `≤ 1,5 min` de presupuesto, **0 pérdida de
datos confirmados**). Sin embargo, aceptar escrituras concurrentes sin coordinación sobre la misma
reserva desde dos regiones rompe la bandeja de entrada de idempotencia de `D14` (`R-4`) y puede
mostrar dos versiones distintas del itinerario (`R-1`), mientras que coordinar cada operación a
través del océano amenaza la latencia interactiva (`QA-02`).

| Alternativa | QA-05: 0 datos confirmados perdidos | QA-05: redirección ≤ 60 s | R-4 / CRN-12 (idempotencia por usuario) | QA-02 (lectura ≤ 800 ms) | Viajero escribiendo fuera de su región | CON-09 / Complejidad |
|---|---|---|---|---|---|---|
| **R1. Partición por usuario con región de origen pura** (asíncrona a réplicas; sin testigo transregional) | ❌ la ventana `< 1 s` aún no replicada al caer la región primaria se pierde incluso para comandos ya confirmados | ✅ | ✅ todo lo de un usuario pasa por un único primario | ✅ lecturas locales en cualquier región | ⚠️ paga RTT inter-regional en escrituras manuales | ✅ simple de razonar |
| **R2. Escritura libre en las tres regiones con tipos convergentes puros (CRDT)** | ⚠️ sigue habiendo ventana asíncrona ante caída súbita | ✅ cero conmutación de liderazgo | ❌ dos regiones pueden aceptar en simultáneo el mismo mensaje y disparar efectos laterales duplicados (notificaciones, casos) | ✅ | ✅ escritura local siempre | ❌ exige modelar invariantes de negocio enteras como semirretículos |
| **R3. Consenso síncrono global en cada escritura** (quórum transoceánico entre las 3 regiones) | ✅ linealizable | ✅ la mayoría sobreviviente (`2/3`) sigue operando | ✅ | ⚠️ si las lecturas fuertes también piden quórum global, rompe los 80 ms de datos | ❌ toda escritura de ingesta y de usuario paga `120–250 ms` por transacción | ⚠️ |
| **R4. Región primaria por usuario con quórum intra-región + testigo transregional en comandos manuales + fusión determinista (D10/D13) ante *failover* + lectura causal por sesión** ⬅ **elegido** | ✅ RPO = 0 para comandos confirmados y re-ingesta idempotente para fuentes automáticas | ✅ promoción determinista a `región_respaldo` en `≤ 45 s` | ✅ en operación normal 100 % de las escrituras del usuario van a su partición primaria | ✅ lecturas siempre locales, con *read-your-writes* por versión en sesión | ⚠️ ~90–140 ms extra solo en comandos manuales (`< 15 req/s` globales) | ⚠️ combina piezas ya diseñadas en D10/D13/D14 |

### Por qué R4

**R3** es la tentación de quien quiere resolver `R-1` comprando una base globalmente linealizable y
olvidándose del tema: fracasa en costo y en latencia de escritura para el flujo continuo de ingesta
(`45` a `450 eventos/s`, con múltiples pasos transaccionales por evento).

**R2** aprovecha que `D10` y `D13` ya diseñaron `Observacion` como estructura solo agregable y de
fusión determinista, pero **no resuelve `R-4`**: aunque el estado final de `Reserva` converja tarde o
temprano, si dos regiones procesan a la vez la misma notificación antes de ver la `bandeja_entrada`
de la otra, ambas emiten eventos aguas abajo y `notification` despierta dos veces al viajero.

**R1** resuelve `R-4` con limpieza, pero incumple literalmente una cláusula de `QA-05`: si un
usuario crea una reserva manual en Europa, recibe `201 Created`, y `200 ms` después cae la región
europea antes de que salga la replicación asíncrona, ese dato confirmado se pierde.

**R4 corrige el único punto débil de R1 aplicando garantías diferenciadas por capacidad** (la regla
de CAP por operación, no monolítica para todo el sistema):

1. **Propiedad de escritura por `región_primaria`.** Cada `usuario_id` tiene una región dueña donde
   residen el primario de su partición, su suscripción activa de `mail-ingest` y su índice en
   `provider-sync`. Toda escritura de ese usuario se serializa allí con quórum síncrono en 2 de 3
   zonas de disponibilidad (`~3 ms`). Eso cierra `R-4` y `CRN-12` sin coordinación global.
2. **Testigo transregional selectivo para comandos manuales.** Solo cuando el humano ejecuta un
   comando mutativo (`POST/PUT/DELETE /reservas`, resolución de conflicto, `POST /casos` — menos de
   `15 req/s` en todo el sistema), `itinerary-escritura` persiste sincrónicamente un registro testigo
   compacto en la `región_respaldo` del usuario (`~70–90 ms` por red privada del proveedor de nube)
   antes de responder `200/201`. Las fuentes automáticas (correo y proveedores) no pagan ese salto
   porque la fuente externa ya retiene el mensaje original y la reconciliación lo reingresa.
3. **Conmutación con fusión convergente.** Si cae la `región_primaria`, la `región_respaldo` aplica
   los registros testigo pendientes y asume la escritura. Cuando la región caída regresa, cualquier
   observación automática en vuelo se reconcilia sin pérdida gracias a la fusión determinista de
   `D10`/`D13`.
4. **Consistencia causal (*read-your-writes*).** Toda mutación devuelve `version_usuario`; si un
   viajero en tránsito consulta la réplica local antes de que llegue la replicación asíncrona (`< 1
   s`), el BFF detecta `X-Min-Version > version_local` y sirve el estado recién escrito desde caché
   de sesión o desde su primario. El usuario jamás ve desaparecer lo que acaba de guardar.

**Lo que esta decisión habilita para la iteración 4.** Asignar a cada usuario una `región_primaria`
deja tendido el riel estructural para `CRN-15` (residencia normativa de datos personales), dejando a
la iteración 4 únicamente la política de cifrado/alcance de lo que cruza hacia la `región_respaldo`
(registrado como riesgo `R-6`).

→ [ADR-0018](../../03-adr/ADR-0018-consistencia-datos-multirregion.md)

---

## D19 — Estrategia de caché del camino de lectura y arranque móvil (`QA-02`, `QA-03`)

**Problema:** el presupuesto de `QA-02` exige `≤ 80 ms` en el tramo de acceso a datos con al menos
`90 %` de aciertos a `3.000 req/s`, mientras que `QA-03` exige pintar el primer contenido móvil en
`≤ 1,4 s` sobre 4G (`150 ms` RTT, `1,6 Mbps`), sin violar la frescura de `QA-01` ni exponer datos
personales en cachés compartidas de borde.

| Alternativa | QA-02 (≤ 80 ms a 3.000 req/s) | QA-03 (FCP ≤ 1,4 s en 4G) | QA-01 (frescura tras cambio) | Seguridad / Privacidad | Complejidad de invalidación |
|---|---|---|---|---|---|
| **S1. Sin caché dedicada** (solo lectura directa sobre réplicas relacionales de `panel_usuario`) | ⚠️ cumple en valle, pero a `3.000–9.000 req/s` satura conexiones e IOPS | ❌ no ayuda al arranque en frío móvil | ✅ cero desfase adicional | ✅ | ✅ ninguna |
| **S2. Caché de respuestas completas del panel en el borde público (CDN)** | ✅ latencia mínima | ⚠️ solo sirve en reingresos | ❌ purgar por evento millones de URLs en CDN agrega segundos y riesgo de servir datos viejos | ❌ un error de cabecera (`Cache-Control`) filtra un itinerario ajeno | ❌ muy frágil |
| **S3. Caché en memoria dentro de cada proceso de `bff-*` / `itinerary-lectura`** | ✅ sin salto de red interno | ❌ | ❌ cada réplica desincroniza por su cuenta; al escalar horizontalmente cae la tasa de acierto | ✅ | ❌ requiere difusión a todas las instancias |
| **S4. Caché multinivel acotada: estáticos y descriptores en CDN + proyección en clúster regional en memoria invalidada por eventos + instantánea local cifrada y carga diferida en móvil** ⬅ **elegido** | ✅ `~12 ms` en acierto (`≥ 92 %`), `~58 ms` en fallo | ✅ `1.180 ms` en frío puro (`≤ 15 KB`) y `≤ 250 ms` con instantánea local | ✅ actualización/invalidación en `< 5 ms` al publicar eventos de dominio | ✅ cero PII en CDN; almacenamiento local cifrado | ⚠️ dos puntos claros con reglas explícitas |

### Por qué S4

**S2** se descarta de plano por seguridad y por el antipatrón clásico de envenenamiento de caché en
el borde: un itinerario contiene datos personales sensibles y cambia de forma impredecible ante
eventos externos. El CDN se reserva estrictamente para recursos estáticos inmutables y para el
catálogo público `GET /tipos-de-segmento`.

**S3** fracasa justo cuando entra en acción el autoescalado de `QA-04`: al levantar decenas de
réplicas nuevas de `itinerary-lectura`, todas nacen con su memoria vacía y golpean juntas a la base
de datos.

**S4** coloca una **única caché compartida de datos de dominio por región** (clúster en memoria
particionado por `usuario_id`) alimentada e invalidada directamente por `proyeccion-panel` al
consumir los eventos de `itinerary` y `preferences`. Como no hay TTLs anidados de datos personales
entre capas, la antigüedad máxima está bajo control directo del dominio (TTL de resguardo de `15
min`, más `ETag` para respuestas `304 Not Modified` y `marcaFrescura` obligatoria para cumplir
`ADR-0008`). En el móvil, el contrato acotado de `GET /panel/resumen` (`≤ 15 KB` comprimido), el
motor precompilado y la carga diferida de detalles secundarios hacen cerrar los `1.400 ms` incluso
sin caché previa, mientras que la instantánea local cifrada vuelve instantáneas las aperturas
subsiguientes durante el viaje.

→ [ADR-0019](../../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md)

---

## D20 — Contrapresión y comportamiento ante sobrecarga (`QA-04`)

**Problema:** ante una disrupción climática o huelga masiva, el tráfico de lectura se triplica sin
aviso (`3.000 → 9.000 req/s`) al mismo tiempo que los eventos de correo se multiplican por diez (`45
→ 450 eventos/s`). El sistema no puede perder ni una actualización y debe sostener el panel en `p95 ≤
1.500 ms` sacrificando primero lo secundario.

| Alternativa | QA-04: 0 actualizaciones perdidas | QA-04: panel p95 ≤ 1.500 ms | Prioridad de vuelos críticos sobre correo futuro | Protección contra tormenta de reintentos | Complejidad |
|---|---|---|---|---|---|
| **T1. Rechazo plano por límite de tasa global (`HTTP 429`)** | ❌ puede rechazar *webhooks* de proveedores que no reintentan igual | ✅ protege a fuerza bruta | ❌ descarta por orden de llegada, sin mirar importancia | ⚠️ si no devuelve `Retry-After` con *jitter*, sincroniza reintentos | ✅ |
| **T2. Encolado ilimitado en memoria y en el *broker*** | ⚠️ la memoria explota (OOM) en los receptores sincrónicos | ❌ las peticiones HTTP acumulan segundos de espera y vencen en cascada | ❌ bloqueo de cabecera de línea (*head-of-line blocking*): 100.000 correos de viajes del mes próximo tapan una cancelación de hoy | ❌ el cliente reintenta mientras el servidor sigue procesando la petición vieja | ✅ |
| **T3. Interruptores manuales operados por guardia** | ⚠️ | ❌ para cuando un humano interviene ya se consumieron los 5 min mensuales | ❌ | ❌ | ✅ |
| **T4. Contrapresión extremo a extremo + plazo propagado (`X-Deadline-Ms`) + tres carriles de prioridad en el *broker* + degradación automática en 3 modos** ⬅ **elegido** | ✅ receptores `202` livianos + retención durable de 7 días en *broker* | ✅ cancela trabajo vencido y apaga cargas secundarias automáticamente | ✅ carril `P1` garantiza despacho a viajes `EnCurso` y disrupciones | ✅ concurrencia acotada + `Retry-After` aleatorio | ⚠️ requiere probar las transiciones de modo |

### Por qué T4

**T2** reproduce el modo de falla más peligroso de los sistemas distribuidos: cuando todo se encola
sin cota ni plazo, los clientes cortan por *timeout* y vuelven a pedir mientras el *backend* sigue
gastando CPU en respuestas que ya nadie escucha. **T1** protege al servidor sacrificando webhooks y
tratando igual una consulta analítica que un pasajero varado en el aeropuerto. **T3** reacciona en
minutos humanos frente a un presupuesto que se mide en segundos.

**T4** separa la estrategia según la naturaleza del conector:

* En el **camino sincrónico**, propaga el presupuesto restante (`X-Deadline-Ms`), acota colas en
  vuelo por instancia y aplica tres modos automáticos (`Normal`, `Pico elevado`, `Disrupción
  masiva`) alineados exactamente con la frontera de `ADR-0008`: antes de degradar el panel se
  pausan `sharing` (redes), sondeos de baja prioridad y `event-pipeline`.
* En el **camino asíncrono**, los receptores aceptan rápido en el *broker* (cero pérdida) y tres
  carriles de prioridad (`P1` crítico, `P2` estándar, `P3` diferible) impiden que el volumen de
  correos no urgentes postergue avisos de vuelos en curso.

→ [ADR-0020](../../03-adr/ADR-0020-contrapresion-y-sobrecarga.md)

---

## D21 — Estrategia de autoescalado y separación operativa de `itinerary` (`QA-04`, `QA-08`, `R-5`)

**Problema:** `QA-04` fija un tiempo máximo de escalado de **`≤ 3 minutos`** ante una ráfaga súbita,
el enunciado anticipa picos semanales marcados (domingo-lunes y jueves-viernes), y la iteración 2
identificó en `R-5` que concentrar lectura y escritura en un único despliegue de `itinerary` acopla
sus perfiles de escalado y de cambio.

| Alternativa | Picos conocidos (dom-lun / jue-vie) | Ráfaga imprevista (`QA-04` ≤ 3 min) | CRN-08 (costo en horas valle) | R-5 (desacoplar lectura y escritura de `itinerary`) | CON-A4 (< 15 elementos) |
|---|---|---|---|---|---|
| **U1. Escalado puramente reactivo por CPU/memoria**, con un único despliegue de `itinerary` | ⚠️ llega tarde al inicio de cada pico previsible | ❌ la CPU sube cuando las colas ya saturaron, y aprovisionar nodos fríos supera los 3 min | ✅ | ❌ escalar fusión duplica innecesariamente lectura | ✅ |
| **U2. Capacidad fija preaprovisionada 24×7 para 9.000 req/s** | ✅ | ✅ | ❌ multiplica por `~3×` el gasto permanente de cómputo (agrava `R-3`) | ⚠️ | ✅ |
| **U3. Autoescalado híbrido (predictivo por calendario + reactivo por indicadores adelantados + colchón tibio del 15 %) con reducción conservadora y despliegue dual `itinerary-lectura` / `itinerary-escritura`** ⬅ **elegido** | ✅ precalienta 30 min antes del pico semanal | ✅ réplicas listas en `≤ 45 s` y nodos en `≤ 150 s` (`< 3 min`) | ✅ paga el colchón del 15 %, no el 300 % | ✅ escalan, fallan y se despliegan por separado | ✅ mismo módulo lógico y mismos contratos |

### Por qué U3

La CPU es un **indicador atrasado**: en servicios limitados por E/S o por bloqueos de red, la
latencia del usuario ya rompió los `800 ms` antes de que el procesador llegue al `80 %`. Por eso
**U3** dispara el escalado reactivo con **indicadores adelantados** (tasa de peticiones por réplica y
p95 en servicios HTTP; edad del mensaje más antiguo sin procesar en consumidores del *broker*), lo
combina con **escalado predictivo por calendario** para los cuatro días pico conocidos, y mantiene un
`15 %` de capacidad tibia para entrar en la ventana de `≤ 3 minutos`. Además fija techos máximos por
grupo consumidor sincronizados con los cupos de conexión del almacén, evitando que un autoescalador
demasiado veloz tumbe la base de datos.

En el mismo movimiento se cierra operativamente **`R-5`**: desplegar `itinerary-lectura` e
`itinerary-escritura` como dos conjuntos de réplicas independientes desde el mismo código fuente da
aislamiento de recursos, de fallas y de despliegue sin abrir un 14º microservicio ni alterar un solo
contrato publicado.

→ [ADR-0021](../../03-adr/ADR-0021-estrategia-autoescalado.md)

---

## D22 — Despliegue progresivo, reversión automática y compatibilidad de esquemas (`QA-07`, `CRN-04`)

**Problema:** desplegar en horario productivo no puede causar **ni un segundo de inactividad**, una
versión defectuosa no puede afectar a más del **5 % del tráfico**, y debe revertirse sola en **≤ 2
minutos**, incluso cuando el cambio involucra esquemas de base de datos o eventos.

| Alternativa | QA-07: 0 s de inactividad | QA-07: tráfico afectado ≤ 5 % | QA-07: reversión automática ≤ 2 min | Costo de recursos en el despliegue | Seguridad ante cambios de esquema |
|---|---|---|---|---|---|
| **V1. Actualización rotativa simple (*rolling*) simultánea en las 3 regiones** | ✅ con drenaje | ❌ avanza al 25–100 % sin validar SLIs y puede romper las 3 regiones a la vez | ❌ revertir requiere redesplegar instancias viejas | ✅ `N + 1` | ❌ si el esquema cambió de forma incompatible, la reversión falla |
| **V2. Azul-verde (*blue-green*) completo** | ✅ | ❌ conmuta el 100 % del tráfico regional de golpe | ✅ conmutación rápida | ❌ exige `2N` de capacidad durante cada entrega | ❌ igual si el esquema mutó destructivamente |
| **V3. Canario con promoción y reversión manuales** | ✅ | ✅ | ❌ depende de atención humana: no garantiza `≤ 2 min` | ✅ | ⚠️ |
| **V4. Canario secuencial por región (`5 % → 25 % → 100 %`) con reversión automática por SLIs (`≤ 75 s`) + disciplina *expand/contract* e interruptores de funcionalidad** ⬅ **elegido** | ✅ drenaje ordenado de conexiones y particiones | ✅ arranca en `5 %` de 1 región (`~1,7 %` global) | ✅ 2 ventanas de `30 s` + desvío de peso en `≤ 15 s` = `≤ 75 s` | ✅ solo `+5 %` inicial | ✅ versiones `N` y `N+1` siempre coexisten sobre el mismo esquema |

### Por qué V4

**V2** duplica transitoriamente el costo de cómputo y expone al `100 %` de la región en el instante
del corte; **V1** propaga un defecto lógico a todo el mundo antes de detectarlo; **V3** no cumple el
tiempo de reversión de `2 minutos`.

**V4** separa el **despliegue técnico** de la **liberación de tráfico** y ata la segunda a los SLIs
reales medidos cada `30 s`. Pero un desvío de tráfico en `75 segundos` solo funciona si la versión
anterior (`N`) sigue pudiendo leer y escribir la base de datos y los eventos: por eso la regla
*expand/contract* (cambios aditivos primero, contracción en un *release* posterior, verificada en CI
contra migraciones destructivas) no es una recomendación de estilo sino una **condición necesaria**
para que la reversión automática sea real.

→ [ADR-0022](../../03-adr/ADR-0022-despliegue-progresivo-y-reversion.md)

---

## D23 — Particionamiento de datos y plan de crecimiento a 30 M de cuentas (`QA-08`)

**Problema:** duplicar el negocio en 12 meses (`15 M → 30 M` de cuentas, `2 M → 4 M` de usuarios
activos semanales) debe absorberse agregando capacidad horizontal, sin detener el servicio, sin
cambiar contratos entre elementos y sin que el costo crezca más que linealmente.

| Alternativa | Escala de escrituras | 0 inactividad al duplicar | Consultas de un usuario (`QA-02`) | Riesgo de desbalance (*hot shards*) | Crecimiento de costo ≤ lineal |
|---|---|---|---|---|---|
| **W1. Escalado vertical del primario regional + más réplicas de lectura** | ❌ el nodo primario único por región se vuelve techo de escritura e IOPS | ⚠️ cambiar a instancias gigantes suele exigir conmutación | ✅ | ✅ | ❌ las instancias grandes tienen curva de precio supralineal |
| **W2. Particionamiento por rango (fecha de alta o inicial de apellido/país)** | ⚠️ las cuentas recientes concentran casi toda la actividad (*hot shard*) | ⚠️ | ✅ | ❌ sesgo fuerte por cohorte o distribución cultural | ⚠️ |
| **W3. Particionamiento por *hash* consistente sobre `usuario_id` (64 *buckets* lógicos) con división en línea, compactación de observaciones y archivo en frío** ⬅ **elegido** | ✅ escala linealmente agregando fragmentos físicos | ✅ reasignación en línea de *buckets* sin cambiar claves ni contratos | ✅ toda entidad operacional del usuario comparte clave (cero *joins* entre fragmentos) | ✅ distribución uniforme | ✅ compactación + niveles fríos contienen el almacenamiento activo |

### Por qué W3

El trabajo difícil de particionar ya quedó bien preparado en `D10` y `D12`: todas las tablas del
plano operacional llevan `usuario_id` como primera columna de su clave, y ninguna operación del
camino crítico cruza usuarios distintos (la compartición de `RF-11` consulta el viaje puntual por el
`(usuario_id_dueño, viaje_id)` codificado en el recurso). **W3** fija **64 particiones lógicas** por
región desde el inicio mapeadas sobre pocos nodos físicos, de modo que pasar de `15 M` a `30 M`
consiste en mover *buckets* existentes mediante replicación lógica sin tocar una línea de aplicación
(evitando las migraciones de reparticionado que detienen sistemas durante días). La compactación de
`observacion`, el descarte por partición diaria de `bandeja_entrada` y el pase a almacenamiento de
objetos frío de los detalles archivados hace más de 12 meses aseguran que el costo acompañe a los
usuarios **activos**, no a la historia muerta.

→ [ADR-0023](../../03-adr/ADR-0023-particionamiento-y-crecimiento.md)

---

## D24 — Políticas de cortacircuitos, reintentos, pendientes y cuotas de terceros (`QA-06`, `CRN-09`)

**Problema:** con 12 integraciones externas sujetas a caídas de 15+ minutos (`QA-06`) y a cuotas de
tasa estrictas (`CRN-09`), un mal diseño de reintentos tumba el propio sistema o agota la cuota del
proveedor apenas se recupera.

| Alternativa | QA-06: 0 fallos en lectura del panel | QA-06: apertura ≤ 30 s | QA-06: 0 pérdida (cola 24 h) | CRN-09 (respetar cuotas y evitar avalancha al volver) | Complejidad |
|---|---|---|---|---|---|
| **X1. Reintentos inmediatos en línea con *pool* HTTP compartido** | ⚠️ si comparte procesos, contamina | ❌ | ❌ si agota los 3 intentos, pierde el cambio | ❌ multiplica la carga contra un proveedor degradado | ✅ |
| **X2. Cortacircuitos por adaptador que descarta en fallo y delega todo al próximo sondeo** | ✅ | ✅ | ⚠️ proveedores solo-*webhook* o caídas largas pierden cambios o tardan horas | ✅ | ✅ |
| **X3. Mamparo + cortacircuitos de ventana deslizante (`≤ 25 s`) + cola persistente (`24 h`) con retroceso exponencial y *jitter* + presupuesto de cuota por proveedor (80 % tope, 70 % alerta)** ⬅ **elegido** | ✅ lectura del panel 100 % desacoplada | ✅ ventana de `20 s`, abre al `50 %` de error o `5` timeouts | ✅ persiste pendientes hasta `24 h` | ✅ drena pendientes usando como máximo el `50 %` de la cuota disponible | ⚠️ estado de cola y métricas por adaptador |

### Por qué X3

**X1** es el antipatrón clásico de reintentos sin freno: convierte una falla parcial de una aerolínea
en saturación propia. **X2** aísla bien la falla pero deja huecos de recuperación en proveedores que
no exponen consulta histórica completa por rango temporal.

**X3** combina aislamiento físico de recursos por adaptador (mamparo de `50` conexiones), detección
rápida en `≤ 25 s` distinguiendo **indisponibilidad (`5xx`/timeout)** de **cuota agotada (`429`)** y
de **error permanente (`400/401/404`)**, y una `cola_pendientes` durable de `24 h` cuyo drenaje
respeta el limitador de tasa del proveedor para no volver a tirarlo abajo al reconectar. En el mismo
marco fija los intervalos concretos de reconciliación y el objetivo diferenciado de frescura para
IMAP sin *push* que `ADR-0004` había dejado pendientes.

→ [ADR-0024](../../03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md)

---

## D25 — Observabilidad, catálogo de SLIs/SLOs y presupuesto de error (`CRN-03`)

**Problema:** con 13 elementos distribuidos en tres regiones y conectores asíncronos, «mirar la CPU
de las máquinas» no dice si se están consumiendo los `5 minutos/mes` de `ADR-0008` ni permite
rastrear por qué una actualización tardó más de `5 minutos`.

| Alternativa | Medición desde el cliente (`ADR-0008`) | Detección de caída regional ≤ 30 s (`QA-05`) | Rastreo de flujos asíncronos (`QA-01`) | Fatiga de alertas (CON-09: 4 personas) | CRN-08 (costo de ingesta de telemetría) |
|---|---|---|---|---|---|
| **Y1. Alertas por métricas de infraestructura por servidor** (CPU, RAM, disco) | ❌ un servicio puede tener CPU baja y devolver `500` al 100 % | ❌ | ❌ | ❌ tormenta de alarmas sin impacto real | ✅ |
| **Y2. Métricas internas de aplicación sin correlación ni sondas externas** | ❌ no ve fallos de DNS/borde ni lentitud de red cliente | ⚠️ en horas valle sin tráfico real tarda en enterarse | ❌ se corta en el *broker* | ⚠️ | ✅ |
| **Y3. Telemetría OpenTelemetry con `correlation_id` propagado + trazas con muestreo de cola + sondas sintéticas cada 15 s + RUM agregado + alertas por velocidad de consumo (*burn rate*) del presupuesto de error** ⬅ **elegido** | ✅ combina sondas sintéticas, RUM sin PII y telemetría de `edge` | ✅ sondas cada `15 s` desde 6 puntos externos detectan en `≤ 30 s` | ✅ el `idDeCorrelacion` une HTTP y eventos AsyncAPI | ✅ solo despierta a guardia lo que quema presupuesto rápido | ✅ muestreo al `1 %` en éxitos y `100 %` en fallos/lentos |

### Por qué Y3

Para un equipo de cuatro personas (`CON-09`), la fatiga de alertas es tan peligrosa como la falta de
monitoreo. **Y3** adopta el orden de mayor retorno: registros estructurados JSON con
`correlation_id` obligatorio de punta a punta, muestreo inteligente de trazas para no pagar el costo
de guardar el `100 %` de `3.000 req/s` sanas, transacciones sintéticas externas que verifican la
salud semántica cada `15 s` sin depender de que haya usuarios despiertos, y alertas atadas
directamente a la velocidad con que se quema el presupuesto de `5 min/mes` (incluyendo el freno
automático de despliegues funcionales al superar el `75 %` consumido).

→ [ADR-0025](../../03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md)

---

## D26 — Modelo de costo y camino escalonado de infraestructura (`CRN-08` / `R-3`)

**Problema:** operar desde el día 1 tres regiones activas dimensionadas para `15 M` de cuentas más un
almacén analítico columnar dedicado cuesta `~USD 28.500/mes`, lo cual para una *startup* en etapa
temprana crea la presión de abandonar el diseño y pasar a región única o activo-pasivo (`R-3`).

| Alternativa | Viabilidad inicial de startup (`CRN-08`) | Preserva `QA-05` y la arquitectura sin rediseño | QA-09 (aislamiento analítico) | Esfuerzo de transición al crecer (CON-09) |
|---|---|---|---|---|
| **Z1. Tres regiones simétricas a escala plena desde el lanzamiento** | ❌ gasto fijo alto antes de validar ingresos | ✅ | ✅ | ✅ ninguno |
| **Z2. Lanzar en una sola región con base única y rediseñar cuando haya escala** | ✅ el más barato hoy | ❌ destruye `QA-05` y obliga a reescribir particionamiento, consistencia y analítica en el peor momento | ❌ | ❌ retrabajo estructural masivo |
| **Z3. Camino escalonado en 3 etapas sobre la misma arquitectura: (1) 2 regiones activas + 1 testigo de datos y analítica pago por consulta → (2) 3 activas asimétricas → (3) escala 30 M** ⬅ **elegido** | ✅ arranca en `~USD 4.800/mes` (`-83 %`) | ✅ el modelo `D18`, los contratos y el código son idénticos desde el día 1 | ✅ plano analítico separado desde el inicio sobre almacenamiento de objetos | ✅ cambio declarativo de parámetros de IaC |

### Por qué Z3

**Z2** confunde «empezar chico en capacidad» con «empezar con otra arquitectura»: quitar la clave de
partición `usuario_id`, unir los planos operacional y analítico o asumir una única región escribe en
el código supuestos que después cuestan meses desarmar. **Z1** confunde tener la arquitectura lista
con pagar servidores ociosos desde el primer día.

**Z3** mantiene intactos los 13 + 2 elementos, los contratos y el esquema particionado, y gradúa
únicamente **cuántas réplicas de cómputo están encendidas** y **la modalidad de facturación del motor
analítico** (pago por consulta al inicio; capacidad dedicada cuando el volumen de consultas del
equipo de datos lo amortiza). Así `R-3` queda resuelto sin hipotecar ningún ASR.

→ [ADR-0026](../../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md)

---

## Tácticas de atributos de calidad aplicadas en esta iteración

Tabla explícita de trazabilidad hacia el catálogo de tácticas y patrones de diseño (§5 del
enunciado):

| Atributo | Táctica / Patrón | Dónde se aplica | Decisión |
|---|---|---|---|
| Disponibilidad | Redundancia activa + quórum local y testigo transregional | Escritura en 2 de 3 AZs locales + testigo síncrono en `región_respaldo` para comandos manuales | D18 |
| Disponibilidad | Reconfiguración y reintroducción sincronizada | Promoción determinista de `región_respaldo` y sincronización pasiva antes de reincorporar una región | D18 |
| Disponibilidad | Detección por monitoreo sintético (*ping/echo* semántico) | Sondas externas cada `15 s` desde 6 ubicaciones hacia las 3 regiones | D25 |
| Disponibilidad | Cortacircuitos (*circuit breaker*) | Ventana deslizante de `20 s` por adaptador externo en `provider-sync`, `mail-ingest` y `support-liaison` | D24 |
| Disponibilidad | Mamparo (*bulkhead*) | Grupos de conexiones (`máx. 50`) y colas separadas por proveedor externo y entre lectura/escritura | D20, D21, D24 |
| Disponibilidad | Reintento acotado con retroceso exponencial y *jitter* | `cola_pendientes` (24 h) con `5 s × 2^n` y variación `±30 %` solo en fallos transitorios | D24 |
| Disponibilidad | Degradación gradual (*graceful degradation* / *load shedding*) | Tres modos operativos que pausan redes sociales, sondeos fríos y `event-pipeline` antes de afectar el panel | D20 |
| Disponibilidad / Desplegabilidad | Reversión automática (*rollback*) + entrega canaria | Peso inicial del `5 %` en una región a la vez y reversión en `≤ 75 s` ante degradación de SLIs | D22 |
| Desplegabilidad | Gestionar interacciones entre versiones (*expand/contract*) | Cambios aditivos de esquema y eventos compatibles entre versiones `N` y `N+1` | D22 |
| Rendimiento | Mantener múltiples copias de datos (caché + invalidación por eventos) | CDN para estáticos/descriptores, clúster regional en memoria para `panel_usuario` e instantánea móvil | D19 |
| Rendimiento | Reducir sobrecarga computacional y de red | Contrato `GET /panel/resumen ≤ 15 KB`, carga diferida en móvil y `ETag` (`304`) | D19 |
| Rendimiento | Acotar tiempos de ejecución (*bound execution times*) | Presupuesto restante propagado en `X-Deadline-Ms` y cancelación temprana aguas abajo | D20 |
| Rendimiento | Gestionar tasa de llegada (*throttling* / cubeta de fichas) | Limitador por usuario/IP en `api-gateway` y limitador saliente al 80 % de cuota por proveedor | D20, D24 |
| Rendimiento | Priorizar eventos (*priority scheduling*) | Tres carriles en el *broker* (`P1` viajes activos/disrupciones, `P2` estándar, `P3` diferible) | D20 |
| Rendimiento | Acotar tamaños de cola (*bound queue sizes*) | Colas en vuelo acotadas en HTTP para fallar rápido en vez de saturar memoria | D20 |
| Escalabilidad | Replicación horizontal + modelo predictivo y reactivo | Precalentamiento por calendario de picos + autoescalado por métricas adelantadas y reserva tibia del 15 % | D21 |
| Escalabilidad | Separar caminos de lectura y escritura | Unidades de despliegue independientes `itinerary-lectura` e `itinerary-escritura` | D21 |
| Escalabilidad | Particionamiento de datos (*sharding*) y archivo por niveles | 64 *buckets* por `hash(usuario_id)`, división en línea, compactación y almacenamiento frío | D23 |
| Observabilidad / Testabilidad | Correlación distribuida y monitoreo semántico | `correlation_id` HTTP + AsyncAPI, muestreo de cola en trazas y especificaciones verificables de pruebas de carga | D25 |
