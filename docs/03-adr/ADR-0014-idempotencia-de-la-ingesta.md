---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: CRN-12, RF-02, RF-05, RF-06, RF-12, QA-11
---

# ADR-0014: Idempotencia por bandeja de entrada por mensaje y fusión determinista

## Contexto y planteo del problema

El mismo mensaje puede llegar dos veces, y la misma reserva puede describirse en dos mensajes
distintos. Las causas son estructurales, no accidentales:

* El *broker* de [ADR-0001](ADR-0001-estilo-arquitectonico.md) entrega **al menos una vez**.
* El *push* y la reconciliación de [ADR-0004](ADR-0004-obtencion-de-correo.md) se solapan por
  diseño.
* Los proveedores reintentan sus notificaciones.
* El usuario puede tocar dos veces un botón.

Además existe un caso que confunde a las soluciones ingenuas: un estado que **vuelve** a un valor
anterior (un vuelo pasa de las 10:00 a las 10:30 y vuelve a las 10:00). Ese tercer cambio es real
y no un duplicado.

## Drivers de decisión

* **CRN-12** — la ingesta debe ser idempotente.
* **QA-11** — ningún dato incorrecto silencioso (un horario «revertido» descartado lo sería).
* **RF-02, RF-05** — dos canales de ingesta que se solapan.
* **RF-06, RF-12** — comandos del usuario (alta manual, caso de soporte) que pueden repetirse.

## Opciones consideradas

* **N1** — Clave de idempotencia por mensaje (bandeja de entrada).
* **N2** — Registro de huellas del contenido procesado.
* **N3** — Operaciones naturalmente idempotentes (fusión determinista).
* **N1 + N3.**

Comparación completa: [iteración 2, paso 4, D14](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d14--idempotencia-de-la-ingesta-crn-12).

## Resultado de la decisión

Se adopta **N1 + N3**. N1 corta la duplicación **donde nace**; N3 es la **garantía**: aplicar dos
veces la misma observación da el mismo estado, porque la observación se identifica por
`(fuente, idDeFuente)` y se ordena por la versión de la fuente.

| Capa | Mecanismo | Clave | Dónde |
|---|---|---|---|
| Ingreso del mensaje | Bandeja de entrada | `(buzón, idDeMensaje)` | `mail-ingest` |
| Consumo de cada evento | Bandeja de entrada | `(consumidor, idDeEvento)` | Todo elemento que consume eventos |
| Observación | Unicidad | `(reserva, fuente, idDeFuente)` | `itinerary` |
| Comandos del usuario | Cabecera `Idempotency-Key` | Clave enviada por el cliente | `POST /reservas`, `POST /casos` |
| Publicación | *Outbox* transaccional | `idDeEvento` | Todo elemento que publica |

La retención de la bandeja de entrada debe superar el intervalo máximo de reconciliación de
ADR-0004 (valor inicial: **14 días**, a calibrar). Las notificaciones tienen su propia bandeja de
entrada, de modo que un evento duplicado no produce dos avisos.

### Consecuencias

* **Bueno,** porque cubre los tres casos: duplicado de entrega, duplicado de contenido y reversión
  de estado.
* **Bueno,** porque evita extraer dos veces el mismo mensaje, que es la operación más cara de la
  ingesta.
* **Malo,** porque las bandejas de entrada ocupan espacio y necesitan retención acotada.
* **Malo,** porque exige una fusión determinista y bien probada (la de
  [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md)).
* **Malo,** porque **la bandeja de entrada solo es correcta si todos los mensajes de un usuario
  pasan por la misma partición.** Con el activo-activo de ADR-0002, dos regiones podrían procesar
  a la vez dos copias del mismo mensaje. Esto generó el riesgo **R-4**, que se cerró junto con R-1
  en la iteración 3 con la región primaria por usuario
  ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md)).

### Confirmación

* **Prueba de entrega duplicada:** publicar dos veces el mismo `MensajeDeViajeRecibido` produce una
  sola extracción y una sola observación.
* **Prueba de reversión:** la secuencia 10:00 → 10:30 → 10:00 deja la reserva a las 10:00 y emite
  dos avisos de cambio.
* **Prueba de comando:** dos `POST /reservas` con la misma `Idempotency-Key` devuelven la misma
  respuesta y crean una sola reserva.
* **Revisión de esquema:** las restricciones únicas de la tabla de arriba existen
  ([ADR-0012](ADR-0012-persistencia-del-plano-operacional.md)).

## Pros y contras de las opciones

### N1 — Bandeja de entrada por mensaje

* Bueno, porque corta el duplicado de entrega donde nace y es simple.
* Malo, porque no ve el duplicado de contenido (la misma reserva en otro mensaje).

### N2 — Huellas de contenido

* Bueno, porque detecta duplicados de entrega y de contenido.
* **Malo, porque no distingue «ya procesé este estado» de «el estado volvió a ser este»:**
  descartaría un regreso legítimo a un horario anterior, un error silencioso que QA-11 prohíbe.

### N3 — Fusión determinista

* Bueno, porque garantiza el resultado sin importar cuántas veces ni en qué orden llegue una
  observación.
* Malo, porque sola obliga a extraer y fusionar duplicados que podrían haberse evitado.

### N1 + N3

* Bueno, porque combina la eficiencia de N1 y la garantía de N3.
* Malo, porque suma el costo de ambas.

## Más información

* Drivers: [CRN-12](../01-analisis-inicial/06-concerns-arquitectonicos.md),
  [QA-11](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-11--formato-de-correo-desconocido)
* Análisis comparativo: [iteración 2, paso 4, D14](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d14--idempotencia-de-la-ingesta-crn-12)
* Riesgo R-4: [iteración 2, paso 7](../02-proceso-add/iteracion-2/paso-7-analisis.md#riesgos-residuales)
* Relacionados: [ADR-0004](ADR-0004-obtencion-de-correo.md), [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md), [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
