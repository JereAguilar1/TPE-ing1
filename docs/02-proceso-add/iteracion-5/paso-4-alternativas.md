# Iteración 5 — Paso 4: conceptos de diseño y alternativas

> Volver a la [iteración 5](README.md).

Cuatro decisiones de esta iteración refinan **el interior** del elemento nº 14 que
[ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) dejó como frontera: cómo
entiende al viajero (**D37**), qué resuelve solo (**D38**), cuándo deriva a la agencia (**D39**) y qué
recuerda de la conversación (**D40**). Ninguna toca un servicio existente: la frontera de la
iteración 4 se respeta tal cual (`CON-06`). La quinta (**D41**) precisa una inconsistencia de la 1ra
entrega que apareció al revisar las entradas: quién genera el alias de reenvío.

Las cuatro se apoyan entre sí: D37 decide qué entiende el asistente y con qué confianza; D38 y D39
deciden qué hace con eso; D40 guarda lo mínimo para que el diálogo de D38 y D39 funcione.

---

## D37 — Cómo entiende el asistente lo que escribe el viajero (`RF-B1`, `QA-14`)

**Problema:** el viajero escribe texto libre. Antes de actuar, el asistente necesita la intención (qué
pide) y las entidades (sobre qué reserva, qué fecha y hora nuevas). Un modelo de lenguaje entiende
mejor pero envía datos personales a un tercero, no es determinista y necesita una clave paga; las
reglas son predecibles pero entienden solo lo que se previó.

| Alternativa | Comprensión de texto libre | Datos personales (`QA-14`, `CON-10`) | Verificable con pruebas (`QA-16`) | Costo y alcance (`CON-05`, `CON-09`) | Camino de mejora |
|---|---|---|---|---|---|
| **I1. Solo reglas** | ⚠️ solo lo previsto | ✅ nada sale del sistema | ✅ determinista | ✅ | ❌ mejorar exige reescribir |
| **I2. Solo un modelo de lenguaje externo** | ✅ | ❌ cada mensaje viaja a un tercero | ❌ salida no determinista | ❌ clave paga, también en la CI | ✅ |
| **I3. Puerto `InterpreteDeIntenciones`: reglas en el prototipo y modelo enchufable con datos redactados** ⬅ **elegido** | ⚠️ en el prototipo, ✅ con el modelo | ✅ con reglas; redactados con el modelo | ✅ en el prototipo | ✅ | ✅ se agrega un adaptador |

### Por qué I3

**I2** resolvería mejor la comprensión pero rompe tres cosas a la vez: datos personales a un tercero
en cada mensaje, pruebas no repetibles y un secreto pago en la integración continua. **I1** es lo que
el prototipo necesita, pero cerrado. **I3** construye I1 detrás de un puerto con la misma salida que
tendría I2, de modo que pasar a un modelo es agregar un adaptador (la misma idea de complementos de
[ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md)). Por debajo de una confianza de 0,6 el
asistente no actúa: repregunta.

→ [ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md)

---

## D38 — Qué resuelve el asistente solo, y cómo (`RF-B1`)

**Problema:** el enunciado pide «reprogramaciones». Trotamundos no vende ni cambia pasajes: registra lo
que el viajero ya reservó. Lo que sí puede hacer el asistente es mantener el itinerario al día cuando
el viajero ya cambió algo, con el comando de la gestión manual (`PUT /reservas/{id}`), y ayudarlo
con los dos «problemas menores» que el itinerario ya tiene: una reserva por confirmar y un conflicto
entre fuentes. Pero un malentendido no puede terminar en un cambio.

| Alternativa | Cubre «reprogramaciones» (`RF-B1`) | Riesgo de un cambio por error | Reusa reglas del dominio (`RF-06`, `ADR-0013`) | Interfaces nuevas (`CON-06`) |
|---|---|---|---|---|
| **K1. Solo consultas; todo cambio se deriva** | ❌ | ✅ nulo | — | ✅ `0` |
| **K2. El asistente cambia el itinerario cuando entiende el pedido** | ✅ | ❌ un malentendido cambia el itinerario | ✅ | ✅ `0` |
| **K3. Consultas directas; corrección del itinerario y problemas menores, propuestos y confirmados; cambios ante el proveedor, derivados** ⬅ **elegido** | ✅ en lo que el sistema puede hacer | ✅ el viajero ve el cambio exacto antes | ✅ fijados, conflictos y versión | ✅ `0` |

### Por qué K3

**K1** deja afuera lo que pide el enunciado. **K2** es útil pero inseguro. **K3** separa lo que el
sistema puede hacer (corregir su propio itinerario) de lo que no (cambiar la reserva ante el
proveedor), y pone una confirmación explícita, con vencimiento, entre la propuesta y el cambio. Como
la corrección entra por `PUT /reservas/{id}`, hereda los fijados, los conflictos y el control de
versión de la gestión manual sin lógica duplicada. Los problemas menores usan los comandos que
`itinerary` ya tenía para eso (`POST /reservas/{id}/confirmacion` y
`POST /reservas/{id}/conflictos/{cid}/resolucion`), con la misma confirmación.

→ [ADR-0038](../../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md)

