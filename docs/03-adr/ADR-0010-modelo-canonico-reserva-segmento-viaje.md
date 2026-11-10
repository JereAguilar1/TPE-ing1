---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: RF-03, RF-06, RF-07, CRN-11, CRN-12, QA-04, QA-15, CON-09
---

# ADR-0010: Modelo canónico con dos agregados de límites explícitos, `Reserva` y `Viaje`

## Contexto y planteo del problema

Tres fuentes escriben sobre las mismas reservas, en concurrencia y con ritmos distintos: el correo,
el proveedor y el propio usuario. El sistema promete ser el «único punto de verdad» (MN-1). Antes
de decidir cómo se persiste (ADR-0012) o cómo se fusiona (ADR-0013) hay que decidir **qué es una
unidad de consistencia**.

Hay dos preguntas que suelen mezclarse y que en este dominio tienen dinámicas distintas:

* *¿Qué es esta reserva y qué valores tiene?* Es una pregunta de identidad y de fusión, y no
  depende del viaje.
* *¿A qué viaje pertenece?* Es una pregunta de agrupación, y su respuesta cambia con el tiempo
  (el usuario mueve un hotel a otro viaje, llega una reserva que extiende un viaje existente).

Durante un pico de disrupción (QA-04), muchos proveedores notifican cambios a la vez. Si la unidad
de escritura es grande, esas notificaciones compiten entre sí y con las acciones del usuario.

## Drivers de decisión

* **RF-03, RF-06, RF-07** — extraer reservas, gestionarlas manualmente y agruparlas por viaje.
* **CRN-11** — resolver conflictos entre fuentes que describen la misma reserva.
* **CRN-12** — la ingesta debe ser idempotente.
* **QA-04** — absorber el pico sin que las escrituras se serialicen innecesariamente.
* **QA-15** — agregar un tipo de segmento sin tocar el modelo.
* **CON-09** — el equipo es de cuatro personas; el modelo tiene que ser razonable de construir.

## Opciones consideradas

* **J1** — Modelo rico con un único agregado `Viaje` que contiene reservas y segmentos.
* **J2** — Modelo anémico con servicios (entidades de datos y *transaction scripts*).
* **J3** — Agregados con límites transaccionales explícitos: `Reserva` y `Viaje`.

La comparación completa está en el
[paso 4 de la iteración 2, D10](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d10--modelo-del-dominio-y-sus-límites).

## Resultado de la decisión

Se adopta **J3: dos agregados, `Reserva` y `Viaje`**, con estos límites:

| Agregado | Raíz | Contiene | Invariantes principales |
|---|---|---|---|
| `Reserva` | `Reserva` | `Identificador`, `Observación` (solo se agrega), `Segmento`, `Conflicto` | Al menos un segmento. Los identificadores son únicos por usuario. **La vista consolidada es una función determinista de las observaciones y de los campos fijados** |
| `Viaje` | `Viaje` | La **membresía** (referencias a reservas por id) | Una reserva pertenece a lo sumo a un viaje activo. Una asignación fijada por el usuario no la mueve ningún proceso automático |

Tres precisiones forman parte de la decisión:

1. **`Observación` es lo que una fuente afirma sobre una reserva en un momento.** Las
   observaciones solo se agregan; la vista consolidada se deriva de ellas.
2. **`Reserva` y `Viaje` no se referencian por objeto, solo por id**, y se coordinan por eventos
   internos. Ninguna transacción abarca los dos agregados.
3. **La agrupación razona por rol y lugar, nunca por tipo de segmento** (el rol lo declara el
   descriptor de [ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md)). Por eso una regla
   de agrupación no necesita conocer el tren.

