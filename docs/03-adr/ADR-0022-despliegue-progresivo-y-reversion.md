---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Jeremias Aguilar
consultados: Francisco Lozano, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: QA-07, CRN-04, QA-05, CRN-03, CON-04
---

# ADR-0022: Entrega progresiva canaria por región con reversión automática y migraciones *expand/contract*

## Contexto y planteo del problema

Con un presupuesto mensual total de disponibilidad de **`5,0 minutos`** ([ADR-0008](ADR-0008-alcance-disponibilidad.md)),
no existen ventanas de mantenimiento programadas (`CRN-04`). El escenario `QA-07` exige desplegar
versiones nuevas en cualquier horario productivo con **`0 segundos` de inactividad**, afectando a lo
sumo al **`5 %` del tráfico** si la versión tiene un defecto y ejecutando la **reversión automática
en `≤ 2 minutos`**.

Sin embargo, redirigir el tráfico de vuelta a la versión anterior en menos de dos minutos solo es
posible si la base de datos y los eventos publicados siguen siendo compatibles con ambas versiones en
simultáneo: una migración destructiva de esquema convierte cualquier reversión rápida en una caída
total.

## Drivers de decisión

* **QA-07** — despliegue en línea con inactividad = `0 s`, radio de impacto `≤ 5 %` y reversión
  automática `≤ 2 min`.
* **CRN-04** — despliegue continuo sin ventanas de mantenimiento.
* **CRN-03 / AMB-02 ([ADR-0008](ADR-0008-alcance-disponibilidad.md))** — el plano de aplicación dispone de apenas `2,0 min/mes` de presupuesto de error.
* **CON-04** — verificación automática de compatibilidad hacia atrás en integración continua.

## Opciones consideradas

* **V1** — Actualización rotativa simple (*rolling upgrade*) simultánea en las tres regiones.
* **V2** — Despliegue azul-verde (*blue-green*) completo por servicio.
* **V3** — Despliegue canario con evaluación y reversión manuales.
* **V4** — Entrega progresiva canaria secuencial por región gobernada por SLIs (`≤ 75 s`), combinada
  con migraciones *expand/contract* e interruptores de funcionalidad (*feature toggles*).

## Resultado de la decisión

Se adopta **V4**:

1. **Progresión secuencial región por región.** Todo despliegue comienza en una única región
   (priorizando la que está en horario valle), espera `15 minutos` de estabilidad al `100 %` y recién
   entonces avanza a la segunda y luego a la tercera.
2. **Rampa canaria con reversión automática en `≤ 75 s`.** Dentro de cada región, el tráfico se
   asigna en tres escalones (`5 %` durante `5 min` → `25 %` durante `10 min` → `100 %`). El primer
   escalón expone apenas al `5 %` regional (`~1,7 %` global). Un controlador evalúa cada `30 s` la
   tasa de `5xx`, el `p95` y los fallos de consumo del canario frente a la flota estable; dos
   ventanas degradadas consecutivas (`60 s`) retiran el peso del canario a `0 %` en `≤ 15 s`
   (**total `≤ 75 s < 2 min`**). El reemplazo de instancias usa drenaje ordenado (`SIGTERM` + cierre
   de conexiones en vuelo) logrando **`0 s` de corte**.
3. **Protocolo obligatorio *expand/contract* para datos y eventos.** Se prohíben cambios destructivos
   de esquema en un paso (`DROP`/`RENAME` de columna, endurecimiento de nulabilidad o eliminación de
   campos en eventos). Todo cambio incompatible se divide en al menos dos despliegues: primero
   *expandir* de forma aditiva y tolerante, y recién cuando quedan cero réplicas de la versión vieja
   en las tres regiones, *contraer*.

### Consecuencias

* **Bueno,** porque un canario fallido completo consume como máximo **`~1,25 segundos` equivalentes**
  del presupuesto global (`75 s × 5 % × 1/3`), protegiendo holgadamente los `2,0 min/mes` del plano
  de aplicación.
* **Bueno,** porque garantiza que la reversión por tráfico siempre encuentre un esquema de datos
  válido para la versión anterior.
* **Malo,** porque un cambio que requiera eliminar o renombrar una columna exige dos ciclos de
  entrega en lugar de uno, disciplina necesaria a cambio de cero inactividad.

### Confirmación

* **Inyección de falla en despliegue (`QA-07`):** publicar en preproducción un canario que devuelva
  `500` en el `10 %` de sus respuestas y verificar que el tráfico afectado nunca supere el `5 %` y que
  el controlador revierta el peso a `0 %` en **`≤ 120 s`** con `0` peticiones caídas durante el
  drenaje.
* **Regla estática en CI:** rechazo automático de scripts SQL con sentencias destructivas directas o
  cambios incompatibles en esquemas OpenAPI/AsyncAPI sin fase previa de expansión.

## Pros y contras de las opciones

### V1 — Actualización rotativa simultánea en las tres regiones

* Bueno, porque es rápida y consume pocos recursos extra (`N + 1`).
* **Malo, porque propaga un defecto lógico al 100 % de las regiones antes de frenar.**

### V2 — Azul-verde completo

* Bueno, porque conmuta y revierte rápido.
* **Malo, porque duplica transitoriamente el costo de cómputo (`2N`) y expone al 100 % del tráfico
  regional al hacer el corte (incumple `≤ 5 %`).**

### V3 — Canario con promoción manual

* Bueno, porque acota el radio de impacto al `5 %`.
* **Malo, porque depender de un humano para revertir no garantiza los `≤ 2 minutos` de `QA-07`.**

### V4 — Canario secuencial automático + *expand/contract*

* Bueno, porque satisface las tres métricas de `QA-07` con sobrecosto mínimo de recursos (`+5 %`).
* Malo, porque alarga el tiempo total de propagación global de un *release* (`~60–90 min` entre las 3
  regiones), lo cual se compensa con interruptores de funcionalidad cuando se requiere activación
  inmediata.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D22](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d22--despliegue-progresivo-reversión-automática-y-compatibilidad-de-esquemas-qa-07-crn-04)
* Relacionados: [ADR-0008](ADR-0008-alcance-disponibilidad.md), [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0025](ADR-0025-observabilidad-sli-slo-presupuesto-error.md)
