# Iteración 2 · Paso 4 — Conceptos de diseño y alternativas

Este es el paso donde ADD exige **considerar alternativas antes de elegir**. Para cada una de las
siete decisiones estructurales de la iteración (más una de proceso) se listan los conceptos de
diseño evaluados, qué driver favorece a cada uno y por qué se descartaron los no elegidos. La
elección queda formalizada en el ADR correspondiente; acá está el razonamiento comparativo que el
ADR resume.

Criterio de evaluación usado en todas las tablas: ✅ favorece el driver · ⚠️ lo permite con costo ·
❌ lo compromete · — no aplica.

**Dos advertencias de lectura.** A diferencia de la iteración 1, las decisiones de esta iteración
están **acopladas**: D10, D11 y D12 definen juntas el modelo canónico y se evaluaron en conjunto;
D13 y D14 comparten el mecanismo de observaciones. Cada ADR declara sus dependencias. Y la
numeración continúa la de la iteración 1: **el número de la decisión coincide con el del ADR**
(D10 → ADR-0010).

---

## D10 — Modelo del dominio y sus límites

**Problema:** tres fuentes escriben sobre las mismas reservas, en concurrencia y con ritmos
distintos (el correo, el proveedor y el usuario), y el sistema promete ser el «único punto de
verdad» (MN-1). Antes de decidir cómo se persiste o cómo se fusiona hay que decidir **qué es una
unidad de consistencia**.

| Alternativa | CRN-11 (fusión de fuentes) | CRN-12 (idempotencia) | QA-04 (contención en el pico) | QA-15 (extensibilidad) | R-1 (consistencia entre regiones) | CON-09 (equipo de 4) |
|---|---|---|---|---|---|---|
| **J1. Modelo rico con un único agregado `Viaje`** que contiene reservas y segmentos | ⚠️ la fusión ocurre dentro del viaje, pero una reserva puede cambiar de viaje y su identidad no depende de él | ⚠️ | ❌ cada actualización de un proveedor serializa contra todo el viaje | ✅ | ❌ una unidad de escritura grande multiplica la probabilidad de conflicto entre regiones | ⚠️ |
| **J2. Modelo anémico con servicios** (entidades de datos y *transaction scripts*) | ❌ las reglas de fusión quedan repartidas entre servicios | ❌ cada servicio resolvería la duplicación a su manera | ⚠️ | ⚠️ | ❌ no hay una unidad de consistencia que replicar o fusionar | ✅ lo más simple de escribir |
| **J3. Agregados con límites transaccionales explícitos: `Reserva` y `Viaje`** ⬅ **elegido** | ✅ la fusión es una operación de una sola raíz, con invariantes verificables | ✅ la idempotencia se resuelve en la frontera del agregado | ✅ cada actualización toca una reserva, no un viaje | ✅ el segmento vive dentro de la reserva y su variabilidad se declara en un registro (D11) | ✅ unidades pequeñas, colocalizadas por usuario, con una fusión determinista | ⚠️ exige disciplina de diseño |

### Por qué J3

J1 es la elección intuitiva —«un viaje tiene reservas, que tienen segmentos»— y se descarta por
**contención**: un proveedor que notifica el cambio de puerta de un vuelo no debería competir con
el usuario que mueve un hotel a otro viaje. Además mezcla dos preguntas distintas: *¿qué es esta
reserva y qué valores tiene?* (identidad y fusión) y *¿a qué viaje pertenece?* (agrupación). La
primera no depende del viaje; la segunda sí cambia con el tiempo.

J2 es la alternativa que mejor se ajusta a CON-09 y se descarta por **dispersión de invariantes**:
la deduplicación, la precedencia entre fuentes y la idempotencia son las reglas más delicadas del
sistema, y distribuirlas entre servicios es la receta para que dos caminos de código las apliquen
distinto. El plan de la iteración lo marca como el escenario de retrabajo más caro del proyecto.

