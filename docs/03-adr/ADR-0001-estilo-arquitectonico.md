---
estado: aceptado
fecha: 2026-10-24
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 1
drivers: QA-04, QA-05, QA-09, QA-10, QA-15, CON-09, CON-A4, CRN-01, CRN-02, CRN-08
---

# ADR-0001: Microservicios orientados a eventos con granularidad acotada

## Contexto y planteo del problema

Trotamundos es un sistema *greenfield* sin base de código previa y sin una arquitectura de
referencia establecida para su dominio, de modo que la primera decisión es qué forma general tiene
el *backend*.

El análisis inicial dejó en evidencia que **el sistema tiene tres perfiles de carga radicalmente
distintos**, y esto es lo que determina la decisión:

| Carga | Perfil | Presupuesto de latencia | Volumen |
|---|---|---|---|
| Ingesta de correo y de proveedores | Ráfagas, asíncrona | 300 s de punta a punta | 45 eventos/s de promedio, 450 en pico de disrupción |
| Lectura del panel | Sostenida, sincrónica | **800 ms en el p95** | 3.000 req/s normales, 9.000 en disrupción |
| Consultas analíticas | Pesada, episódica | 30 s | Sobre 3.300 millones de registros |

Tres cargas con esos perfiles no se dimensionan ni se escalan juntas. Absorber el pico de ingesta
de [QA-04](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-04--pico-de-carga-por-disrupción-masiva)
replicando también el camino de lectura significa pagar capacidad que no se necesita, y
[QA-09](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica)
exige directamente que la carga analítica no compita por los recursos de la operación.

Al mismo tiempo hay una fuerza en sentido contrario: CON-09 dice que el equipo son **cuatro
personas con dedicación parcial**. Una granularidad fina de servicios satisfaría los mismos
atributos de calidad y volvería el trabajo inviable, tanto de construir como de documentar.

## Drivers de decisión

* **QA-04** — absorber 9.000 req/s y 450 eventos/s durante 30 minutos sin perder actualizaciones,
  degradando lo secundario antes que el panel.
* **QA-09** — la carga analítica no debe degradar el p95 operacional más de un 5 %.
* **QA-05** — los elementos deben poder replicarse por región de forma independiente.
* **QA-10, QA-15** — agregar un proveedor o un medio de transporte sin modificar lo existente.
* **CON-09 / CON-A4** — el diseño tiene que ser construible y documentable por cuatro personas con
  dedicación parcial; menos de 15 elementos.
* **CRN-01** — establecer la estructura general del sistema.
* **CRN-02** — la estructura debe permitir repartir el trabajo entre cuatro personas.
* **CRN-08** — el costo de infraestructura es una fuerza real.

## Opciones consideradas

* **A1** — Monolito modular en capas.
* **A2** — SOA con un bus de integración central.
* **A3** — Microservicios orientados a eventos, con granularidad acotada.
* **A4** — Serverless (funciones) puro.

La comparación completa contra cada driver está en el
[paso 4 de la iteración 1](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d1--estilo-arquitectónico-del-backend).

## Resultado de la decisión

Se adopta **A3: microservicios orientados a eventos con granularidad acotada**, con tres
precisiones que son parte de la decisión y no detalles de implementación:

1. **La comunicación entre el plano de ingesta y el dominio es asíncrona**, mediante un *broker* de
   mensajería con eventos de dominio. Es lo que desacopla la ráfaga de QA-04 del camino de lectura.
2. **La comunicación del camino de lectura es sincrónica** (HTTP/JSON), porque el presupuesto de
   800 ms de QA-02 no tolera indirección adicional.
3. **Los límites entre servicios se trazan por perfil de carga y por frontera de confianza, no por
   entidad del dominio.** Por eso `identity-access` es un servicio propio (frontera de confianza de
   QA-13) y por eso `mail-ingest` está separado de `booking-extraction` (la primera es E/S contra
   terceros, la segunda es cómputo); pero no hay un servicio por cada entidad del modelo.

El techo de **15 elementos** queda formalizado como CON-A4.

### Consecuencias

* **Bueno,** porque la ingesta y la lectura escalan por separado: el pico de disrupción de QA-04 se
  absorbe agregando consumidores de la cola sin tocar el camino de lectura.
* **Bueno,** porque el flujo de eventos de dominio que este estilo requiere es, sin trabajo
  adicional, la fuente de alimentación del plano analítico de [ADR-0003](ADR-0003-separacion-planos.md).
* **Bueno,** porque cada servicio se replica por región de forma independiente, que es lo que
  [ADR-0002](ADR-0002-despliegue-multirregion.md) necesita.
* **Bueno,** porque los adaptadores de proveedor se agregan como elementos nuevos, habilitando la
  medida de «0 elementos modificados» de QA-10.
* **Malo,** porque es más caro de operar que un monolito: hay 13 elementos que desplegar, observar
  y versionar, con un equipo de cuatro personas (CRN-08, CON-09).
