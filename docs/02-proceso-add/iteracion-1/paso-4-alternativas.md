# Iteración 1 · Paso 4 — Conceptos de diseño y alternativas

Este es el paso donde ADD exige **considerar alternativas antes de elegir**. Para cada una de las
siete decisiones estructurales se listan los conceptos de diseño evaluados, qué driver favorece a
cada uno, y por qué se descartaron los no elegidos. La elección queda formalizada en el ADR
correspondiente; acá está el razonamiento comparativo que el ADR resume.

Criterio de evaluación usado en todas las tablas: ✅ favorece el driver · ⚠️ lo permite con costo ·
❌ lo compromete.

---

## D1 — Estilo arquitectónico del *backend*

**Problema:** el sistema tiene tres perfiles de carga radicalmente distintos (ingesta en ráfagas,
lectura sensible a milisegundos, analítica pesada) y debe tolerar la pérdida de una región con 5
minutos de presupuesto mensual.

| Alternativa | QA-04 (ráfaga) | QA-05 (región) | QA-09 (aislar analítica) | QA-10/15 (extensión) | CRN-02 / CON-09 (equipo de 4) | CRN-08 (costo) |
|---|---|---|---|---|---|---|
| **A1. Monolito modular en capas** | ❌ escala como un bloque: para absorber la ráfaga de ingesta hay que replicar también el plano de lectura | ⚠️ posible, pero el despliegue es todo-o-nada | ❌ comparte proceso y almacén con la operación | ⚠️ los módulos aíslan, pero el despliegue acoplado frena | ✅ lo más simple de construir y documentar | ✅ el más barato |
| **A2. SOA con un bus de integración central** | ⚠️ el bus absorbe la ráfaga pero se vuelve el cuello de botella | ⚠️ el bus es un punto único por región | ⚠️ | ✅ la mediación en el bus facilita agregar proveedores | ⚠️ exige operar y versionar el bus | ⚠️ |
| **A3. Microservicios orientados a eventos, con granularidad acotada** ⬅ **elegido** | ✅ la ingesta escala por separado del plano de lectura; el *broker* desacopla la ráfaga | ✅ cada servicio se replica por región de forma independiente | ✅ el flujo de eventos alimenta un plano separado sin tocar la operación | ✅ los adaptadores se agregan como elementos nuevos | ⚠️ 13 elementos es el techo de lo sostenible, de ahí CON-A4 | ⚠️ más caro que el monolito, aceptado |
| **A4. Serverless (funciones) puro** | ✅ escalado elástico inmediato | ✅ | ✅ | ✅ | ⚠️ barato de empezar, difícil de razonar al crecer | ✅ paga por uso |

### Por qué A3

A1 queda descartado por el **perfil de carga asimétrico**: absorber el pico de ingesta de QA-04
obligaría a replicar el plano de lectura al mismo tiempo, pagando capacidad que no se necesita, y
el aislamiento de QA-09 sería imposible dentro del mismo proceso.

A4 queda descartado principalmente por el **presupuesto de latencia de QA-02**: el arranque en
frío de las funciones es incompatible con 800 ms en el p95 cuando el camino de lectura atraviesa
varias de ellas, y el control fino que exige la replicación activo-activo de QA-05 es más difícil
de obtener. Sí se adopta de forma **acotada** para cargas episódicas: el sondeo de reconciliación
de ADR-0004 y los trabajos de archivado de RF-08.

A2 queda descartado porque concentra en el bus la lógica de mediación que D6 prefiere tener en
adaptadores sustituibles, y porque el bus se vuelve un elemento crítico más que replicar en tres
regiones.

**La granularidad importa tanto como el estilo.** Microservicios con 40 servicios satisfaría los
mismos atributos de calidad y haría el trabajo inviable para cuatro personas con dedicación
parcial (CON-09). De ahí CON-A4: menos de 15 elementos, y los límites se trazan por **perfil de
carga y por frontera de confianza**, no por entidad del dominio.

