---
estado: aceptado
fecha: 2026-11-17
decisores: Francisco Lozano
consultados: —
informados: equipo completo
iteracion: 5
drivers: RF-B2, RF-12, CON-06, CRN-12, QA-04, QA-14
---

# ADR-0039: El asistente deriva a la agencia ante cuatro situaciones explícitas, con confirmación del viajero y un caso idempotente por el contrato existente de `support-liaison`

## Contexto y planteo del problema

RF-B2 pide delegar a la agencia preferida **únicamente** los casos que el bot no resuelve. Las dos
formas de fallar son simétricas: derivar de más satura a la agencia con consultas que el bot podía
contestar; derivar de menos deja al viajero atrapado en un diálogo que no avanza, justo cuando tiene
un problema real (por ejemplo, una cancelación por clima).

`support-liaison` ya expone `POST /casos` (RF-12): idempotente por `Idempotency-Key`, deriva a la
agencia preferida, guarda una instantánea del viaje y publica `CasoDerivado`. Pide `viajeId` y un
`motivo` (`cancelacion`, `cambioDeHorario`, `reprogramacion`, `otro`), acepta una `descripcion` de
hasta 2.000 caracteres y un `idDeCausa` cuando el pedido nace de una disrupción, y responde `422` si
el viajero no tiene agencia preferida.

## Drivers de decisión

* **RF-B2** — derivar solo lo que el bot no resuelve.
* **RF-12** — derivación rápida a la agencia preferida.
* **CON-06** — cero interfaces nuevas ([ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)).
* **CRN-12** — un reintento no puede abrir dos casos.
* **QA-14** — la síntesis que viaja a la agencia no lleva más datos personales que los necesarios.

## Opciones consideradas

* **L1** — Derivar ante cualquier cosa que no sea una consulta.
* **L2** — Derivar solo cuando el viajero lo pide.
* **L3** — Cuatro disparadores explícitos, propuesta y confirmación, y caso idempotente por
  `POST /casos`.

## Resultado de la decisión

Se adopta **L3**. El asistente **propone** derivar (una `AccionPropuesta` de tipo `derivarALaAgencia`,
como en [ADR-0038](ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md)) en estas cuatro
situaciones, y solo en ellas:

| Disparador | Cuándo | `motivo` del caso | `idDeCausa` |
|---|---|---|---|
| **Cambio ante el proveedor** | Intención `cambioAnteProveedor`: reprogramar o cancelar con la aerolínea o el hotel, reembolsos, reclamos | `reprogramacion`, `cancelacion` u `otro`, según el pedido | — |
| **El viajero lo pide** | Intención `pedirAgencia` («quiero hablar con mi agencia», «con una persona») | `otro` | — |
| **No entiende dos veces seguidas** | Dos turnos consecutivos con `noEntendido` ([ADR-0037](ADR-0037-interpretacion-de-intenciones-del-asistente.md)) | `otro` | — |
| **Disrupción sin salida simple** | La reserva por la que pregunta tiene una disrupción conocida de severidad `alta` ([ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md)): corregir el itinerario no resuelve un vuelo cancelado | `cancelacion` o `cambioDeHorario` | El `disrupcionId` |

Cómo se deriva:

1. **Siempre con confirmación,** también cuando el viajero lo pidió: derivar contacta a un tercero, y
   el viajero ve qué se le va a enviar a su agencia antes de que salga.
2. **Hace falta un viaje.** `POST /casos` pide `viajeId`: si la conversación no está sobre un viaje y
   el viajero tiene varios, el asistente pregunta cuál antes de proponer.
3. **La síntesis es estructurada y mínima.** La `descripcion` resume el pedido y los turnos
   relevantes (qué reserva, qué pasó, qué quiere el viajero) sin copiar la conversación entera, en
   ≤ 2.000 caracteres.
4. **Idempotente.** La `Idempotency-Key` del caso se deriva de la acción propuesta: confirmar dos
   veces, o un reintento de red, abre **un** caso.
5. **Sin agencia preferida (`422`),** el asistente explica cómo configurarla y no insiste.
6. Después de derivar, el contador de «no entendidos» vuelve a cero y la conversación sigue: el
   viajero puede consultar el estado del caso por `support-liaison`.

### Consecuencias

* **Bueno,** porque la frontera entre lo que resuelve el bot y lo que va a la agencia es explícita y
  probable: cuatro disparadores, cada uno con su prueba.
* **Bueno,** porque reutiliza `POST /casos` tal como está: idempotencia, instantánea del viaje y
  `CasoDerivado` vienen gratis (CON-06).
* **Bueno,** porque el viajero nunca queda atrapado: a los dos malentendidos se le ofrece salir.
* **Malo,** porque la confirmación agrega un turno incluso cuando el viajero ya pidió la agencia.
* **Neutro,** porque el umbral de dos intentos es un supuesto a calibrar con uso real.

### Confirmación

* Una prueba por disparador, que verifica la propuesta y el `motivo` y el `idDeCausa` del caso.
* Prueba de idempotencia: confirmar dos veces la misma derivación abre un solo caso.
* Prueba de que sin confirmación no se llama a `POST /casos`, y de la respuesta ante `422`.
* Prueba de que una consulta de estado nunca termina en derivación.

## Pros y contras de las opciones

### L1 — Derivar todo lo que no sea consulta

* Bueno, porque nunca deja al viajero sin respuesta humana.
* Malo, porque satura a la agencia con lo que el bot podía resolver: contradice el «únicamente» de
  RF-B2.

### L2 — Solo cuando el viajero lo pide

* Bueno, porque el viajero tiene el control.
* Malo, porque ante un malentendido repetido o una cancelación el viajero queda atrapado hasta que se
  le ocurra pedirlo.

### L3 — Cuatro disparadores con confirmación

* Bueno, porque cubre los casos reales sin derivar de más.
* Malo, porque cada disparador nuevo exige una decisión explícita (es intencional).

## Más información

* Iteración: [iteración 5, paso 4, D39](../02-proceso-add/iteracion-5/paso-4-alternativas.md#d39--cuándo-y-cómo-deriva-a-la-agencia-rf-b2)
* Contratos: [`support-liaison.yaml`](../../contratos/openapi/support-liaison.yaml) (`POST /casos`), [`virtual-assistant.yaml`](../../contratos/openapi/virtual-assistant.yaml)
* Relacionados: [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md), [ADR-0037](ADR-0037-interpretacion-de-intenciones-del-asistente.md), [ADR-0038](ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md), [ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md)