* **Malo,** porque introduce consistencia eventual entre servicios. Una reserva extraída de un
  correo no está visible en el panel en el mismo instante. El presupuesto de frescura de 300 s lo
  absorbe, pero deja de ser cierto que «escribir y leer» sea atómico.
* **Malo,** porque la depuración de un flujo que atraviesa cuatro servicios y un *broker* es más
  difícil. Esto convierte la trazabilidad distribuida en un requisito de operación, no en un lujo.
* **Neutro,** porque se adopta *serverless* de forma **acotada** para cargas episódicas y
  tolerantes a latencia: el sondeo de reconciliación de [ADR-0004](ADR-0004-obtencion-de-correo.md)
  y los trabajos de archivado de RF-08. No es el estilo general, es una elección puntual donde el
  perfil de carga lo justifica.

### Confirmación

* La [vista de módulos nivel 1](../04-vistas/vista-modulos-nivel-1.md) declara las dependencias
  permitidas entre subsistemas; una verificación automática de dependencias en la construcción del
  prototipo falla si alguna se viola.
* El recuento de elementos del plano operacional se verifica contra CON-A4 (< 15) en cada
  iteración.
* Una prueba de carga del prototipo debe mostrar que agregar consumidores de la cola de ingesta
  aumenta el rendimiento de la ingesta **sin** alterar el p95 del camino de lectura.

## Pros y contras de las opciones

### A1 — Monolito modular en capas

* Bueno, porque es lo más simple de construir, documentar y depurar: encaja perfectamente con
  CON-09.
* Bueno, porque es el más barato de operar (CRN-08).
* Bueno, porque la consistencia es trivial: no hay consistencia eventual que explicar.
* **Malo, porque escala como un bloque.** Absorber la ráfaga de ingesta de QA-04 obliga a replicar
  el camino de lectura simultáneamente, pagando capacidad inútil.
* **Malo, porque no puede satisfacer QA-09:** la consulta analítica comparte proceso y almacén con
  la operación.
* Malo, porque el despliegue es todo-o-nada, lo que complica QA-07 con un presupuesto de 5 minutos
  mensuales.

### A2 — SOA con un bus de integración central

* Bueno, porque la mediación centralizada facilita agregar proveedores (QA-10).
* Bueno, porque el bus absorbe la ráfaga de ingesta.
* Malo, porque el bus se convierte en el cuello de botella y en un punto crítico adicional que hay
  que replicar en tres regiones.
* Malo, porque concentra en el bus la lógica de traducción que [ADR-0006](ADR-0006-capa-de-anticorrupcion.md)
  prefiere tener en adaptadores sustituibles y versionados en el repositorio.
* Malo, porque operar y versionar el bus es trabajo que CON-09 no tiene disponible.

### A3 — Microservicios orientados a eventos con granularidad acotada

* Bueno, porque atiende QA-04, QA-05, QA-09, QA-10 y QA-15 a la vez, que es más de lo que cualquier
  otra opción logra.
* Bueno, porque el flujo de eventos es un subproducto aprovechable (ADR-0003).
* Malo, porque el costo de operación y de documentación es el más alto después de A2.
* Malo, porque introduce consistencia eventual.
* Neutro: la granularidad **acotada** es lo que lo hace viable; sin CON-A4 esta opción sería
  inviable para el equipo.

### A4 — Serverless puro

* Bueno, porque el escalado elástico es inmediato, que es ideal para QA-04.
* Bueno, porque se paga por uso, lo mejor para CRN-08 en una etapa temprana.
* **Malo, porque el arranque en frío es incompatible con el presupuesto de 800 ms de QA-02** cuando
  el camino de lectura atraviesa varias funciones.
* Malo, porque el control fino que exige la replicación activo-activo de QA-05 es más difícil de
  obtener.
* Malo, porque un sistema de 13 responsabilidades expresado como decenas de funciones es más
  difícil de razonar y documentar, y CRN-02 pide lo contrario.

## Más información

* Drivers: [QA-04](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-04--pico-de-carga-por-disrupción-masiva),
  [QA-09](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica),
  [CON-09 y CON-A4](../01-analisis-inicial/05-restricciones.md),
  [CRN-01 y CRN-02](../01-analisis-inicial/06-concerns-arquitectonicos.md)
* Análisis comparativo: [iteración 1, paso 4, D1](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d1--estilo-arquitectónico-del-backend)
* Vistas afectadas: [módulos N1](../04-vistas/vista-modulos-nivel-1.md), [C&C N1](../04-vistas/vista-cyc-nivel-1.md)
* Relacionados: [ADR-0002](ADR-0002-despliegue-multirregion.md), [ADR-0003](ADR-0003-separacion-planos.md), [ADR-0006](ADR-0006-capa-de-anticorrupcion.md)
