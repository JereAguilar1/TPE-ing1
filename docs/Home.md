# Wiki — TPE Trotamundos

Arquitectura del sistema **Trotamundos** (panel unificado de gestión de viajes) diseñada con el
método **ADD** (*Attribute-Driven Design*, Cervantes & Kazman), con las decisiones registradas
como **ADR** en formato **MADR**.

> **Cómo leer esta wiki.** El orden recomendado es: (1) el análisis inicial, que fija los
> *drivers* inmutables del diseño; (2) el proceso ADD, donde cada iteración consume esos drivers
> y produce decisiones; (3) los ADR, que son el registro normativo de cada decisión; (4) las
> vistas, que muestran las estructuras resultantes. La [matriz de
> trazabilidad](05-trazabilidad/matriz-drivers-decisiones.md) conecta las cuatro cosas.

---

## 0. Gestión del trabajo

| Página | Para qué sirve |
|---|---|
| [Equipo y responsabilidades](00-gestion/equipo.md) | Integrantes, roles y reparto de trabajo por iteración |
| [Bitácora de evolución](00-gestion/bitacora.md) | Registro fechado de qué se hizo y quién lo hizo |
| [Plan de iteraciones ADD](00-gestion/plan-de-iteraciones.md) | Las 4 iteraciones: objetivo, alcance y artefactos esperados |

## 1. Análisis inicial y pre-requisitos

Esta sección es el **refinado de la especificación dada**: convierte la narrativa del enunciado en
drivers verificables, y deja explícito todo lo que el enunciado no dice.

| Página | Para qué sirve |
|---|---|
| [1.1 Propósito y alcance](01-analisis-inicial/01-proposito-y-alcance.md) | Qué es el sistema, qué queda dentro y qué queda fuera |
| [1.2 Diagrama de contexto](01-analisis-inicial/02-diagrama-de-contexto.md) | Límites del sistema y actores/sistemas externos |
| [1.3 Requisitos funcionales](01-analisis-inicial/03-requisitos-funcionales.md) | RF-01…RF-15 priorizados, y los casos de uso primarios |
| [1.4 Escenarios de atributos de calidad](01-analisis-inicial/04-escenarios-de-calidad.md) | QA-01…QA-18 en formato de 6 partes del SEI |
| [1.5 Restricciones](01-analisis-inicial/05-restricciones.md) | CON-01…CON-10 (técnicas, de negocio y de proceso) |
| [1.6 Inquietudes arquitectónicas](01-analisis-inicial/06-concerns-arquitectonicos.md) | CRN-01…CRN-10 |
| [1.7 Supuestos, ambigüedades y carga derivada](01-analisis-inicial/07-supuestos-y-carga-derivada.md) | Los números que el enunciado no da, y cómo se derivaron |
| [1.8 Árbol de utilidad](01-analisis-inicial/08-arbol-de-utilidad.md) | Priorización (valor de negocio, riesgo técnico) y selección de ASRs |
| [1.9 Glosario y modelo conceptual](01-analisis-inicial/09-glosario.md) | Vocabulario común del dominio |

## 2. Proceso ADD

| Página | Estado |
|---|---|
| [Resumen del proceso](02-proceso-add/README.md) | — |
| [Iteración 1 — Estructura general del sistema](02-proceso-add/iteracion-1/README.md) | ✅ Completa |
| [Iteración 2 — Estructuras para la funcionalidad primaria](02-proceso-add/iteracion-2-plan.md) | 📋 Planificada |
| [Iteración 3 — Refinamiento para rendimiento, disponibilidad y escalabilidad](02-proceso-add/iteracion-3-plan.md) | 📋 Planificada |
| [Iteración 4 — Refinamiento para interoperabilidad, seguridad y evolucionabilidad](02-proceso-add/iteracion-4-plan.md) | 📋 Planificada |

## 3. Decisiones arquitectónicas (ADR)

[Índice de ADRs](03-adr/README.md) · [Plantilla MADR](03-adr/plantilla-madr.md)

| ADR | Decisión | Iteración |
|---|---|---|
| [ADR-0001](03-adr/ADR-0001-estilo-arquitectonico.md) | Microservicios orientados a eventos con núcleo acotado | 1 |
| [ADR-0002](03-adr/ADR-0002-despliegue-multirregion.md) | Despliegue activo-activo en tres regiones | 1 |
| [ADR-0003](03-adr/ADR-0003-separacion-planos.md) | Separación de plano operacional y plano analítico | 1 |
| [ADR-0004](03-adr/ADR-0004-obtencion-de-correo.md) | Obtención de correo por push con reconciliación periódica | 1 |
| [ADR-0005](03-adr/ADR-0005-capa-de-clientes-bff.md) | Capa de clientes con un BFF por tipo de cliente | 1 |
| [ADR-0006](03-adr/ADR-0006-capa-de-anticorrupcion.md) | Capa de anticorrupción con adaptadores de proveedor como plugins | 1 |
| [ADR-0007](03-adr/ADR-0007-identidad-y-comparticion.md) | OIDC para identidad, delegación OAuth y compartición por designados | 1 |
| [ADR-0008](03-adr/ADR-0008-alcance-disponibilidad.md) | Alcance y forma de medición del objetivo de disponibilidad | 1 |
| [ADR-0009](03-adr/ADR-0009-contratos-spec-driven.md) | Contratos (OpenAPI/AsyncAPI) como artefactos de primera clase | 1 |

## 4. Vistas arquitectónicas

| Vista | Qué muestra |
|---|---|
| [Contexto](04-vistas/vista-contexto.md) | El sistema como caja negra frente a su entorno |
| [Módulos — nivel 1](04-vistas/vista-modulos-nivel-1.md) | Descomposición en subsistemas y sus dependencias |
| [Componentes y conectores — nivel 1](04-vistas/vista-cyc-nivel-1.md) | Elementos en ejecución y cómo se comunican |
| [Despliegue — nivel 1](04-vistas/vista-despliegue-nivel-1.md) | Asignación a infraestructura multirregión |

## 5. Trazabilidad

[Matriz driver → decisión → vista → ADR](05-trazabilidad/matriz-drivers-decisiones.md)
