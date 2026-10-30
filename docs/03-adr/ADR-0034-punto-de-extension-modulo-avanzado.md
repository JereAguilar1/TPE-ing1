---
estado: aceptado
fecha: 2026-10-29
decisores: Juan Emilio Pardo, Jeremias Aguilar, Francisco Lozano, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 4
drivers: CON-06, CON-05, CON-A4, QA-04, QA-15
---

# ADR-0034: Integración del módulo avanzado de la 2da entrega como elemento autónomo nº 14 sobre eventos y contratos existentes, y recorte del prototipo por ASRs

## Contexto y planteo del problema

El enunciado del TPE (§3 y §4) establece que en la segunda entrega el equipo deberá incorporar **una**
de dos capacidades avanzadas —**Opción A:** sistema de recomendación proactivo con enfoque
*human-in-the-loop*, u **Opción B:** asistente virtual conversacional de primer nivel con escalamiento
de casos complejos— y construir un prototipo ejecutable acotado y trazable a las decisiones tomadas.

De ello derivan dos restricciones que la cuarta iteración debe dejar resueltas antes de cerrar la
primera entrega:
1. **`CON-06` (criterio de salida 4):** demostrar en papel que **tanto la Opción A como la Opción B**
   se alojan sobre la arquitectura actual **sin modificar servicios de dominio existentes ni requerir
   interfaces nuevas en ellos**, respetando además el tope de `< 15` elementos operacionales
   (`CON-A4`).
2. **`CON-05`:** fijar un criterio objetivo y no arbitrario para acotar qué parte de la arquitectura se
   implementa en código real en el prototipo y qué parte se representa con dobles contractuales.

## Drivers de decisión

* **CON-06** — verificar que la arquitectura aloja sin retrabajo estructural tanto la Opción A como la
  Opción B de la 2da entrega.
* **CON-05 / CON-09** — acotar racionalmente el alcance del prototipo ejecutable a la capacidad real de
  cuatro integrantes con dedicación parcial.
* **CON-A4 ([ADR-0001](ADR-0001-estilo-arquitectonico.md))** — mantener la cantidad total de elementos del plano operacional estrictamente por debajo de `15` (`13 + 1 = 14 < 15`).
* **QA-04** — impedir que el cómputo de recomendación o de modelos conversacionales degrade el camino
  crítico de ingesta y lectura durante una disrupción masiva.

## Opciones consideradas

* **J1** — Incrustar la lógica del recomendador o del asistente conversacional dentro del servicio
  núcleo `itinerary`.
* **J2** — Diseñar y construir de antemano un *framework* genérico de orquestación de agentes e IA
  antes de elegir entre Opción A y Opción B.
* **J3** — Alojar el módulo elegido como el elemento autónomo nº `14` del plano operacional, conectado
  exclusivamente como consumidor de los eventos ya publicados en el *broker* y cliente de las APIs REST
  existentes (`itinerary`, `support-liaison`, `analytics-store`), exponiendo sus operaciones propias a
  través de `bff-web`/`bff-mobile`, y recortar el prototipo como una tajada vertical guiada por los
  **5 ASRs**.

## Resultado de la decisión

Se adopta **J3**:

1. **Costura arquitectónica invariante para Opción A y Opción B (`CON-06` verificado).** Cualquiera de
   las dos opciones que se seleccione al iniciar la 2da entrega se instancia como **un único servicio
   autónomo nuevo** (elemento operacional nº `14`, cumpliendo `14 < 15`), gobernado por las mismas
   siete reglas de dependencia de la [vista de módulos de nivel 1](../04-vistas/vista-modulos-nivel-1.md):
   * **Si se elige Opción A (`recommendation-engine`):** se suscribe en el *broker* como grupo
     consumidor nuevo a `ViajeArmado`, `ReservaActualizada`, `ViajeCompletado` y
     `PreferenciasActualizadas`, consulta tendencias agregadas en `analytics-store` en solo lectura,
     mantiene en su propio esquema particionado por `usuario_id` el estado de preferencias aprendidas
     con retroalimentación **human-in-the-loop** (`aceptar`, `descartar`, `ajustar criterios`), expone
     `GET /viajes/{id}/sugerencias` y `POST /sugerencias/{id}/feedback` hacia los BFF, y cuando el
     viajero confirma incorporar una sugerencia invoca el comando estándar `POST /reservas` de
     `itinerary-escritura`. **Interfaces nuevas en el dominio existente: `0`.**
   * **Si se elige Opción B (`virtual-assistant`):** se suscribe a `DisrupcionDetectada` y
     `PreferenciasActualizadas`, lee el contexto vivo del viaje mediante `GET /viajes/{id}` en
     `itinerary-lectura`, gestiona en su propio almacén la sesión conversacional multi-turno expuesta
     en `POST /asistente/sesiones/{sid}/mensajes` vía BFF, aplica ajustes simples confirmados por el
     usuario vía `POST/PUT /reservas` en `itinerary-escritura`, y **deriva los reclamos o
     reprogramaciones complejas invocando el contrato ya existente `POST /casos` de `support-liaison`**
     adjuntando la síntesis estructurada de la conversación. **Interfaces nuevas en el dominio
     existente: `0`.**
