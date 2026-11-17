---
estado: aceptado
fecha: 2026-11-17
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 5
drivers: RF-B1, RF-06, RF-07, QA-11, CON-06, QA-12, QA-04, CRN-11, CRN-12
---

# ADR-0038: El asistente responde consultas, corrige el itinerario y resuelve problemas menores solo con confirmación explícita; cambiar una reserva ante el proveedor no es algo que pueda hacer

## Contexto y planteo del problema

El enunciado pide que el bot gestione «reprogramaciones, consultas de estado y problemas menores».
Trotamundos no vende ni emite pasajes: **registra** lo que el viajero ya reservó con aerolíneas,
hoteles y rentadoras. Reprogramar un vuelo ante la aerolínea es algo que el sistema no puede hacer
(no tiene esa interfaz ni procesa pagos, [alcance](../01-analisis-inicial/01-proposito-y-alcance.md)).

Lo que sí puede hacer es mantener el itinerario al día. Si el viajero ya cambió su vuelo por su
cuenta («me pasaron el vuelo al jueves a las 18:30»), el asistente puede corregir esa reserva en el
itinerario con el mismo comando que usa la gestión manual (`PUT /reservas/{id}` de `itinerary`,
RF-06). Pero un asistente que entiende por reglas (o por un modelo de lenguaje,
[ADR-0037](ADR-0037-interpretacion-de-intenciones-del-asistente.md)) puede equivocarse: cambiar el
itinerario por un malentendido sería peor que no hacer nada.

## Drivers de decisión

* **RF-B1** — consultas de estado, reprogramaciones y problemas menores.
* **RF-06 / CRN-11** — la edición del viajero es una observación más y fija los campos que toca
  ([ADR-0013](ADR-0013-deduplicacion-y-conflictos.md)).
* **QA-11** — una reserva de banda media espera la confirmación del viajero
  ([ADR-0015](ADR-0015-politica-de-confianza-de-extraccion.md)).
* **CON-06** — cero interfaces nuevas en el núcleo ([ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)).
* **QA-12** — el asistente nunca ve ni toca datos de otro usuario.
* **QA-04** — una carga del asistente no puede frenar a `itinerary`.

## Opciones consideradas

* **K1** — Solo consultas: el bot responde y todo cambio lo deriva a la agencia.
* **K2** — El bot cambia el itinerario directamente cuando entiende el pedido.
* **K3** — Consultas directas; cambios del itinerario y problemas menores en dos pasos (el
  asistente **propone**, el viajero **confirma**), y todo cambio ante el proveedor se deriva.

## Resultado de la decisión

Se adopta **K3**:

1. **Consultas (`estadoDelViaje`, `proximoTramo`) sin pasos extra.** El asistente lee de
   `itinerary-lectura`, en nombre del viajero: `GET /panel` para saber qué viajes tiene, qué reservas
   esperan su confirmación y qué conflictos están abiertos (una reserva por confirmar no está en
   ningún viaje, así que solo aparece ahí), y `GET /viajes` y `GET /viajes/{id}` para el detalle de un
   viaje. Responde con fechas y horas en la zona del lugar ([ADR-0032](ADR-0032-internacionalizacion-y-localizacion.md)).
   Si hay una disrupción conocida sobre la reserva ([ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md)),
   la menciona.
2. **Corrección del itinerario (`corregirHorario`) en dos pasos.**
   * El asistente arma la edición —el tramo nuevo, con su inicio y su fin corridos lo mismo— y la
     **propone** con un resumen legible («Cambio tu vuelo AR1402 del jueves 3/12 10:00 al sábado 5/12
     18:30. ¿Confirmás?») y un `accionId` que vence a los **10 minutos** (supuesto a calibrar).
   * Recién con una `confirmacion` explícita de ese `accionId` ejecuta `PUT /reservas/{id}` con la
     `version` que leyó. Si `itinerary` responde `409` (la reserva cambió mientras tanto), relee y
     vuelve a proponer: nunca pisa un cambio que el viajero no vio.
   * El cambio entra como edición manual: queda **fijado** y, si después una fuente informa otra
     cosa, se abre un conflicto ([ADR-0013](ADR-0013-deduplicacion-y-conflictos.md)). El asistente no
     inventa un camino propio.
