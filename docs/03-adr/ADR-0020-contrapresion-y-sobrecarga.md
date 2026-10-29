---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Juan Emilio Pardo
consultados: Francisco Lozano, Jeremias Aguilar
informados: equipo completo
iteracion: 3
drivers: QA-04, QA-01, QA-02, CRN-03, AMB-02
---

# ADR-0020: Contrapresión extremo a extremo, colas con prioridad y degradación automática por niveles

## Contexto y planteo del problema

El escenario `QA-04` (ASR-2) modela el momento más crítico para Trotamundos: una disrupción climática
o huelga masiva triplica sin previo aviso las lecturas del panel (**`9.000 req/s`** sostenidas por
`30 minutos`) mientras multiplica por diez el ingreso de correos y avisos (**`450 eventos/s`**). El
sistema debe sostener **`p95 ≤ 1.500 ms`** en el panel y perder **cero actualizaciones**.

Sin contrapresión explícita, las colas en memoria crecen, los clientes vencen por *timeout* y
reintentan mientras los servidores siguen gastando CPU en peticiones abandonadas; y en el plano
asíncrono, cientos de miles de correos de viajes lejanos tapan por orden de llegada (*head-of-line
blocking*) las cancelaciones de vuelos que están embarcando ahora mismo.

## Drivers de decisión

* **QA-04** — absorber `9.000 req/s` y `450 eventos/s` durante `30 min` sin pérdida de
  actualizaciones y con `p95 ≤ 1.500 ms` en la lectura del panel.
* **QA-01** — preservar la propagación rápida de cambios urgentes aun con el plano de ingesta bajo
  ráfaga.
* **QA-02** — impedir que una saturación parcial arrastre por agotamiento de hilos al camino normal
  de lectura.
* **CRN-03 / AMB-02 ([ADR-0008](ADR-0008-alcance-disponibilidad.md))** — respetar la frontera declarada entre
  funciones críticas y funciones degradables.

## Opciones consideradas

* **T1** — Límite de tasa plano global (`HTTP 429`) sin distinción por tipo de operación.
* **T2** — Encolado ilimitado en memoria y en el *broker* en orden estricto de llegada (FIFO).
* **T3** — Degradación manual accionada por un operador ante alarma.
* **T4** — Presupuesto de plazo propagado (`X-Deadline-Ms`), colas acotadas, tres carriles de
  prioridad en el *broker* y máquina automática de tres modos operativos.

## Resultado de la decisión

Se adopta **T4**:

1. **Presupuesto de plazo propagado y colas sincrónicas acotadas.** `api-gateway` fija
   `X-Deadline-Ms` (`800 ms` normal, `1.500 ms` en disrupción); todo servicio descuenta el tiempo
   transcurrido y aborta llamadas si restan `< 20 ms`. Las colas de entrada por réplica se acotan a
   `50` peticiones en espera y el borde aplica cubeta de fichas por usuario (`60 req/min`, ráfaga
   `20`) devolviendo `429` con `Retry-After` aleatorio (`2–8 s`).
2. **Receptores livianos y tres carriles de prioridad en el *broker*.** Los receptores de *webhooks*
   validan firma, encolan en `≤ 15 ms` y responden `202 Accepted` (cero pérdida en el borde). Los
   eventos se despachan en tres carriles particionados por `usuario_id`: **`P1` Crítico**
   (disrupciones, proveedores y viajes `EnCurso` o `< 48 h`), **`P2` Estándar** (correo de viajes
   futuros) y **`P3` Diferible** (reconciliación, archivado y `event-pipeline`).
3. **Tres modos automáticos de degradación (`Normal` → `Pico elevado` → `Disrupción masiva`).** Ante
   superación sostenida de umbrales regionales de carga o latencia, el sistema apaga sin intervención
   humana primero publicaciones a redes sociales y sondeos fríos (`Pico elevado`), y luego pausa
   `event-pipeline` —reteniendo los eventos hasta `7 días` en el *broker*— y omite sugerencias
   difusas (`Disrupción masiva`), preservando toda la capacidad para el panel y los avisos críticos.

### Consecuencias

* **Bueno,** porque protege las funciones críticas exactamente en el orden comprometido por
  `ADR-0008` y garantiza **cero pérdida** al convertir sobrecarga en atraso controlado de `P2`/`P3`
  respaldado en disco en el *broker*.
* **Bueno,** porque el carril `P1` evita que un viajero en tránsito espere detrás de confirmaciones
  de hoteles para dentro de seis meses.
* **Malo,** porque durante una `Disrupción masiva` la frescura del plano analítico puede superar
  temporalmente la hora de `QA-09` hasta drenar los eventos retenidos, concesión explícitamente
  autorizada por `QA-04`.
* **Neutro,** porque exige histéresis en las reglas de salida de modo (`10–15 min` estables) para
  evitar oscilaciones rápidas entre modos.

### Confirmación

* Ejecución en el prototipo del escenario especificado para `QA-04` en
  [pruebas-de-carga-y-slos.md](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-2--qa-04-pico-súbito-por-disrupción-masiva),
  verificando `0` actualizaciones perdidas, `p95 ≤ 1.500 ms` y transición automática a modo
  `Disrupción masiva`.
* Prueba unitaria/integración de propagación de `X-Deadline-Ms`: una petición con `10 ms` restantes
  debe abortarse antes de consultar la base de datos.

## Pros y contras de las opciones

### T1 — Límite de tasa plano global

* Bueno, porque es trivial de configurar en el *gateway*.
* **Malo, porque rechaza por igual a un *webhook* irrepetible que a una acción secundaria.**

### T2 — Encolado ilimitado en orden FIFO

* Bueno, porque no descarta en la puerta.
* **Malo, porque colapsa por memoria/timeouts en cascada y bloquea eventos urgentes detrás de correo
  no urgente.**

### T3 — Degradación manual por guardia

* Bueno, porque un humano evalúa el contexto antes de apagar funciones.
* **Malo, porque el tiempo de reacción humano excede por completo un presupuesto mensual de 5
  minutos.**

### T4 — Contrapresión con plazo propagado, prioridad y modos automáticos

* Bueno, porque resuelve simultáneamente supervivencia del panel, prioridad semántica y cero pérdida.
* Malo, porque agrega tres carriles de consumo y lógica de cambio de modo que hay que ejercitar en
  pruebas de carga.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D20](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d20--contrapresión-y-comportamiento-ante-sobrecarga-qa-04)
* Detalle de modos y carriles: [iteración 3, sección 5.3](../02-proceso-add/iteracion-3/README.md#53-contrapresión-colas-con-prioridad-y-niveles-de-degradación-d20)
* Relacionados: [ADR-0001](ADR-0001-estilo-arquitectonico.md), [ADR-0008](ADR-0008-alcance-disponibilidad.md), [ADR-0021](ADR-0021-estrategia-autoescalado.md)