2. **Aislamiento operativo y de privacidad del elemento nº 14.** El nuevo módulo se clasifica como
   carga degradable en [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md) (ante `Disrupción masiva`,
   `recommendation-engine` se pausa y `virtual-assistant` opera con mamparo estricto sin quitar CPU ni
   conexiones a `itinerary`), no posee permiso alguno sobre `VAULT` (`Regla R5`, [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md))
   y suscribe `CuentaSuprimida` para borrar su estado propio en `< 24 h` ([ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)).
3. **Regla de recorte del prototipo para la 2da entrega (`CON-05`).** El prototipo ejecutable no
   intentará codificar los 13 servicios completos ni conectarse a decenas de aerolíneas reales:
   implementará una **tajada vertical trazable (*walking skeleton*)** compuesta por (a) los caminos que
   demuestran empíricamente los **5 ASRs** (`QA-01`, `QA-04`, `QA-05`, `QA-11`, `QA-13`) junto con un
   adaptador/extractor ejemplar (`QA-10`/`QA-15`) y el aislamiento analítico (`QA-09`), más (b) el
   módulo avanzado elegido (Opción A u Opción B), sustituyendo proveedores externos adicionales por
   simuladores conformes a los contratos `OpenAPI`/`AsyncAPI` ([ADR-0009](ADR-0009-contratos-spec-driven.md)).

### Consecuencias

* **Bueno,** porque garantiza cero retrabajo sobre los 35 ADRs y las vistas de la 1ra entrega sea cual
  sea la opción avanzada elegida en la 2da entrega.
* **Bueno,** porque da un criterio arquitectónico defendible para `CON-05`: se construye exactamente lo
  que pone a prueba las decisiones riesgosas del árbol de utilidad, no pantallas repetitivas.
* **Neutro,** porque la elección final entre `recommendation-engine` y `virtual-assistant` queda lista
  para tomarse en el primer hito de la 2da entrega según foco del equipo.

### Confirmación

* **En la 1ra entrega (verificación documental):** comprobación en [iteración 4 §5.7](../02-proceso-add/iteracion-4/README.md#57-verificación-en-papel-del-punto-de-extensión-para-la-2da-entrega-d34--con-06-con-05)
  y en [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md) de que todas las aristas
  entrantes y salientes de Opción A y Opción B usan contratos ya declarados en la iteración 2 y
  respetan las reglas `R1`–`R7`.
* **En la 2da entrega (verificación en código):** comprobar en el árbol de código del prototipo que
  integrar el módulo elegido modifica `0` contratos de `itinerary` y `support-liaison` (`openapi-diff`
  sin cambios en ellos).

## Pros y contras de las opciones

### J1 — Incrustar el módulo avanzado dentro de `itinerary`

* Bueno, porque evita desplegar un contenedor adicional.
* **Malo, porque viola la cohesión del núcleo de dominio, reabre `R-5` y acopla dependencias pesadas de
  recomendación/PLN al camino transaccional de reservas.**

### J2 — Construir un *framework* genérico de agentes antes de elegir A o B

* Bueno, porque intenta abstraer ambas opciones bajo un mismo motor.
* **Malo, porque introduce complejidad accidental innecesaria para un equipo de 4 personas (`CON-05`,
  `CON-09`) cuando A y B tienen dinámicas de interacción distintas.**

### J3 — Elemento autónomo nº 14 sobre eventos/APIs existentes + tajada vertical por ASRs

* Bueno, porque demuestra extensibilidad real de la arquitectura oriental a eventos sin especulación y
  acota con rigor el prototipo.
* Malo, porque suma dos rutas de composición simples en `bff-web` y `bff-mobile` al activar la opción
  elegida.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D34](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d34--punto-de-extensión-para-el-módulo-avanzado-y-recorte-de-la-2da-entrega-con-06-con-05)
* Diseño en papel comparado de Opción A y Opción B: [iteración 4, sección 5.7](../02-proceso-add/iteracion-4/README.md#57-verificación-en-papel-del-punto-de-extensión-para-la-2da-entrega-d34--con-06-con-05)
* Vista estática del punto de extensión: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md)
* Relacionados: [ADR-0001](ADR-0001-estilo-arquitectonico.md), [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md)
