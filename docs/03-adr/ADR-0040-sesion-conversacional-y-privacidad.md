---
estado: aceptado
fecha: 2026-11-17
decisores: Francisco Lozano
consultados: —
informados: equipo completo
iteracion: 5
drivers: RF-B1, QA-14, CON-10, QA-04, QA-12, CRN-12, CON-A4
---

# ADR-0040: El asistente guarda solo su sesión conversacional, particionada por usuario, con retención acotada; entra en la supresión de fase 1 por `usuario_id` y conoce las disrupciones por `DisrupcionDetectada`

## Contexto y planteo del problema

Una conversación tiene memoria: el viaje del que se habla, la acción propuesta que espera
confirmación ([ADR-0038](ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md)) y cuántas
veces seguidas no se entendió al viajero ([ADR-0039](ADR-0039-politica-de-derivacion-a-la-agencia.md)).
Esa memoria es un dato personal: el texto que escribe el viajero puede traer nombres, localizadores o
problemas de salud.

Además, para detectar una «disrupción sin salida simple», el asistente tiene que saber qué
disrupciones afectan las reservas del viajero. `DisrupcionDetectada` ya trae, por cada disrupción,
los usuarios afectados y sus reservas.

[ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md) dice que el módulo avanzado «suscribe
`CuentaSuprimida` para borrar su estado propio». Pero ese evento, por diseño
([ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)), **no lleva el `usuarioId`**, solo el
seudónimo analítico: el asistente no tendría cómo saber qué borrar. ADR-0030 resuelve la fase 1 de
otra forma: `identity-access` **ordena el borrado por `usuario_id`** a cada servicio operacional.

## Drivers de decisión

* **RF-B1** — una conversación de varios turnos.
* **QA-14 / CON-10** — minimización, retención acotada y supresión verificable.
* **QA-12** — una sesión nunca la ve otro usuario.
* **QA-04** — el asistente no puede sumar carga sobre el núcleo.
* **CON-A4** — sigue siendo un solo elemento (nº 14).

## Opciones consideradas

* **M1** — Sin estado: el BFF manda la conversación entera en cada mensaje.
* **M2** — Estado propio en el esquema del asistente, particionado por `usuario_id`, con retención
  acotada, y supresión por `CuentaSuprimida`.
* **M3** — Como M2, pero la supresión entra en la fase 1 de ADR-0030 (borrado ordenado por
  `usuario_id`), y las disrupciones llegan por `DisrupcionDetectada`.

## Resultado de la decisión

Se adopta **M3**:

1. **Qué se guarda.** En el esquema propio del asistente, con `usuario_id` en la clave
   ([ADR-0012](ADR-0012-persistencia-del-plano-operacional.md)): la sesión (viaje en foco, acción
   pendiente con su vencimiento, contador de «no entendidos») y sus turnos (texto, intención y hora).
   **No** guarda copias del itinerario: lo lee cuando lo necesita (ADR-0038).
2. **Retención: 30 días** desde el último turno (supuesto a calibrar); un trabajo periódico borra lo
   vencido. Una sesión de otro usuario responde `404`.
3. **Supresión: fase 1 de ADR-0030.** El asistente se suma a la lista de servicios operacionales a
   los que `identity-access` ordena el borrado físico por `usuario_id` (`itinerary`, `preferences`,
   `sharing`, `support-liaison`). **No** se suscribe a `CuentaSuprimida`: esta decisión **precisa
   ADR-0034** en ese punto, que no era aplicable tal como estaba escrito. La retención de 30 días es
   la segunda línea de defensa.
4. **Disrupciones: `DisrupcionDetectada`.** El asistente consume ese evento (carril P1) con su bandeja
   de entrada ([ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md)) y guarda, por usuario afectado,
   qué reservas tiene afectadas, con qué severidad y el `disrupcionId`. Lo usa para contestar y para
   el disparador de ADR-0039. Se agrega como consumidor en el contrato AsyncAPI (1.5.0).
5. **No consume `PreferenciasActualizadas`.** La agencia preferida la resuelve `support-liaison` al
   abrir el caso; el asistente no necesita copiarla. Si se agrega el idioma de las respuestas
   ([ADR-0032](ADR-0032-internacionalizacion-y-localizacion.md)), se consumirá entonces.
6. **Degradable.** Ante `Disrupción masiva` ([ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md)), el
   asistente es carga de prioridad 2/3: responde con un mensaje de servicio reducido antes de quitarle
   recursos a `itinerary`.

### Consecuencias

* **Bueno,** porque la memoria de la conversación es la mínima para que funcione, y desaparece sola.
* **Bueno,** porque la supresión usa el mismo mecanismo que el resto del plano operacional, en lugar
  de un camino que no podía funcionar.
* **Bueno,** porque las disrupciones llegan por un evento que ya existía (CON-06).
* **Malo,** porque hay una proyección más de disrupciones, que se purga con la bandeja de entrada.
* **Neutro,** porque el borrado ordenado de la fase 1 no está construido para ningún servicio en el
  prototipo (paso 14 del plan); hasta entonces, rige la retención.

### Confirmación

* Prueba de que una sesión de otro usuario responde `404`.
* Prueba de que el trabajo periódico borra las sesiones con más de 30 días sin turnos.
* Prueba de que `DisrupcionDetectada` repetido no duplica la proyección, y de que el asistente
  menciona la disrupción al consultar la reserva afectada.

## Pros y contras de las opciones

### M1 — Sin estado

* Bueno, porque no hay nada que retener ni suprimir.
* Malo, porque una acción pendiente quedaría en manos del cliente, que podría confirmar algo que el
  asistente nunca propuso.

### M2 — Estado propio, supresión por `CuentaSuprimida`

* Bueno, porque sigue literalmente a ADR-0034.
* Malo, porque `CuentaSuprimida` no trae el `usuarioId` (ADR-0030): la supresión no funcionaría.

### M3 — Estado propio, supresión de fase 1 y `DisrupcionDetectada`

* Bueno, porque es coherente con ADR-0030 y con lo que ya existe.
* Malo, porque depende de un borrado ordenado que el prototipo todavía no construye.

## Más información

* Iteración: [iteración 5, paso 4, D40](../02-proceso-add/iteracion-5/paso-4-alternativas.md#d40--memoria-de-la-conversación-y-privacidad-qa-14-con-10)
* Contratos: [`virtual-assistant.yaml`](../../contratos/openapi/virtual-assistant.yaml), [`eventos-de-dominio.yaml`](../../contratos/asyncapi/eventos-de-dominio.yaml) (`DisrupcionDetectada`)
* Relacionados: [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md), [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md), [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md), [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)
