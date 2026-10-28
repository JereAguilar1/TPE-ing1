# Iteración 2 — Identificar las estructuras que soportan la funcionalidad primaria

> **Estado:** 📋 Planificada · **Responsable de coordinación:** Jeremias Aguilar

Este es el plan de la iteración, no su resultado. Está escrito por adelantado para que el alcance
quede comprometido y no se descubra a mitad de camino (CON-05, CON-09).

## Paso 1 — Entradas

Las mismas del análisis inicial, **más** los productos de la iteración 1: la estructura general de
13 elementos, los nueve ADRs, las cuatro vistas de nivel 1 y el
[kanban de drivers](iteracion-1/paso-7-analisis.md#kanban-de-drivers).

## Paso 2 — Objetivo de la iteración

> Identificar las estructuras internas que soportan los 9 requisitos funcionales primarios y los 7
> casos de uso primarios, de modo que cada caso de uso tenga un recorrido completo y especificado
> entre elementos con interfaces declaradas.

### Drivers que consume

| Driver | Estado al cerrar la iteración 1 | Qué debe lograr esta iteración |
|---|---|---|
| RF-03, RF-07 | 🟨 / ⬜ | **El modelo canónico** de Reserva, Segmento, Viaje y Tipo de segmento. Es el artefacto central de la iteración |
| RF-01 | 🟨 | Ciclo de vida del consentimiento de un buzón: otorgar, renovar, revocar |
| RF-02 | 🟨 | Diseño interno de suscripciones y del sondeo de reconciliación |
| RF-04 | ⬜ | Filtros y whitelists de remitentes |
| RF-05 | 🟨 | Contrato canónico de adaptador de proveedor, concreto |
| RF-06 | ⬜ | Gestión manual, incluida la resolución de conflictos con las fuentes automáticas |
| RF-08 | ⬜ | Ciclo de vida del viaje y archivado (política de AMB-08) |
| RF-09 | 🟨 | Contratos de los dos BFF |
| RF-10 | 🟨 | Reglas de notificación y canales |
| RF-12, RF-15 | ⬜ | Caso de soporte y preferencias |
| RF-14 | 🟨 | Modelo dimensional del plano analítico |
| QA-11 | 🟨 | Umbral de confianza de extracción y flujo hacia el usuario |
| CRN-06 | 🟨 | Estrategia concreta de pruebas de contrato |
| **CRN-11** | nuevo | **Resolución de conflictos** entre fuentes que describen la misma reserva |
| **CRN-12** | nuevo | **Idempotencia** de la ingesta: el mismo mensaje puede llegar dos veces |

## Paso 3 — Elementos a refinar

| Elemento | Por qué |
|---|---|
| `itinerary` | Es el núcleo del dominio, el elemento más grande y el que concentra más riesgo |
| `booking-extraction` | Es el elemento del riesgo **R-2** (fragilidad de la extracción desde correo) |
| `mail-ingest` | Tiene dos caminos de ingesta que deben converger ([ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md)) |
| `provider-sync` | El contrato canónico de adaptador determina si QA-10 y QA-15 se cumplen |
| `preferences` | Es pequeño y habilita RF-08, RF-12 y RF-15 |

## Paso 4 — Conceptos de diseño a evaluar

| Decisión | Alternativas a evaluar |
|---|---|
| Modelo del dominio y sus límites | Modelo rico de dominio · modelo anémico con servicios · agregados con límites transaccionales explícitos |
| Persistencia del modelo canónico | Relacional normalizado · documental · relacional con campos semiestructurados para la variabilidad por tipo de segmento |
| Extensibilidad del tipo de segmento (QA-15) | Herencia de tablas · tabla única con atributos por tipo · registro de tipos con esquema declarado |
| Deduplicación y fusión (CRN-11) | Clave natural por código de confirmación · coincidencia difusa por atributos · precedencia por fuente con intervención del usuario |
| Idempotencia de la ingesta (CRN-12) | Clave de idempotencia por mensaje · registro de huellas procesadas · operaciones naturalmente idempotentes |
| Umbral de confianza de extracción (QA-11) | Umbral fijo · umbral por remitente · confirmación del usuario por debajo del umbral |
| Modelo del plano analítico | Esquema en estrella · tabla ancha desnormalizada · eventos crudos con vistas |

## Paso 5 — Qué se instancia

- Descomposición interna de `itinerary` en sus módulos y agregados.
- Contrato del extractor de correo y del adaptador de proveedor, concretos.
- Esquemas de persistencia del plano operacional.
- Modelo dimensional del plano analítico.

## Paso 6 — Artefactos esperados

| Artefacto | Dónde irá |
|---|---|
| Modelo de dominio detallado | `01-analisis-inicial/09-glosario.md` ampliado, más una página propia en la iteración |
| Vista de módulos nivel 2 de `itinerary` y `booking-extraction` | `04-vistas/vista-modulos-nivel-2.md` |
| Diagramas de secuencia de UC-1 a UC-7 | `04-vistas/secuencias-casos-primarios.md` |
| Contratos OpenAPI y AsyncAPI de todas las interfaces de nivel 1 | `contratos/` en la raíz del repositorio ([ADR-0009](../03-adr/ADR-0009-contratos-spec-driven.md)) |

## ADRs previstos

| ADR | Tema | Driver principal |
|---|---|---|
| ADR-0010 | Modelo canónico de Reserva, Segmento y Viaje | RF-03, RF-07, QA-15 |
| ADR-0011 | Extensibilidad del tipo de segmento | QA-15 |
| ADR-0012 | Estrategia de persistencia del plano operacional | QA-02, QA-08 |
| ADR-0013 | Deduplicación y resolución de conflictos entre fuentes | CRN-11, RF-06, RF-07 |
| ADR-0014 | Idempotencia de la ingesta | CRN-12 |
| ADR-0015 | Política de confianza de extracción de correo | QA-11 |
| ADR-0016 | Modelo dimensional del plano analítico | RF-14 |
| ADR-0017 | Estrategia de pruebas y verificación de contratos | CRN-06, CON-04 |

## Criterios de salida

1. Los 7 casos de uso primarios tienen un diagrama de secuencia completo, sin pasos «por definir».
2. Los 15 requisitos funcionales están en 🟨 o 🟩; **ninguno** en ⬜.
3. Todas las interfaces de la [vista C&C de nivel 1](../04-vistas/vista-cyc-nivel-1.md) tienen
   contrato declarado en el repositorio.
4. El riesgo **R-2** tiene una mitigación concreta y verificable, no solo la regla estructural de
   «no inventar».
5. El modelo canónico se valida contra QA-15: se demuestra en papel que agregar «tren» toca a lo
   sumo dos elementos.

## Riesgo propio de esta iteración

El modelo canónico es la decisión de mayor alcance de todo el trabajo: de él dependen QA-15, QA-10,
QA-11 y la viabilidad del punto de extensión de la 2da entrega. Equivocarlo es el escenario de
retrabajo más caro del proyecto. **Mitigación:** validarlo explícitamente contra los cinco tipos de
segmento (vuelo, hotel, auto, tren, autobús) antes de cerrar la iteración, incluidos los dos que
todavía no se implementan.