**Los límites quedan así** (el detalle está en el [README](README.md#52-el-modelo-canónico)):

| Agregado | Raíz | Contiene | Invariantes principales |
|---|---|---|---|
| `Reserva` | `Reserva` | `Observación` (solo se agrega), `Segmento`, `Conflicto` | Al menos un segmento. Los identificadores son únicos por usuario. **La vista consolidada es una función determinista de las observaciones y de los campos fijados** |
| `Viaje` | `Viaje` | La **membresía** (referencias a reservas por id) | Una reserva pertenece a lo sumo a un viaje activo. Una asignación fijada por el usuario no la mueve ningún proceso automático |

La última invariante de `Reserva` es la que importa: si la consolidación es determinista, aplicar
las mismas observaciones en cualquier orden de llegada da el mismo resultado, lo que simplifica
CRN-12 (D14) y **deja abiertos los dos caminos de R-1** (partición por usuario y tipos
convergentes) sin comprometerse con ninguno.

**Lo que esta decisión compra y lo que cuesta.** Compra una unidad de consistencia pequeña donde
las reglas críticas tienen un solo hogar. Cuesta **consistencia eventual entre `Reserva` y
`Viaje`**: cuando llega una reserva, el viaje se actualiza después, por evento. Y complica la
lectura inmediata tras una escritura (el usuario agrega una reserva y quiere verla ya en su
viaje), que se resuelve devolviendo el estado resultante en la respuesta del comando; el detalle
de la caché va a la iteración 3.

→ [ADR-0010](../../03-adr/ADR-0010-modelo-canonico-reserva-segmento-viaje.md)

---

## D11 — Extensibilidad del tipo de segmento

**Problema:** QA-15 exige agregar un medio de transporte nuevo (tren, autobús) tocando a lo sumo
dos elementos. Los cinco tipos comparten casi todo (un inicio y un fin, en tiempo y lugar, con un
operador) y difieren en detalles (coche y asiento de un tren, categoría de un auto).

| Alternativa | QA-15 (¿qué se toca para agregar «tren»?) | QA-02 (lectura) | QA-10 / QA-11 (adaptadores y extractores) | RF-14 (analítica) | CON-09 |
|---|---|---|---|---|---|
| **K1. Herencia de tablas** (tabla base + una por tipo) | ❌ tabla nueva, migración y mapeo en cada elemento que lee o escribe segmentos | ⚠️ *joins* por tipo | ⚠️ cada adaptador debe conocer las tablas | ⚠️ | ⚠️ |
| **K2. Tabla única con atributos por tipo** (columnas dispersas) | ⚠️ columnas nuevas y migración; nada impide mezclar campos de tipos distintos | ✅ | ❌ no hay contrato de qué debe traer un segmento de cada tipo | ⚠️ | ✅ |
| **K3. Registro de tipos con esquema declarado** ⬅ **elegido** | ✅ un descriptor nuevo y, a lo sumo, un complemento por canal de datos | ✅ el núcleo va en columnas; el detalle se lee como bloque | ✅ el adaptador valida su salida contra el esquema del tipo | ✅ `dim_tipo_segmento` se alimenta del registro (D16) | ⚠️ hay que construir el registro y su validación |

### Por qué K3

K1 es la respuesta de manual de orientación a objetos y **incumple QA-15 literalmente**: agregar un
tipo obliga a tocar el esquema de datos y a todo elemento que lea segmentos.

K2 funciona hasta el tercer tipo, y falla de forma **silenciosa**: sin un esquema declarado por
tipo, nada define qué debe traer un segmento de tren, de modo que la salida de un extractor mal
hecho se acepta sin objeción. Eso debilita QA-11 justo donde R-2 ya es el riesgo más frágil.

K3 separa el segmento en dos partes: un **núcleo común** (tipo, inicio, fin, operador, referencia,
estado) en columnas propias, y un **detalle** por tipo validado contra el esquema que declara su
descriptor. El descriptor además declara qué campos son relevantes para notificar, cómo se
presenta el segmento y qué atributos pasan a la analítica, de modo que ni `notification`, ni los
BFF, ni el plano analítico necesitan código nuevo por cada tipo.

**La regla del núcleo.** Todo lo que se filtre, ordene, agrupe o deduplique pertenece al núcleo;
el detalle es para presentar y notificar. Esa regla es el costo de K3 (el detalle no se indexa) y
también lo que mantiene el rendimiento de QA-02.

**Un rol por tipo.** El descriptor declara el `rolEnViaje` (traslado, alojamiento o movilidad
local). La agrupación de reservas en viajes (RF-07) razona por rol y lugar, nunca por tipo, y por
eso una regla de agrupación no necesita conocer el tren.

→ [ADR-0011](../../03-adr/ADR-0011-extensibilidad-del-tipo-de-segmento.md)

---

## D12 — Persistencia del modelo canónico

**Problema:** el modelo de D10 y D11 necesita almacenarse con garantías transaccionales fuertes en
tres puntos (unicidad de identificadores, bandeja de entrada de eventos, publicación de eventos
junto con el cambio) y con una variabilidad por tipo que no obligue a migrar. Debe además
respetar el presupuesto de 80 ms de acceso a datos de QA-02 y no cerrar el camino de R-1.

| Alternativa | QA-15 (tipo nuevo sin migración) | QA-02 (80 ms) | CRN-11 / CRN-12 (unicidad, *inbox*, *outbox*) | R-1 (partición por usuario) | QA-08 (crecimiento) | CON-09 |
|---|---|---|---|---|---|---|
| **L1. Relacional normalizado** (esquema por tipo) | ❌ cada tipo, una migración | ✅ | ✅ nativo | ✅ | ✅ | ✅ lo más conocido |
| **L2. Documental** (un documento por agregado) | ✅ | ✅ un acceso por agregado | ⚠️ unicidad entre documentos y publicación transaccional dependen del producto | ✅ | ✅ | ⚠️ menos práctica en el equipo |
| **L3. Relacional con campos semiestructurados para el detalle por tipo** ⬅ **elegido** | ✅ el detalle es un campo JSON validado por el registro | ✅ núcleo indexado; el detalle se lee como bloque | ✅ nativo | ✅ clave de partición = usuario | ✅ con compactación de observaciones | ✅ |

### Por qué L3

L3 toma del modelo relacional lo que D13 y D14 necesitan **sin negociar**: restricciones de
unicidad (los identificadores de una reserva por usuario, la clave de idempotencia de un evento) y
la escritura atómica del cambio junto con el evento a publicar (*outbox*). Y toma del documental
la flexibilidad **solo donde hace falta**: el detalle por tipo.

L1 se descarta por QA-15 (acopla el esquema físico a la lista de tipos, que es justo lo que K3
evita). L2 se descarta con menos firmeza: la flexibilidad es la misma que la de L3, pero las dos
garantías de las que dependen la deduplicación y la idempotencia pasan a depender del producto
elegido y de transacciones entre documentos, y el equipo tiene menos práctica con ese modelo.
Queda como alternativa a reconsiderar si el detalle crece hasta dominar el modelo.

**Toda tabla del plano operacional lleva `usuario_id` como clave de partición.** Es lo que hace
que los agregados de un mismo usuario vivan juntos, y es compatible con las dos salidas posibles
de R-1.

**Control del crecimiento (QA-08).** Las observaciones se agregan y no se modifican, lo que las
hace crecer sin cota. Se compactan: se conservan las más recientes por fuente y las que dieron
origen a un conflicto abierto, y el resto se resume en el plano analítico por los eventos ya
emitidos. Es la parte de QA-08 que esta iteración sí cubre.

**Lo que esta decisión deja explícitamente abierto.** El producto concreto y la topología de
replicación entre regiones. Elegirlos hoy sería decidir R-1 sin haberlo analizado, y queda en la
iteración 3 (CRN-13).

→ [ADR-0012](../../03-adr/ADR-0012-persistencia-del-plano-operacional.md)

---

## D13 — Deduplicación y resolución de conflictos entre fuentes (CRN-11)

**Problema:** la misma reserva real puede llegar por el correo de la aerolínea, por el correo de la
agencia en línea, por el intercambio del proveedor y por la carga manual del usuario, con
códigos distintos, formatos distintos y, a veces, valores distintos. Son **dos problemas
diferentes** que las alternativas de abajo resuelven por separado: *¿es la misma reserva?*
(identidad) y *¿qué valor gana cuando no coinciden?* (conflicto).

| Alternativa | Identidad | Valores en conflicto | QA-11 (no inventar) | RF-06 (gestión manual) | Fricción para el usuario |
|---|---|---|---|---|---|
| **M1. Clave natural por código de confirmación** | ✅ exacta cuando hay código · ❌ falla si no hay código o hay varios | — | ✅ no fusiona de más | ⚠️ las cargas manuales suelen no tener código | ✅ ninguna |
| **M2. Coincidencia difusa por atributos** (fechas, lugares, operador) | ⚠️ cubre el caso sin código, con falsos positivos | — | ❌ una fusión errónea es una extracción incorrecta silenciosa | ✅ | ✅ pero los errores son caros |
| **M3. Precedencia por fuente, con intervención del usuario** | — | ✅ determinista y explicable | ✅ | ✅ la edición del usuario es una fuente más | ⚠️ pregunta cuando las fuentes discrepan |
| **M1 + M3, con M2 solo como sugerencia** ⬅ **elegido** | ✅ | ✅ | ✅ | ✅ | ⚠️ acotada a los campos que el usuario fijó |

### Por qué M1 + M3 (y M2 como sugerencia)

M2 queda descartada **como mecanismo de fusión** por QA-11: dos habitaciones del mismo hotel para
la misma noche, un viaje de ida y vuelta por la misma ruta, o dos pasajes de tren iguales para
personas distintas son reservas distintas que un criterio difuso fusionaría sin avisar. Una
fusión errónea es un dato incorrecto que el usuario no sabe que lo es, que es exactamente lo que
el sistema promete no hacer. Se conserva como **sugerencia**: cuando no hay código, el sistema
propone «¿es la misma reserva?» y el usuario decide.

M1 se adopta con una corrección: una reserva no tiene *un* código sino un **conjunto de
identificadores**. Un vuelo comprado a través de una agencia en línea tiene el localizador de la
aerolínea y el número de orden de la agencia, y cada correo trae uno, otro o ambos. Si una
observación coincide con **cualquiera** de los identificadores conocidos, es la misma reserva. Si
una observación liga dos reservas que el sistema creía distintas, se unifican (la más antigua
conserva el id), salvo que alguna sea manual, caso en el que se pide confirmación.

M3 resuelve la segunda mitad, con reglas explícitas:

| Situación | Regla |
|---|---|
| Dos versiones de la misma fuente | Gana la de mayor versión de la **fuente** (fecha de emisión), no la que llegó último |
| Proveedor frente a correo | El proveedor gana en los hechos operativos (horarios, estado, puertas, cancelación). El correo completa los campos que el proveedor no informa |
| Reserva solo manual | El usuario es la autoridad |
| Edición manual frente a una fuente automática | La edición **fija** el campo. Si una fuente trae después un valor **distinto y nuevo**, se abre un conflicto: el panel muestra el valor fijado con un aviso y el usuario elige |
| Cancelación del proveedor | Prevalece siempre: el estado pasa a `Cancelada` y se notifica. El usuario puede reactivarla manualmente, lo que fija el estado |
| Sin identificador coincidente | El sistema **nunca** fusiona por su cuenta: crea la reserva y, si hay candidatas, sugiere |

**Lo que esta decisión cuesta.** Intervención del usuario cuando las fuentes discrepan sobre un
campo que él fijó. La hipótesis es que son pocos casos, pero es una hipótesis: el prototipo debe
medir cuántos conflictos se abren por usuario y por semana. Si fueran muchos, la regla de fijado
sería lo primero a revisar.

→ [ADR-0013](../../03-adr/ADR-0013-deduplicacion-y-conflictos.md)

---

## D14 — Idempotencia de la ingesta (CRN-12)

**Problema:** el *broker* de D1 entrega al menos una vez, el *push* y la reconciliación de D4 se
solapan por diseño, los proveedores reintentan sus notificaciones y el usuario puede tocar dos
veces un botón. El mismo mensaje puede llegar dos veces, y la misma reserva puede describirse en
dos mensajes distintos.

| Alternativa | Duplicado de **entrega** (mismo mensaje o evento) | Duplicado de **contenido** (misma reserva, otro mensaje) | Reversión de estado (A → B → A) | Costo | CON-09 |
|---|---|---|---|---|---|
| **N1. Clave de idempotencia por mensaje** (bandeja de entrada) | ✅ | ❌ no lo ve | ✅ | ⚠️ tabla con retención acotada | ✅ |
| **N2. Registro de huellas de contenido procesado** | ✅ | ✅ | ❌ **trata el regreso a un estado anterior como duplicado** | ⚠️ | ✅ |
| **N3. Operaciones naturalmente idempotentes** (fusión determinista) | ✅ | ✅ | ✅ si se ordena por versión de la fuente | ✅ | ⚠️ exige una fusión determinista y bien probada |
| **N1 + N3** ⬅ **elegido** | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |

### Por qué N1 + N3

N2 parece la solución obvia y tiene un defecto de fondo: **una huella de contenido no distingue «ya
procesé este estado» de «el estado volvió a ser este»**. Si un vuelo pasa de las 10:00 a las
10:30 y vuelve a las 10:00, la tercera observación tiene la misma huella que la primera y N2 la
descartaría, dejando al usuario con un horario falso. Es un error silencioso del tipo que QA-11
prohíbe.

N1 corta la duplicación **donde nace** (los dos caminos de ingesta de D4) y ahorra el costo de
extraer dos veces el mismo mensaje. N3 es la **garantía**: aplicar dos veces la misma observación
da el mismo estado consolidado, porque la observación se identifica por `(fuente, idDeFuente)` y
se ordena por la versión de la fuente. Una sin la otra no alcanza: N1 no ve el contenido repetido
y N3 sola obliga a extraer y fusionar duplicados que podrían haberse evitado.

| Capa | Mecanismo | Clave | Dónde |
|---|---|---|---|
| Ingreso del mensaje | Bandeja de entrada | `(buzón, idDeMensaje)` | `mail-ingest` |
| Consumo de cada evento | Bandeja de entrada | `(consumidor, idDeEvento)` | todo elemento que consume eventos |
| Observación | Unicidad | `(reserva, fuente, idDeFuente)` | `itinerary` |
| Comandos del usuario | Cabecera `Idempotency-Key` | clave enviada por el cliente | `POST /reservas`, `POST /casos` |
| Publicación | *Outbox* transaccional | `idDeEvento` | todo elemento que publica |

La ventana de retención de la bandeja de entrada debe superar el intervalo máximo de
reconciliación de [ADR-0004](../../03-adr/ADR-0004-obtencion-de-correo.md); el valor inicial
propuesto es de 14 días y se calibra. Las notificaciones al usuario tienen su propia bandeja de
entrada: un evento duplicado no debe producir dos avisos.

**Una advertencia que se hereda a R-4.** La bandeja de entrada es correcta solo si **todos los
mensajes de un usuario pasan por la misma partición**. Con el activo-activo de D2, dos regiones
podrían procesar a la vez dos copias del mismo mensaje. Es la razón por la que esta decisión
queda atada a R-1 y se cierra junto con él en la iteración 3 ([paso 7](paso-7-analisis.md#riesgos-residuales)).

→ [ADR-0014](../../03-adr/ADR-0014-idempotencia-de-la-ingesta.md)

---

## D15 — Política de confianza de extracción (QA-11)

**Problema:** R-2 es el riesgo más frágil: los formatos de correo cambian sin aviso. QA-11 pide
dos cosas que tiran en direcciones opuestas: **0 % de extracción incorrecta silenciosa** y **95 %
de acierto** sobre los 20 remitentes más frecuentes. Un umbral muy alto sacrifica cobertura y
devuelve al usuario a revisar su correo; uno muy bajo contamina el itinerario.

| Alternativa | QA-11: 0 % silenciosa | QA-11: 95 % de acierto (cobertura) | Fricción (el usuario revisa) | Mantenimiento | Mitigación verificable de R-2 |
|---|---|---|---|---|---|
| **O1. Umbral fijo global** | ❌ un mismo número es laxo para unos remitentes y estricto para otros | ⚠️ | ⚠️ | ✅ | ❌ |
| **O2. Umbral por remitente** (por extractor) | ✅ calibrado contra el corpus de cada formato | ✅ | ✅ | ⚠️ hay que calibrar cada extractor | ✅ visible por remitente |
| **O3. Confirmación del usuario por debajo del umbral** | ✅ nada entra sin revisión | ✅ | ⚠️ carga para el usuario | ✅ | ⚠️ |
| **O2 + O3, con dos umbrales (tres bandas)** ⬅ **elegido** | ✅ | ✅ | ✅ la revisión queda para la banda media | ⚠️ | ✅ |

### Por qué O2 + O3

O1 es la forma más simple y se descarta porque la confianza **no está calibrada igual entre
extractores**: un 0,9 de un formato muy estable y un 0,9 de uno con plantillas cambiantes no
significan lo mismo. O3 sola obligaría a confirmar todo lo que no sea perfecto y convertiría el
sistema en un formulario de revisión, anulando su propuesta de valor.

Se adoptan **dos umbrales por extractor** que dividen el resultado en tres bandas:

| Banda | Condición | Qué ocurre |
|---|---|---|
| **Alta** | Confianza ≥ umbral alto del extractor **y** validación estructural superada | La reserva se agrega como `Confirmada`, con origen «correo», y se avisa que se agregó |
| **Media** | Entre el umbral bajo y el alto | La reserva entra como `PorConfirmar`: aparece en una sección propia del panel, **no** en el itinerario confirmado y **no** dispara avisos críticos. El usuario confirma, corrige o descarta |
| **Baja** | Menor que el umbral bajo, o ningún extractor reconoce el formato | **No entra nada.** Se publica `ExtraccionNoReconocida` y se ofrece la carga manual. El sistema no inventa |

La confianza de una reserva es el **mínimo** de la confianza de sus campos obligatorios, no el
promedio: una fecha dudosa no se compensa con un código seguro. Los valores iniciales son 0,90 y
0,60, y son un **supuesto a calibrar** con el corpus del prototipo, no un driver.

### Mitigación concreta y verificable de R-2

La regla de «no inventar» de la iteración 1 era estructural; esta iteración la acompaña con
mecanismos que se pueden **medir**:

| # | Mecanismo | Cómo se verifica |
|---|---|---|
| 1 | **Corpus de referencia por extractor**: correos reales anonimizados, con la salida esperada | Una puerta de integración continua exige ≥ 95 % de acierto por mensaje sobre los campos obligatorios y **cero** extracciones incorrectas en la banda alta |
| 2 | **Validación estructural previa al puntaje**: fecha de fin posterior a la de inicio, localizador con el patrón del emisor, lugar resoluble, zona horaria presente | Cualquier falla fuerza la banda media o baja, sin importar la confianza |
| 3 | **Observabilidad por extractor**: proporción de cada banda y proporción de reservas de banda alta que el usuario corrigió después | Panel y alarma por extractor. Las correcciones del usuario son la señal del error silencioso |
| 4 | **Disyuntor de calidad**: si la proporción de correcciones o de banda baja supera un umbral en una ventana, el extractor pasa a «solo confirmación» (todo va a la banda media) | Prueba con el corpus degradado: el disyuntor debe abrirse |
| 5 | **Modo sombra** para versiones nuevas de un extractor: corre sobre tráfico real y se compara con la versión vigente sin publicar | La versión se promueve solo si no empeora el corpus ni la comparación |

**Lo que esto no resuelve.** Un formato nuevo, sin corpus, no está cubierto hasta que alguien lo
agregue; y la cifra de 95 % solo es cierta sobre el corpus. Por eso R-2 queda **mitigado y no
cerrado** ([paso 7](paso-7-analisis.md#riesgos-residuales)).

→ [ADR-0015](../../03-adr/ADR-0015-politica-de-confianza-de-extraccion.md)

---

## D16 — Modelo dimensional del plano analítico (RF-14)

**Problema:** el equipo de datos va a monetizar tendencias, destinos y cancelaciones con consultas
pesadas sobre tres años de historia, con frescura ≤ 1 hora (AMB-07), y el plano analítico debe
absorber tipos de segmento nuevos sin rediseño (QA-15).

| Alternativa | RF-14 (consultas) | QA-15 (tipo nuevo) | Frescura ≤ 1 h | Costo de consulta | Consistencia entre consultas |
|---|---|---|---|---|---|
| **P1. Esquema en estrella** (hechos y dimensiones conformes) | ✅ | ✅ una fila nueva en `dim_tipo_segmento` | ✅ micro-lotes | ✅ | ✅ las dimensiones se comparten |
| **P2. Tabla ancha desnormalizada** | ✅ rápida para lo previsto | ❌ columnas dispersas por tipo | ✅ | ✅ | ⚠️ cada consulta nueva repite la lógica |
| **P3. Eventos crudos con vistas** | ⚠️ | ✅ | ✅ | ❌ cada consulta reinterpreta el JSON de los eventos | ❌ |
| **P1 sobre P3 como capa de aterrizaje** ⬅ **elegido** | ✅ | ✅ | ✅ | ✅ | ✅ |

### Por qué P1 sobre P3

P2 es la más rápida de construir y la que peor envejece: los atributos propios de cada tipo de
segmento la llenarían de columnas casi vacías, y cada tipo nuevo cambiaría la tabla que usan todas
las consultas. P3 sola es flexible pero deja a los analistas reinterpretando el detalle JSON de
cada evento en cada consulta, con resultados que difieren de un analista a otro.

Se adopta P1 **alimentada desde P3**: los eventos de dominio se retienen crudos (inmutables) y de
ellos se construyen los hechos y dimensiones. Si el modelo dimensional cambia, se reconstruye
desde los eventos sin tocar el plano operacional, que es lo que D3 buscaba al separar los planos.

El modelo tiene **dos hechos** (cambios de reserva, que es transaccional, y viaje, que es un
*snapshot* acumulativo con sus hitos) y **seis dimensiones**; está en el
[README](README.md#59-el-modelo-dimensional-del-plano-analítico). La dimensión de usuario guarda
un **seudónimo** y no datos personales, previendo CON-10; la política completa es de la iteración 4.

→ [ADR-0016](../../03-adr/ADR-0016-modelo-dimensional-analitico.md)

---

## D17 — Estrategia de pruebas y verificación de contratos (CRN-06, CON-04)

Esta decisión no es estructural, pero cierra el criterio de salida 3 (todas las interfaces con
contrato) y hace verificables QA-10 y QA-11; por eso se toma acá, como D8 y D9 en la iteración 1.

| Alternativa | CON-04 (*spec-driven*) | QA-10 (adaptador nuevo verificable) | QA-11 (extractor verificable) | Cambios de terceros | CON-09 |
|---|---|---|---|---|---|
| **Q1. Pruebas de extremo a extremo en un entorno integrado** | ⚠️ | ⚠️ lentas | ⚠️ | ❌ dependen de los entornos de prueba ajenos | ❌ costosas y frágiles para cuatro personas |
| **Q2. Pruebas de contrato dirigidas por el consumidor** (con un *broker* de contratos) | ✅ | ✅ | ⚠️ | ❌ los terceros no publican contratos de consumidor | ⚠️ otro componente que operar |
| **Q3. Pruebas derivadas de la especificación** (OpenAPI y AsyncAPI como fuente) ⬅ **elegido** | ✅ el contrato es la fuente de verdad | ✅ suite de conformidad reutilizable | ✅ corpus de referencia | ✅ grabaciones de las respuestas reales, revalidadas periódicamente | ✅ |

### Por qué Q3

Q1 se descarta por CON-09 y porque depende de entornos de terceros que el equipo no controla.
Q2 es la técnica más precisa entre equipos internos independientes y se descarta por costo: con
cuatro personas y un contrato que ya es la fuente de verdad (ADR-0009), un *broker* agrega una
pieza a operar sin que resuelva el problema principal, que es el de los **terceros**, quienes no
van a publicar contratos de consumidor. Se deja como alternativa a reconsiderar si el equipo crece.

| Nivel | Qué verifica | Contra qué |
|---|---|---|
| Contrato sincrónico | Que cada implementación cumple su OpenAPI y que los clientes no esperan algo ajeno a él | La especificación; detección de cambios incompatibles en cada cambio |
| Contrato de eventos | Que cada evento publicado y consumido cumple su AsyncAPI | La especificación |
| **Suite de conformidad de complementos** | Que un adaptador o un extractor cumple el contrato canónico **y** que su salida valida contra el esquema del tipo de segmento | La misma suite para todos: es lo que vuelve literal «0 elementos existentes modificados» de QA-10 |
| Corpus de referencia | Acierto de cada extractor y comportamiento del disyuntor de calidad | Correos anonimizados (D15) |
| Grabaciones de terceros | Que los proveedores no cambiaron su contrato | Respuestas reales grabadas, revalidadas con una frecuencia fija |
| Propiedades de la fusión | Que la consolidación es determinista e idempotente: mismas observaciones en cualquier orden, mismo estado | Pruebas basadas en propiedades sobre `Reserva` |

→ [ADR-0017](../../03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md)

---

## Tácticas de atributos de calidad aplicadas en esta iteración

Las decisiones anteriores instancian conceptos de diseño; estos a su vez aplican tácticas. Esta
tabla las deja explícitas, porque el enunciado evalúa «la correcta utilización de patrones y
tácticas de diseño» (§5).

| Atributo | Táctica | Dónde se aplica | Decisión |
|---|---|---|---|
| Modificabilidad | Encapsular | Agregados `Reserva` y `Viaje` con invariantes en la raíz | D10 |
| Modificabilidad | Aumentar la cohesión semántica | Nueve módulos de `itinerary` con responsabilidad única | D10 |
| Modificabilidad | Restringir dependencias | Reglas de dependencia entre los módulos de `itinerary` | D10 |
| Modificabilidad | Diferir el enlace | Descriptores de tipo de segmento cargados desde configuración | D11 |
| Modificabilidad | Generalizar el módulo | Núcleo común del segmento y detalle declarado por tipo | D11 |
| Rendimiento | Mantener múltiples copias de datos | Proyección `panel_usuario` mantenida por eventos | D10, D12 |
| Rendimiento | Reducir la demanda | Coalescencia de notificaciones por viaje | RF-10 |
| Rendimiento | Priorizar eventos | Severidad crítica de las notificaciones sin espera | RF-10 |
| Escalabilidad | Particionamiento de datos por usuario | `usuario_id` como clave de partición de todo el plano operacional | D12 |
| Escalabilidad | Separar lectura y escritura | `itinerary` con dos modos de despliegue | D10 |
| Disponibilidad | Reintento con operaciones idempotentes | Bandeja de entrada y fusión determinista | D14 |
| Disponibilidad | Transacciones | *Outbox*: el cambio y su evento se escriben atómicamente | D12, D14 |
| Disponibilidad | Degradación gradual | Extractor en modo «solo confirmación» | D15 |
| Disponibilidad | Disyuntor | Disyuntor de **calidad** del extractor (además del de disponibilidad de D6) | D15 |
| Disponibilidad | Detección de excepciones | Validación estructural previa al puntaje de confianza | D15 |
| Interoperabilidad | Adaptar interfaces | Contrato canónico de adaptador y de extractor, con salida `ObservaciónCanónica` | D11, D17 |
| Seguridad | Reducir la exposición de datos | Filtros por remitente evaluados sobre metadatos **antes** de descargar el cuerpo | RF-04 |
| Seguridad | Mantener la confidencialidad | Seudónimo de usuario en el plano analítico | D16 |
| Seguridad | Auditar | Observaciones que no se modifican: historial completo de cada valor y de su fuente | D10, D13 |
| Testabilidad | Especializar las interfaces de acceso | Contratos verificables y suite de conformidad de complementos | D17 |
| Testabilidad | Grabar y reproducir | Grabaciones de respuestas de terceros y corpus de correos | D15, D17 |
| Testabilidad | Aislar la fusión como función determinista | Pruebas basadas en propiedades | D10, D17 |