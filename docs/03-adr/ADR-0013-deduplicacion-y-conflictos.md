---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: CRN-11, RF-03, RF-05, RF-06, QA-11
---

# ADR-0013: Identidad por identificadores múltiples, precedencia por fuente y coincidencia difusa solo como sugerencia

## Contexto y planteo del problema

La misma reserva real puede llegar por el correo de la aerolínea, por el de la agencia en línea,
por el intercambio del proveedor y por la carga manual del usuario. Llega con códigos distintos,
formatos distintos y, a veces, valores distintos. Hay **dos problemas diferentes**:

* **Identidad:** ¿estas dos observaciones son la misma reserva?
* **Conflicto:** cuando dos fuentes no coinciden, ¿qué valor gana?

Una fusión errónea es especialmente grave: produce un dato incorrecto que el usuario no sabe que
es incorrecto, que es exactamente lo que QA-11 prohíbe.

## Drivers de decisión

* **CRN-11** — resolver conflictos entre fuentes que describen la misma reserva.
* **QA-11** — 0 % de datos incorrectos insertados silenciosamente.
* **RF-06** — la gestión manual del usuario convive con las fuentes automáticas.
* **RF-03, RF-05** — las reservas llegan por correo y por proveedor.

## Opciones consideradas

* **M1** — Clave natural por código de confirmación.
* **M2** — Coincidencia difusa por atributos (fechas, lugares, operador).
* **M3** — Precedencia por fuente, con intervención del usuario.
* **M1 + M3, con M2 solo como sugerencia.**

Comparación completa: [iteración 2, paso 4, D13](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d13--deduplicación-y-resolución-de-conflictos-entre-fuentes-crn-11).

## Resultado de la decisión

Se adopta **M1 + M3, con M2 solo como sugerencia**.

**Identidad (M1 corregida).** Una reserva no tiene *un* código sino un **conjunto de
identificadores** `(emisor, código)`: un vuelo comprado por una agencia en línea tiene el
localizador de la aerolínea y el número de orden de la agencia. Si una observación coincide con
**cualquiera** de los identificadores conocidos, es la misma reserva. Si una observación liga dos
reservas que el sistema creía distintas, se unifican (la más antigua conserva el id), salvo que
alguna sea manual, en cuyo caso se pide confirmación.

**Conflictos (M3).**

| Situación | Regla |
|---|---|
| Dos versiones de la misma fuente | Gana la de mayor versión **de la fuente** (fecha de emisión), no la que llegó último |
| Proveedor frente a correo | El proveedor gana en los hechos operativos (horarios, estado, puertas, cancelación); el correo completa lo que el proveedor no informa |
| Reserva solo manual | El usuario es la autoridad |
| Edición manual frente a fuente automática | La edición **fija** el campo. Si una fuente trae después un valor distinto y nuevo, se abre un `Conflicto` y el usuario elige |
| Cancelación del proveedor | Prevalece siempre. El usuario puede reactivarla manualmente, lo que fija el estado |
| Sin identificador coincidente | El sistema **nunca** fusiona por su cuenta: crea la reserva y, si hay candidatas, sugiere |

**Coincidencia difusa (M2) solo como sugerencia.** Cuando no hay identificador común, el sistema
puede proponer «¿es la misma reserva?», y la decisión es del usuario.

### Consecuencias

* **Bueno,** porque la fusión es exacta y explicable: cada valor consolidado tiene una regla y una
  fuente.
* **Bueno,** porque el sistema nunca fusiona por parecido, lo que protege QA-11.
* **Bueno,** porque la edición del usuario es una fuente más, con reglas explícitas (RF-06).
* **Malo,** porque el usuario tiene que intervenir cuando las fuentes discrepan sobre un campo que
  él fijó. La hipótesis es que son pocos casos, y es una hipótesis que hay que medir.
* **Malo,** porque las reservas sin identificador común quedan duplicadas hasta que el usuario
  acepte la sugerencia.

### Confirmación

* **Pruebas de la fusión:** casos de ejemplo para cada fila de la tabla de reglas, más pruebas
  basadas en propiedades ([ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md)).
* **Prueba negativa:** dos habitaciones del mismo hotel para la misma noche, sin código común,
  **no** se fusionan.
* **Métrica del prototipo:** conflictos abiertos por usuario y por semana. Si fueran muchos, la
  regla de fijado es lo primero a revisar.

## Pros y contras de las opciones

### M1 — Clave natural por código de confirmación

* Bueno, porque es exacta cuando hay código y no fusiona de más.
* Malo, porque falla si no hay código o hay varios, y las cargas manuales suelen no tenerlo.

### M2 — Coincidencia difusa

* Bueno, porque cubre el caso sin código.
* **Malo, porque produce falsos positivos silenciosos:** un viaje de ida y vuelta por la misma ruta
  o dos pasajes iguales para personas distintas se fusionarían sin avisar.

### M3 — Precedencia por fuente con intervención del usuario

* Bueno, porque es determinista y explicable.
* Malo, porque agrega fricción cuando las fuentes discrepan, y por sí sola no resuelve la
  identidad.

### M1 + M3, con M2 como sugerencia

* Bueno, porque resuelve por separado identidad y conflicto, sin fusiones silenciosas.
* Malo, porque la fricción se acota pero no desaparece.

## Más información

* Drivers: [QA-11](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-11--formato-de-correo-desconocido),
  [CRN-11](../01-analisis-inicial/06-concerns-arquitectonicos.md),
  [RF-06](../01-analisis-inicial/03-requisitos-funcionales.md)
* Análisis comparativo: [iteración 2, paso 4, D13](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d13--deduplicación-y-resolución-de-conflictos-entre-fuentes-crn-11)
* Recorridos: [UC-1, UC-2 y UC-4](../04-vistas/secuencias-casos-primarios.md)
* Relacionados: [ADR-0010](ADR-0010-modelo-canonico-reserva-segmento-viaje.md), [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md) (fusión convergente ante la caída de una región)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