→ [ADR-0001](../../03-adr/ADR-0001-estilo-arquitectonico.md)

---

## D2 — Topología de despliegue

**Problema:** 5 minutos de inactividad al mes (99,9884 %) con un presupuesto de 1,5 minutos
asignado a la pérdida de una región (QA-05), y operación en tres franjas horarias (QA-18).

| Alternativa | QA-05 (pérdida de región) | QA-02/03 (latencia) | QA-18 (multirregión) | CRN-08 (costo) | CRN-13 (consistencia) |
|---|---|---|---|---|---|
| **B1. Región única, múltiples zonas de disponibilidad** | ❌ una región caída es una caída total; el presupuesto mensual se agota en el primer incidente | ❌ los usuarios de las otras dos franjas pagan la latencia transoceánica | ❌ | ✅ el más barato | ✅ trivial |
| **B2. Activo-pasivo multirregión** | ⚠️ el *failover* tiene un tiempo de recuperación que consume el presupuesto entero, y hay que ejercitarlo para confiar en él | ❌ la región pasiva no sirve tráfico: la latencia no mejora | ⚠️ | ⚠️ se paga capacidad ociosa | ✅ replicación en un sentido |
| **B3. Activo-activo en tres regiones** ⬅ **elegido** | ✅ la pérdida de una región redistribuye el tráfico sin conmutación: 60 s de redirección contra 1,5 min de presupuesto | ✅ acerca el borde al usuario, que es lo que financia el presupuesto de 120 ms de red | ✅ habilita residencia de datos por región (CRN-15) | ❌ tres veces la capacidad, más el tráfico de replicación | ❌ exige resolver escritura concurrente entre regiones |
| **B4. Activo-activo en más de tres regiones** | ✅ | ✅ | ✅ | ❌ costo creciente sin ganancia proporcional | ❌ el problema de consistencia empeora |

### Por qué B3

B1 es incompatible con QA-05 por definición. B2 es la tentación razonable y se descarta por
aritmética: un tiempo de recuperación realista de un *failover* entre regiones —detección,
promoción del almacén, redirección, recalentamiento de cachés— está en el orden de varios minutos,
y el presupuesto mensual completo es de cinco. Un solo incidente al año lo agotaría.

B4 se descarta por CRN-08: tres regiones son el mínimo que cubre las tres franjas horarias y
sobrevive a la pérdida de una conservando mayoría para el consenso; más regiones agregan costo y
agravan el problema de consistencia sin mejorar el driver.

**Lo que esta decisión compra y lo que cuesta.** Compra QA-05 y buena parte del presupuesto de
latencia de QA-02. Cuesta el triple de infraestructura y, sobre todo, **traslada el problema a la
consistencia de datos entre regiones** (CRN-13), que queda explícitamente diferido a la
iteración 3 y es el principal riesgo residual de esta iteración.

→ [ADR-0002](../../03-adr/ADR-0002-despliegue-multirregion.md)

---

## D3 — Organización de los datos

**Problema:** QA-09 exige que una consulta analítica sobre 3 años de historia no degrade el p95
operacional más de un 5 %, estando el plano operacional en carga pico.

| Alternativa | QA-09 (aislamiento) | QA-02 (latencia de lectura) | RF-14 (consultas pesadas) | CRN-08 (costo) | Complejidad |
|---|---|---|---|---|---|
| **C1. Un solo almacén, con réplicas de lectura para la analítica** | ❌ las réplicas comparten el flujo de replicación y el esquema normalizado: una consulta de 3 años las satura | ⚠️ | ❌ un esquema normalizado es malo para agregaciones masivas | ✅ | ✅ |
| **C2. CQRS: vistas materializadas de lectura sobre el mismo almacén** | ⚠️ mejora la lectura operacional, no resuelve la analítica | ✅ | ❌ | ✅ | ⚠️ |
| **C3. Plano analítico separado, alimentado por el flujo de eventos de dominio** ⬅ **elegido** | ✅ aislamiento físico: la consulta no toca la base operacional | ✅ | ✅ almacén columnar, apto para agregaciones | ❌ segundo almacén y segunda canalización | ❌ hay que gestionar la frescura y la duplicación del dato |
| **C4. Plano analítico separado, alimentado por volcados nocturnos** | ✅ | ✅ | ✅ | ⚠️ | ✅ más simple que C3 |