El modelo completo (diagrama de clases, estados de la reserva y ciclo de vida del viaje) está en
la [iteración 2, §5.1 y §5.2](../02-proceso-add/iteracion-2/README.md#52-el-modelo-canónico).

### Consecuencias

* **Bueno,** porque las reglas críticas (identidad, precedencia, idempotencia) tienen un solo
  hogar: el agregado `Reserva`.
* **Bueno,** porque cada actualización de un proveedor toca una reserva, no un viaje entero: el
  cambio de puerta de un vuelo no compite con el usuario que mueve un hotel (QA-04).
* **Bueno,** porque la consolidación determinista hace que aplicar las mismas observaciones en
  cualquier orden dé el mismo resultado, lo que simplifica CRN-12
  ([ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md)) y deja abiertos los dos caminos de R-1.
* **Bueno,** porque las observaciones que no se modifican son, sin trabajo adicional, un
  historial auditable de cada valor y de su fuente.
* **Malo,** porque introduce **consistencia eventual entre `Reserva` y `Viaje`**: cuando llega una
  reserva, el viaje se actualiza después, por evento.
* **Malo,** porque complica la lectura inmediata tras una escritura. Se mitiga devolviendo el
  estado resultante en la respuesta del comando; la caché se trata en la iteración 3
  ([ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md)).
* **Neutro,** porque concentra muchas responsabilidades en `itinerary` (riesgo R-5), que se acota
  con los dos modos de despliegue `itinerary-escritura` e `itinerary-lectura`
  ([ADR-0021](ADR-0021-estrategia-autoescalado.md)).

### Confirmación

* **Pruebas basadas en propiedades sobre `Reserva`:** para cualquier permutación de un conjunto de
  observaciones, el estado consolidado es el mismo
  ([ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md)).
* **Verificación de dependencias** en la construcción del prototipo: el módulo `reservas` no
  importa a `viajes` ni a la inversa
  ([vista de módulos N2](../04-vistas/vista-modulos-nivel-2.md)).
* **Revisión de esquema:** ninguna transacción del prototipo escribe en `reserva` y `viaje` a la
  vez.

## Pros y contras de las opciones

### J1 — Agregado único `Viaje`

* Bueno, porque es la forma intuitiva: «un viaje tiene reservas, que tienen segmentos».
* Bueno, porque la lectura de un viaje completo es un solo acceso.
* **Malo, porque genera contención:** cada actualización de proveedor se serializa contra todo el
  viaje, justo en el pico de QA-04.
* Malo, porque mezcla identidad y agrupación: una reserva que cambia de viaje cambia de agregado.
* Malo, porque una unidad de escritura grande multiplica la probabilidad de conflicto entre
  regiones (R-1).

### J2 — Modelo anémico con servicios

* Bueno, porque es lo más simple de escribir (CON-09).
* **Malo, porque dispersa las invariantes:** la deduplicación, la precedencia y la idempotencia
  quedan repartidas entre servicios, y dos caminos de código terminan aplicándolas distinto.
* Malo, porque no hay una unidad de consistencia clara que replicar o fusionar entre regiones.

### J3 — Agregados `Reserva` y `Viaje`

* Bueno, porque atiende a la vez CRN-11, CRN-12, QA-04, QA-15 y R-1.
* Malo, porque exige disciplina de diseño y acepta consistencia eventual entre agregados.

## Más información

* Drivers: [RF-03, RF-06, RF-07](../01-analisis-inicial/03-requisitos-funcionales.md),
  [QA-04](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-04--pico-de-carga-por-disrupción-masiva),
  [QA-15](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte),
  [CRN-11 y CRN-12](../01-analisis-inicial/06-concerns-arquitectonicos.md)
* Análisis comparativo: [iteración 2, paso 4, D10](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d10--modelo-del-dominio-y-sus-límites)
* Validación contra los cinco tipos de segmento: [iteración 2, paso 7](../02-proceso-add/iteracion-2/paso-7-analisis.md#validación-del-modelo-canónico-contra-los-cinco-tipos-de-segmento)
* Vistas afectadas: [módulos N2](../04-vistas/vista-modulos-nivel-2.md), [secuencias de los casos primarios](../04-vistas/secuencias-casos-primarios.md)
* Relacionados: [ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md), [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md), [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
