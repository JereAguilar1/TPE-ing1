---
estado: aceptado
fecha: 2026-10-24
decisores: Ivo Iriarte, Jeremias Aguilar
consultados: Francisco Lozano
informados: equipo completo
iteracion: 1
drivers: QA-02, QA-03, QA-17, RF-09, CON-09, AMB-01, AMB-05
---

# ADR-0005: Un *backend for frontend* por tipo de cliente

## Contexto y planteo del problema

El sistema tiene dos clientes con presupuestos de rendimiento distintos, y el refinado los dejó
explícitos:

| Cliente | Objetivo | Condiciones |
|---|---|---|
| Web | p95 ≤ 800 ms para la carga del panel (AMB-01) | Carga pico de 3.000 req/s |
| Móvil | *First Contentful Paint* ≤ 1,4 s en el p75 (AMB-05) | 4G: RTT 150 ms, 1,6 Mbps; dispositivo de gama media |

Los dos presupuestos están en conflicto si se los sirve con un único contrato. La respuesta que
hace eficiente a la web —el panel completo en una sola ida y vuelta— es demasiado grande para
1,6 Mbps: a 1,6 Mbps, cada 200 KB de respuesta consume **un segundo entero** del presupuesto de
1,4 s. Y la respuesta mínima que sirve al móvil obliga a la web a varias peticiones encadenadas,
cada una pagando el RTT.

Hay un tercer driver: QA-17 pide aprovechar el GPS del dispositivo para destacar el segmento
pertinente del viaje, lo cual es una necesidad del cliente móvil que la web no tiene.

## Drivers de decisión

* **QA-02** — p95 ≤ 800 ms para la carga del panel web, con 70 ms asignados a la composición de la
  respuesta en el [presupuesto de latencia](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-latencia-web-800-ms-p95).
* **QA-03** — FCP ≤ 1,4 s en el p75 sobre 4G y dispositivo de gama media.
* **QA-17** — uso del GPS para destacar el segmento pertinente, con degradación útil si el permiso
  está denegado.
* **RF-09** — visualizar el panel unificado desde web y desde móvil.
* **CON-09** — cuatro personas con dedicación parcial.

## Opciones consideradas

* **F1** — Una sola API genérica para los dos clientes.
* **F2** — Un *backend for frontend* (BFF) por tipo de cliente.
* **F3** — Un BFF más GraphQL.
* **F4** — Una PWA única para web y móvil.

## Resultado de la decisión

Se adopta **F2: un BFF por tipo de cliente**, con dos elementos — `bff-web` y `bff-mobile` — cada
uno con su propio contrato:

| Elemento | Contrato | Estrategia |
|---|---|---|
| `bff-web` | `GET /panel`, `GET /viajes/{id}` | Compone el panel completo en **una** ida y vuelta, para no pagar el RTT varias veces |
| `bff-mobile` | `GET /panel/resumen`, `GET /viajes/{id}` | Devuelve primero un resumen mínimo (los viajes próximos, que es lo que pinta el primer contenido) y difiere los detalles a peticiones posteriores |

Dos precisiones que son parte de la decisión:

* **Los BFF no contienen lógica de dominio.** Solo componen y adaptan respuestas de `itinerary` y
  `preferences`. Si un BFF empieza a tomar decisiones de negocio, la frontera está mal trazada.
* **La aplicación móvil se construye con un marco multiplataforma y módulos nativos** para GPS y
  notificaciones, en lugar de dos aplicaciones nativas separadas. Es una concesión explícita a
  CON-09.

### Consecuencias

* **Bueno,** porque cada cliente obtiene exactamente la forma de respuesta que su presupuesto
  necesita, y los dos presupuestos pueden cerrar a la vez.
* **Bueno,** porque los clientes evolucionan de forma independiente: un cambio en la pantalla web
  no obliga a publicar una versión nueva de la aplicación móvil.
* **Bueno,** porque la carga diferida del cliente móvil reduce el tráfico contra `itinerary`: la
  mayoría de las sesiones solo consultan el viaje próximo.