### Por qué C3 (más C2 dentro del plano operacional)

C1 y C2 no resuelven el driver: el problema no es el esquema de lectura, es que una consulta
analítica y una consulta operacional **compiten por los mismos recursos**. Solo la separación
física lo resuelve.

Entre C3 y C4 la diferencia es la frescura. C4 es más simple pero da una frescura de 24 horas, y
AMB-07 fijó el objetivo en **≤ 1 hora**. Además el flujo de eventos de dominio ya existe por D1:
alimentar el plano analítico desde ahí no agrega un mecanismo nuevo, solo un consumidor más.

C2 se adopta igualmente, pero **dentro** del plano operacional: el camino de lectura del panel usa
una proyección optimizada, que es lo que hace cerrar el presupuesto de 80 ms de acceso a datos de
QA-02.

→ [ADR-0003](../../03-adr/ADR-0003-separacion-planos.md)

---

## D4 — Obtención del correo del usuario

**Problema:** el enunciado dice «sondear», y el refinado demostró que sondear 9 millones de
buzones cada 5 minutos son **30.000 sondeos por segundo** sostenidos
([cálculo](../../01-analisis-inicial/07-supuestos-y-carga-derivada.md#por-qué-el-sondeo-uniforme-es-inviable)).

| Alternativa | QA-01 (≤ 5 min) | CRN-09 (cuotas de terceros) | CRN-08 (costo) | Cobertura de proveedores | QA-04 (ráfaga) |
|---|---|---|---|---|---|
| **E1. Sondeo uniforme cada 5 min** | ✅ en teoría | ❌ 30.000 sondeos/s excede las cuotas publicadas en órdenes de magnitud | ❌ prohibitivo; el 99,99 % de los sondeos no devuelve nada | ✅ funciona con cualquier proveedor | ❌ la carga es constante al máximo: no queda margen |
| **E2. Sondeo con intervalo adaptativo por actividad del buzón** | ⚠️ los buzones poco activos quedan fuera del objetivo | ⚠️ reduce la carga, no la elimina | ⚠️ | ✅ | ⚠️ |
| **E3. Notificación por *push* del proveedor** | ✅ la notificación llega en segundos | ✅ ~45 eventos/s de promedio | ✅ | ❌ no existe en IMAP genérico (E-06), y las notificaciones se pueden perder | ✅ la carga sigue a la actividad real |
| **E4. *Push* + sondeo de reconciliación escalonado** ⬅ **elegido** | ✅ el camino normal es el *push*; la reconciliación es red de seguridad | ✅ | ✅ | ✅ cubre IMAP y las notificaciones perdidas | ✅ |

### Por qué E4

E1 es la lectura literal del enunciado y es **inviable**, lo que convierte a esta decisión en una
reinterpretación documentada del requisito (ver
[AMB-03](../../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)):
se interpreta «sondear» como *obtener de forma continua*, y el mecanismo pasa a ser una decisión
de diseño.

E3 solo tampoco alcanza: IMAP genérico no ofrece notificaciones comparables, y ningún mecanismo de
*push* garantiza la entrega. De ahí E4: el *push* es el camino que cumple el presupuesto de
frescura, y el sondeo de reconciliación —escalonado, de baja frecuencia, con intervalo según la
actividad del buzón— cubre los buzones sin *push* y recupera lo que se haya perdido.

La reconciliación es una carga episódica y tolerante a latencia, así que es exactamente el caso
donde conviene la adopción acotada de funciones mencionada en D1.

→ [ADR-0004](../../03-adr/ADR-0004-obtencion-de-correo.md)

---

## D5 — Capa de clientes

**Problema:** dos clientes con presupuestos de rendimiento distintos (QA-02: 800 ms en web;
QA-03: 1,4 s de primer contenido en móvil sobre 4G) y necesidades distintas (QA-17: GPS).

| Alternativa | QA-02 (web) | QA-03 (FCP móvil) | QA-17 (GPS) | CON-09 (equipo de 4) | Evolución independiente |
|---|---|---|---|---|---|
| **F1. Una sola API genérica para los dos clientes** | ⚠️ obliga al cliente a varias idas y vueltas, o a recibir datos que no usa | ❌ el *payload* pensado para web arruina el presupuesto de 1,4 s en 4G | ✅ | ✅ una sola API que mantener | ❌ cada cambio afecta a los dos clientes |
| **F2. Un BFF por tipo de cliente** ⬅ **elegido** | ✅ una ida y vuelta, respuesta compuesta a medida | ✅ *payload* reducido y carga diferida de los detalles | ✅ | ⚠️ dos BFF que mantener | ✅ cada cliente evoluciona a su ritmo |
| **F3. Un BFF más GraphQL** | ✅ | ✅ el cliente pide exactamente lo que necesita | ✅ | ❌ costo de aprendizaje y de control de consultas costosas | ✅ |
| **F4. PWA única para web y móvil** | ✅ | ⚠️ difícil llegar a 1,4 s con arranque en frío | ❌ acceso a GPS y a notificaciones más limitado y dependiente de la plataforma | ✅ un solo cliente | ⚠️ |

### Por qué F2

F1 se descarta por el **conflicto directo entre QA-02 y QA-03**: la respuesta que hace eficiente a
la web es demasiado grande para el presupuesto móvil, y la que sirve al móvil obliga a la web a
varias peticiones. Un contrato único serviría mal a los dos.

F4 se descarta por QA-17 y QA-03: el enunciado pide explícitamente «una interfaz rica aprovechando
capacidades nativas como GPS en móviles», y es más difícil sostener el presupuesto de primer
contenido con un arranque en frío de aplicación web.

F3 se descarta por CON-09: GraphQL resolvería elegantemente el problema, pero el control de
consultas costosas y el cacheo son trabajo adicional que un equipo de cuatro personas con
dedicación parcial no puede sostener en paralelo con todo lo demás. Queda registrado como
alternativa a reconsiderar si los dos BFF empiezan a divergir demasiado.

**Sobre la aplicación móvil:** se adopta un marco multiplataforma con módulos nativos para GPS y
notificaciones, en lugar de dos aplicaciones nativas. Es una concesión a CON-09, y el ADR la marca
como revisable si el presupuesto de QA-03 no cierra en las pruebas.

→ [ADR-0005](../../03-adr/ADR-0005-capa-de-clientes-bff.md)

---

## D6 — Integración con sistemas externos

**Problema:** 12 de 16 interfaces son con terceros heterogéneos (ASR-4 / QA-11), hay que poder
agregar un proveedor sin tocar nada existente (QA-10) y un medio de transporte nuevo tocando a lo
sumo dos elementos (QA-15).

| Alternativa | QA-10 (proveedor nuevo) | QA-11 (formato desconocido) | QA-15 (transporte nuevo) | QA-06 (aislar falla de tercero) | Complejidad |
|---|---|---|---|---|---|
| **G1. Llamadas directas desde los servicios de dominio** | ❌ cada proveedor nuevo modifica el dominio | ❌ los conceptos del proveedor se filtran al modelo canónico | ❌ | ❌ la falla del tercero se propaga al dominio | ✅ |
| **G2. Capa de anticorrupción con un adaptador por proveedor** ⬅ **elegido** | ✅ se agrega un adaptador, no se modifica nada | ✅ la heterogeneidad queda contenida en el adaptador | ✅ junto con el registro de tipos de segmento | ✅ el cortacircuitos vive en el adaptador | ⚠️ una capa más |
| **G3. Plataforma de integración de terceros (iPaaS)** | ✅ | ⚠️ la lógica de extracción queda fuera del repositorio | ⚠️ | ⚠️ | ⚠️ dependencia de un proveedor más, y CON-04 se complica |
| **G4. Capa de anticorrupción con adaptadores cargados como complementos** ⬅ **elegido junto con G2** | ✅ el adaptador se registra por configuración, sin desplegar los demás | ✅ | ✅ | ✅ | ⚠️ exige definir y versionar el contrato del complemento |

### Por qué G2 + G4

G1 es lo que ocurre si no se decide nada, y es exactamente lo que QA-10, QA-11 y QA-15 prohíben:
cada proveedor nuevo sería una modificación del dominio.

G3 se descarta por CON-04: con *spec-driven development* como restricción de proceso, la lógica de
traducción tiene que vivir en el repositorio, versionada y verificable por pruebas de contrato. Una
plataforma externa la saca de ahí.

Sobre G2 se adopta además **G4**: los adaptadores implementan un contrato canónico y se registran
por configuración, de modo que agregar uno no obliga a redesplegar los existentes. Esto es lo que
hace que la medida de respuesta de QA-10 —«cantidad de elementos existentes modificados = 0»— sea
literalmente cierta y no una aproximación.

El mismo patrón se aplica dos veces: a los proveedores de viaje en `provider-sync`, y a los
formatos de correo en `booking-extraction`, donde cada extractor es un complemento con su puntaje
de confianza. Es lo que permite que QA-11 cumpla «0 % de extracción incorrecta silenciosa»: si
ningún extractor reconoce el formato con confianza suficiente, el sistema no inventa.

→ [ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md)

---

## D7 — Identidad, autorización y compartición

**Problema:** tres cosas distintas que suelen confundirse en una: autenticar al usuario, custodiar
el acceso delegado a su correo (ASR-5 / QA-13, CON-08) y autorizar a terceros designados a ver un
itinerario (QA-12), sin olvidar que publicar en redes sociales es un cuarto mecanismo (AMB-10).

| Alternativa | CON-08 (autorización explícita) | QA-13 (custodia de tokens) | QA-12 (solo designados) | CON-09 | CRN-05 |
|---|---|---|---|---|---|
| **H1. Credenciales de correo guardadas por el sistema** | ❌ pedirle la contraseña del correo al usuario viola CON-08 | ❌ el peor caso posible de custodia | — | ✅ | ❌ |
| **H2. OIDC para el usuario + OAuth 2.0 delegado para el correo, con tokens en una bóveda de secretos** ⬅ **elegido** | ✅ el consentimiento lo otorga el proveedor de correo, es revocable y de alcance acotado | ✅ un único servicio puede descifrar; el resto recibe tokens de uso acotado | — | ✅ se delega la identidad a un proveedor gestionado | ✅ |
| **H3. Enlaces de capacidad (quien tiene el enlace, ve)** | — | — | ❌ «solo personas designadas» se incumple en cuanto el enlace se reenvía | ✅ el más simple | — |
| **H4. Lista de designados verificada contra la identidad autenticada** ⬅ **elegido para compartir** | — | — | ✅ el enlace no alcanza: hay que ser la persona designada | ⚠️ obliga al designado a autenticarse | — |

### Por qué H2 + H4

H1 queda descartado por CON-08, que es una restricción y no se negocia.

Sobre la compartición, H3 es la solución habitual y **no cumple el driver**. QA-12 exige el 100 %
de accesos de no designados denegados, y un enlace reenviado o filtrado otorga acceso a quien no
estaba designado. La medida de respuesta del escenario es justamente lo que hace visible que la
solución fácil no sirve. De ahí H4: el enlace identifica el recurso, pero el acceso se decide
contra la **identidad autenticada** del visitante y su pertenencia a la lista. El costo es
fricción para el designado, y se acepta.

**La consecuencia estructural de QA-13** es que `identity-access` es el **único** elemento del
sistema con capacidad de descifrar un token de correo. `mail-ingest`, que es quien necesita leer
los buzones, recibe tokens de uso acotado y de vida corta, y no tiene acceso a la bóveda. Así, un
`mail-ingest` comprometido no permite la extracción masiva que describe el escenario.

**Y AMB-10 se resuelve estructuralmente:** `sharing` ofrece dos interfaces separadas —
`comparticiones` (designados, dato completo, control de acceso) y `publicaciones` (redes sociales,
resumen sin datos sensibles, confirmación explícita del usuario). Son dos modelos de confianza
distintos, así que son dos operaciones distintas, no una con un parámetro.

→ [ADR-0007](../../03-adr/ADR-0007-identidad-y-comparticion.md)

---

## Tácticas de atributos de calidad aplicadas en esta iteración

Las decisiones anteriores instancian conceptos de diseño; estos a su vez aplican tácticas. Esta
tabla las deja explícitas, porque el enunciado evalúa «la correcta utilización de patrones y
tácticas de diseño» (§5).

| Atributo | Táctica | Dónde se aplica | Decisión |
|---|---|---|---|
| Disponibilidad | Redundancia activa | Tres regiones sirviendo tráfico simultáneamente | D2 |
| Disponibilidad | Detección por latido / monitoreo | Comprobación de salud regional en el borde | D2 |
| Disponibilidad | Cortacircuitos | Un cortacircuitos por adaptador de proveedor | D6 |
| Disponibilidad | Mamparo (*bulkhead*) | Grupos de recursos separados por adaptador | D6 |
| Disponibilidad | Degradación gradual | Prioridad de panel y notificaciones sobre analítica y publicación en redes | D1, D3 |
| Rendimiento | Introducir concurrencia | Consumo de eventos en paralelo por partición de usuario | D1 |
| Rendimiento | Mantener múltiples copias de datos | Proyección de lectura del panel (CQRS) | D3 |
| Rendimiento | Acercar los recursos | Borde y despliegue regional cerca del usuario | D2 |
| Rendimiento | Gestionar la tasa de eventos | *Broker* absorbiendo la ráfaga de ingesta | D1, D4 |
| Escalabilidad | Replicación horizontal sin estado | Servicios sin estado de sesión | D1 |
| Escalabilidad | Particionamiento de datos por usuario | Clave de partición = usuario | D1, D3 |
| Interoperabilidad | Adaptar interfaces (anticorrupción) | Un adaptador por proveedor y por formato de correo | D6 |
| Interoperabilidad | Descubrir y registrar servicios | Registro de adaptadores por configuración | D6 |
| Modificabilidad | Encapsular | Contrato canónico de adaptador | D6 |
| Modificabilidad | Restringir dependencias | Dependencias permitidas declaradas en la vista de módulos | D1 |
| Modificabilidad | Diferir el enlace | Adaptadores y extractores cargados como complementos | D6 |
| Seguridad | Autenticar actores | OIDC para el usuario y para el designado | D7 |
| Seguridad | Autorizar actores | Evaluación de autorización centralizada en `identity-access` | D7 |
| Seguridad | Limitar el acceso | Solo `identity-access` descifra tokens; tokens de uso acotado al resto | D7 |
| Seguridad | Mantener la confidencialidad | Cifrado en reposo de los tokens en bóveda | D7 |
| Seguridad | Auditar | Registro de todo acceso al almacén de secretos | D7 |
| Testabilidad | Especializar las interfaces de acceso | Contratos OpenAPI/AsyncAPI verificables por pruebas de contrato | D9 |