3. **Problemas menores, con la misma confirmación en dos pasos.** Son los dos casos en que el
   itinerario está esperando una decisión del viajero, y que `itinerary` ya sabe resolver:
   * **Una reserva por confirmar (`confirmarReserva`).** Llegó del correo con datos de banda media
     ([ADR-0015](ADR-0015-politica-de-confianza-de-extraccion.md)) y no entra a ningún viaje hasta que
     el viajero decida: el asistente la encuentra en `porConfirmar` de `GET /panel`. La muestra y propone confirmarla o descartarla
     (`POST /reservas/{id}/confirmacion`, acciones `confirmarReserva` y `descartarReserva`).
   * **Un conflicto entre fuentes (`resolverConflicto`).** El viajero fijó un valor y una fuente
     posterior informa otro (por ejemplo, él cargó 14:00 y la aerolínea dice 13:00,
     [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md)). El asistente lo encuentra en
     `conflictosAbiertos` de `GET /panel`, muestra los dos valores y propone mantener el suyo o aceptar el de la fuente
     (`POST /reservas/{id}/conflictos/{cid}/resolucion`).
4. **Cambios ante el proveedor (`cambioAnteProveedor`) no se ejecutan.** Reprogramar o cancelar con
   la aerolínea o el hotel, reembolsos y reclamos se derivan a la agencia, como dice
   [ADR-0039](ADR-0039-politica-de-derivacion-a-la-agencia.md).
5. **Siempre en nombre del viajero.** Cada llamada a `itinerary` lleva su identidad; una reserva o un
   viaje que no son suyos responden igual que uno inexistente ([ADR-0028](ADR-0028-autorizacion-comparticion-y-publicacion.md)).
   El asistente no guarda copias del itinerario: lo lee cuando lo necesita.
6. **Cero interfaces nuevas.** Todo lo anterior usa operaciones que `itinerary` ya exponía.

### Consecuencias

* **Bueno,** porque un malentendido nunca cambia el itinerario: el viajero ve el cambio exacto antes
  de que ocurra.
* **Bueno,** porque las correcciones del asistente heredan las reglas de la gestión manual (fijados,
  conflictos, versión), sin lógica duplicada.
* **Bueno,** porque no prometer reprogramaciones ante el proveedor es honesto con lo que el sistema
  puede hacer.
* **Malo,** porque corregir lleva dos turnos en lugar de uno.
* **Neutro,** porque el asistente depende de `itinerary-lectura`; si no responde, el asistente lo
  dice y no adivina.

### Confirmación

* Prueba de que sin `confirmacion` no se llama a `PUT /reservas/{id}`, y de que una confirmación
  vencida o de otra acción responde `409`.
* Prueba de que un `409` de `itinerary` lleva a una propuesta nueva con la versión releída.
* Pruebas de los problemas menores: confirmar y descartar una reserva por confirmar, y resolver un
  conflicto en los dos sentidos, siempre después de la confirmación.
* Prueba de que un pedido de cambio ante el proveedor no ejecuta nada y termina en derivación.
* Revisión del contrato: el asistente solo llama operaciones que ya existían en `itinerary.yaml`.

## Pros y contras de las opciones

### K1 — Solo consultas

* Bueno, porque es lo más simple y no cambia nada por error.
* Malo, porque deja afuera las «reprogramaciones» y los «problemas menores» que pide el enunciado:
  todo termina en la agencia.

### K2 — Cambio directo

* Bueno, porque resuelve en un turno.
* Malo, porque un malentendido modifica el itinerario sin que el viajero lo vea.

### K3 — Propuesta y confirmación

* Bueno, porque combina la utilidad de K2 con la seguridad de K1.
* Malo, porque agrega el estado de «acción pendiente» a la sesión.

## Más información

* Iteración: [iteración 5, paso 4, D38](../02-proceso-add/iteracion-5/paso-4-alternativas.md#d38--qué-resuelve-el-asistente-solo-y-cómo-rf-b1)
* Contrato: [`virtual-assistant.yaml`](../../contratos/openapi/virtual-assistant.yaml) (`AccionPropuesta`, `confirmacion`)
* Relacionados: [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md), [ADR-0028](ADR-0028-autorizacion-comparticion-y-publicacion.md), [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md), [ADR-0037](ADR-0037-interpretacion-de-intenciones-del-asistente.md), [ADR-0039](ADR-0039-politica-de-derivacion-a-la-agencia.md)