---

## D39 — Cuándo y cómo deriva a la agencia (`RF-B2`)

**Problema:** RF-B2 pide derivar **únicamente** lo que el bot no resuelve. Derivar de más satura a la
agencia; derivar de menos deja al viajero atrapado justo cuando tiene un problema real.

| Alternativa | «Únicamente» lo que no resuelve (`RF-B2`) | El viajero nunca queda atrapado | Un reintento abre un solo caso (`CRN-12`) | Interfaces nuevas (`CON-06`) |
|---|---|---|---|---|
| **L1. Derivar todo lo que no sea consulta** | ❌ deriva de más | ✅ | ✅ con `POST /casos` | ✅ `0` |
| **L2. Derivar solo cuando el viajero lo pide** | ✅ | ❌ ante malentendidos o cancelaciones | ✅ | ✅ `0` |
| **L3. Cuatro disparadores explícitos, con confirmación y caso idempotente** ⬅ **elegido** | ✅ | ✅ a los dos malentendidos se ofrece salir | ✅ clave derivada de la acción | ✅ `0` |

### Por qué L3

Los cuatro disparadores cubren los casos reales: un cambio ante el proveedor, el pedido explícito del
viajero, dos malentendidos seguidos y una disrupción de severidad alta que corregir el itinerario no
resuelve. Cada uno tiene su `motivo` en el caso; la disrupción va como `otro`, porque el evento no
dice si fue una cancelación o una demora, con su descripción y su `idDeCausa`. La derivación
se confirma siempre, porque contacta a un tercero, y usa `POST /casos` tal como está: idempotencia,
instantánea del viaje y `CasoDerivado` vienen sin cambios.

→ [ADR-0039](../../03-adr/ADR-0039-politica-de-derivacion-a-la-agencia.md)

---

## D40 — Memoria de la conversación y privacidad (`QA-14`, `CON-10`)

**Problema:** un diálogo de varios turnos necesita memoria (el viaje en foco, la acción pendiente, los
malentendidos seguidos), y esa memoria es un dato personal. Además, ADR-0034 pide suprimirla al
recibir `CuentaSuprimida`, pero ese evento no trae el `usuarioId` (ADR-0030).

| Alternativa | Diálogo de varios turnos (`RF-B1`) | Una acción pendiente no la decide el cliente | Supresión que funciona (`QA-14`) | Conoce las disrupciones sin interfaces nuevas |
|---|---|---|---|---|
| **M1. Sin estado: el BFF manda la conversación entera** | ✅ | ❌ el cliente podría confirmar algo no propuesto | ✅ trivial | ❌ |
| **M2. Estado propio; supresión por `CuentaSuprimida`** | ✅ | ✅ | ❌ el evento no trae `usuarioId` | ⚠️ |
| **M3. Estado propio y mínimo, retención de 30 días, supresión de fase 1 por `usuario_id` y `DisrupcionDetectada`** ⬅ **elegido** | ✅ | ✅ | ✅ mismo mecanismo que el plano operacional | ✅ evento existente |

### Por qué M3

**M1** pone la acción pendiente en manos del cliente. **M2** sigue literalmente a ADR-0034, pero su
supresión no puede funcionar: `CuentaSuprimida` lleva el seudónimo analítico y no el `usuarioId`.
**M3** guarda lo mínimo (sin copias del itinerario), lo borra solo a los 30 días y se suma a la fase 1
de [ADR-0030](../../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md), en la que
`identity-access` ordena el borrado por `usuario_id` a cada servicio operacional. Es una **precisión
de ADR-0034**, que se registra en el ADR nuevo porque un ADR aceptado no se edita.

→ [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md)

---

## D41 — Quién genera el alias de reenvío (`CON-08`, precisión de ADR-0035)

**Problema:** [ADR-0035](../../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) dice que
el alias `viajes+<token>@ingesta.trotamundos.app` lo asigna `mail-ingest`, pero el contrato publicado
`identity-access.yaml` lo devuelve en `POST /buzones`, y así se construyó (pasos 7 y 8). Un ADR
aceptado no se edita: hace falta decidir cuál de los dos manda y registrarlo.

| Alternativa | El viajero ve su alias al conectar el buzón | Interfaces nuevas (`CON-06`) | Coincide con el contrato publicado (`CON-04`) |
|---|---|---|---|
| **N1. Lo genera `mail-ingest`, con una llamada sincrónica desde `identity-access`** | ✅ | ❌ una llamada nueva | ❌ |
| **N2. Lo genera `mail-ingest`, de forma asincrónica** | ❌ lo ve después | ✅ | ❌ |
| **N3. Lo genera `identity-access` y lo publica en `EstadoDeBuzonCambiado`** ⬅ **elegido** | ✅ | ✅ | ✅ |

### Por qué N3

Es la única que cumple las tres cosas, y es lo que ya dicen los contratos y lo que está construido.
La verificación del reenvío de ADR-0035 (DKIM, SPF o ARC y titular) no cambia: solo cambia quién
genera el alias.

→ [ADR-0041](../../03-adr/ADR-0041-alias-de-reenvio-generado-por-identity-access.md)