* **Malo,** porque hay dos contratos que mantener en lugar de uno, y existe el riesgo de que
  dupliquen lógica de composición. Mitigación: la lógica de dominio queda en `itinerary`, no en los
  BFF.
* **Malo,** porque el marco multiplataforma es una apuesta: si el presupuesto de 1,4 s de QA-03 no
  cierra en las mediciones reales, habrá que reconsiderarlo. **Esta decisión queda marcada como
  revisable**, y la medición es parte de la confirmación.
* **Neutro,** porque agrega un salto de red en el camino de lectura. El presupuesto de latencia ya
  lo contabilizó: 70 ms para el BFF.

### Confirmación

* **Medición de QA-02:** p95 de `GET /panel` medido en el borde, bajo carga de 3.000 req/s. Debe
  ser ≤ 800 ms, y el tramo atribuible al BFF ≤ 70 ms.
* **Medición de QA-03:** FCP de la aplicación móvil en arranque en frío, en red 4G emulada
  (RTT 150 ms, 1,6 Mbps) sobre dispositivo de gama media. p75 ≤ 1,4 s.
* **Verificación de la frontera:** revisión de código de los BFF para confirmar que no contienen
  reglas de dominio (deduplicación, agrupación en viajes, ciclo de vida). Esas reglas viven en
  `itinerary`.
* **Prueba de degradación de QA-17:** la aplicación debe mostrar el itinerario completo con el
  permiso de ubicación denegado.

## Pros y contras de las opciones

### F1 — Una sola API genérica

* Bueno, porque es una sola API que diseñar, documentar y versionar: lo mejor para CON-09.
* Bueno, porque no hay riesgo de que dos contratos divergan.
* **Malo, porque los presupuestos de QA-02 y QA-03 están en conflicto directo.** Una respuesta de
  200 KB consume un segundo entero del presupuesto móvil a 1,6 Mbps; una respuesta mínima obliga a
  la web a encadenar peticiones y pagar el RTT varias veces.
* Malo, porque todo cambio afecta a los dos clientes a la vez, de modo que el ritmo de evolución
  queda atado al más lento.

### F2 — Un BFF por tipo de cliente

* Bueno, porque permite que los dos presupuestos de rendimiento cierren simultáneamente.
* Bueno, porque desacopla el ritmo de evolución de los clientes.
* Malo, porque son dos contratos que mantener.
* Malo, porque introduce el riesgo de duplicar lógica de composición si la disciplina se relaja.

### F3 — Un BFF más GraphQL

* Bueno, porque cada cliente pide exactamente los campos que necesita: resolvería el conflicto de
  presupuestos de forma elegante y con un solo esquema.
* Bueno, porque evita el versionado de múltiples contratos.
* **Malo, porque el control de consultas costosas (profundidad, complejidad, N+1) es trabajo
  adicional** que CON-09 no tiene disponible en paralelo con todo lo demás.
* Malo, porque el cacheo en el borde es más difícil que con peticiones sobre rutas estables, y el
  presupuesto de QA-02 depende de la caché.
* Queda registrado como **la alternativa a reconsiderar** si los dos BFF empiezan a divergir
  demasiado.

### F4 — PWA única para web y móvil

* Bueno, porque es un solo cliente que construir y mantener: lo mejor para CON-09.
* **Malo, porque QA-17 pide explícitamente «una interfaz rica aprovechando capacidades nativas como
  GPS en móviles»**, y el acceso a ubicación en segundo plano y a notificaciones es más limitado y
  más dependiente de la plataforma.
* Malo, porque es más difícil sostener el presupuesto de 1,4 s con el arranque en frío de una
  aplicación web.

## Más información

* Drivers: [QA-02](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-02--tiempo-de-respuesta-del-panel-web),
  [QA-03](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-03--primer-despliegue-de-contenido-en-móvil),
  [QA-17](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-17--contexto-de-ubicación-en-el-dispositivo-móvil)
* Análisis comparativo: [iteración 1, paso 4, D5](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d5--capa-de-clientes)
* Presupuesto: [latencia web](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-latencia-web-800-ms-p95)
* Relacionados: [ADR-0003](ADR-0003-separacion-planos.md) provee la proyección de lectura que hace cerrar el presupuesto
