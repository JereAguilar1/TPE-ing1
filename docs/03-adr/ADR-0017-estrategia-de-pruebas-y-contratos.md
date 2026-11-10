---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: CRN-06, CON-04, QA-10, QA-11, QA-16, CON-09
---

# ADR-0017: Pruebas derivadas de la especificación con suite de conformidad de complementos

## Contexto y planteo del problema

Esta decisión es **de proceso**, no estructural, como D8 y D9 en la iteración 1. Se toma aquí
porque cierra el criterio de salida 3 de la iteración 2 (todas las interfaces con contrato) y
porque sin ella QA-10 y QA-11 no son verificables.

[ADR-0009](ADR-0009-contratos-spec-driven.md) estableció que los contratos OpenAPI y AsyncAPI son
artefactos de primera clase. Falta decidir **cómo se verifica** que las implementaciones los
cumplen. El problema principal no son los elementos internos sino los **terceros**
(aerolíneas, hoteleras, proveedores de correo), que no van a publicar contratos de consumidor y
cuyos entornos de prueba el equipo no controla.

## Drivers de decisión

* **CON-04** — el prototipo respeta las especificaciones definidas contractualmente.
* **CRN-06** — estrategia concreta de pruebas de contrato.
* **QA-10** — un adaptador nuevo se verifica sin modificar elementos existentes.
* **QA-11** — el acierto de un extractor es medible.
* **QA-16** — trazabilidad de la decisión al código.
* **CON-09** — cuatro personas; no hay capacidad para operar infraestructura de pruebas pesada.

## Opciones consideradas

* **Q1** — Pruebas de extremo a extremo en un entorno integrado.
* **Q2** — Pruebas de contrato dirigidas por el consumidor, con un *broker* de contratos.
* **Q3** — Pruebas derivadas de la especificación (OpenAPI y AsyncAPI como fuente).

Comparación completa: [iteración 2, paso 4, D17](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d17--estrategia-de-pruebas-y-verificación-de-contratos-crn-06-con-04).

## Resultado de la decisión

Se adopta **Q3: el contrato es la fuente de verdad y las pruebas se derivan de él**, en seis
niveles:

| Nivel | Qué verifica | Contra qué |
|---|---|---|
| Contrato sincrónico | Cada implementación cumple su OpenAPI y los clientes no esperan algo ajeno a él | La especificación; detección de cambios incompatibles en cada cambio |
| Contrato de eventos | Cada evento publicado y consumido cumple su AsyncAPI | La especificación |
| **Suite de conformidad de complementos** | Un adaptador o extractor cumple el contrato canónico **y** su salida valida contra el esquema del tipo de segmento | La misma suite para todos los complementos |
| Corpus de referencia | Acierto de cada extractor y comportamiento del disyuntor de calidad | Correos anonimizados ([ADR-0015](ADR-0015-politica-de-confianza-de-extraccion.md)) |
| Grabaciones de terceros | Que los proveedores no cambiaron su contrato | Respuestas reales grabadas, revalidadas con frecuencia fija |
| Propiedades de la fusión | Que la consolidación es determinista e idempotente | Pruebas basadas en propiedades sobre `Reserva` ([ADR-0010](ADR-0010-modelo-canonico-reserva-segmento-viaje.md)) |

### Consecuencias

* **Bueno,** porque el contrato deja de ser documentación y pasa a ser una prueba: si el código se
  aparta, la construcción falla (CON-04).
* **Bueno,** porque la suite de conformidad vuelve literal la medida de QA-10: un complemento
  nuevo pasa la misma suite sin que se modifique nada existente.
* **Bueno,** porque las grabaciones desacoplan las pruebas de los entornos de terceros.
* **Malo,** porque las grabaciones envejecen y hay que revalidarlas periódicamente.
* **Malo,** porque las pruebas derivadas de la especificación no detectan errores de integración
  que el contrato no expresa; se acepta ese hueco por CON-09.
* **Neutro,** porque Q2 queda como alternativa a reconsiderar si el equipo crece.

### Confirmación

* El *pipeline* de integración continua del prototipo ejecuta los seis niveles; un cambio
  incompatible en un contrato hace fallar la construcción.
* Un complemento ficticio nuevo pasa la suite de conformidad sin cambios en otros archivos
  (prueba de QA-10).
* Cada prueba referencia en su nombre o metadatos el identificador del contrato y del ADR que
  verifica (QA-16).

## Pros y contras de las opciones

### Q1 — Extremo a extremo en entorno integrado

* Bueno, porque prueba el sistema como lo ve el usuario.
* **Malo, porque es costosa, lenta y frágil** para cuatro personas (CON-09).
* Malo, porque depende de entornos de terceros que el equipo no controla.

### Q2 — Contratos dirigidos por el consumidor

* Bueno, porque es la técnica más precisa entre equipos internos independientes.
* **Malo, porque los terceros no publican contratos de consumidor**, que es justamente el problema
  principal.
* Malo, porque el *broker* de contratos es otro componente que operar.

### Q3 — Derivadas de la especificación

* Bueno, porque reutiliza los contratos que ya existen por ADR-0009 y cubre a los terceros con
  grabaciones.
* Malo, porque no cubre lo que el contrato no expresa.

## Más información

* Drivers: [CON-04 y CON-09](../01-analisis-inicial/05-restricciones.md),
  [CRN-06](../01-analisis-inicial/06-concerns-arquitectonicos.md),
  [QA-10](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-10--integración-de-un-proveedor-de-viaje-nuevo),
  [QA-16](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-16--trazabilidad-de-una-decisión-al-código)
* Análisis comparativo: [iteración 2, paso 4, D17](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d17--estrategia-de-pruebas-y-verificación-de-contratos-crn-06-con-04)
* Relacionados: [ADR-0006](ADR-0006-capa-de-anticorrupcion.md), [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0015](ADR-0015-politica-de-confianza-de-extraccion.md), [ADR-0027](ADR-0027-versionado-y-evolucion-de-contratos.md) (evolución de los contratos)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
