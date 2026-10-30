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
| [Resumen del proceso](02-proceso-add/README.md) | ✅ 1ra entrega cerrada (58/58 drivers atendidos) |
| [Iteración 1 — Estructura general del sistema](02-proceso-add/iteracion-1/README.md) | ✅ Completa |
| [Iteración 2 — Estructuras para la funcionalidad primaria](02-proceso-add/iteracion-2/README.md) | ✅ Completa |
| [Iteración 3 — Refinamiento para rendimiento, disponibilidad y escalabilidad](02-proceso-add/iteracion-3/README.md) | ✅ Completa |
| [Iteración 4 — Refinamiento para interoperabilidad, seguridad, evolucionabilidad y uso internacional](02-proceso-add/iteracion-4/README.md) | ✅ Completa |

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
| `ADR-0010`…`ADR-0017` | Decisiones `D10`–`D17` de funcionalidad primaria ([ver Iteración 2](02-proceso-add/iteracion-2/paso-4-alternativas.md)) | 2 |
| [ADR-0018](03-adr/ADR-0018-consistencia-datos-multirregion.md) | Consistencia multirregión con región primaria por usuario y testigo transregional | 3 |
| [ADR-0019](03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) | Caché multinivel del camino de lectura y arranque móvil | 3 |
| [ADR-0020](03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | Contrapresión, colas con prioridad y modos automáticos de degradación | 3 |
| [ADR-0021](03-adr/ADR-0021-estrategia-autoescalado.md) | Autoescalado híbrido y separación operativa de `itinerary` | 3 |
| [ADR-0022](03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) | Entrega progresiva canaria por región, reversión automática y *expand/contract* | 3 |
| [ADR-0023](03-adr/ADR-0023-particionamiento-y-crecimiento.md) | Particionamiento por *hash* consistente (`64` *buckets*) y archivo frío | 3 |
| [ADR-0024](03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | Mamparos, cortacircuitos, cola persistente y gobierno de cuotas de terceros | 3 |
| [ADR-0025](03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | Observabilidad con OpenTelemetry y gobierno por presupuesto de error | 3 |
| [ADR-0026](03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) | Modelo de costo mensual y camino escalonado en tres etapas | 3 |
| [ADR-0027](03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) | Evolución compatible de contratos por omisión, negociación de versión mayor y `SemVer` en complementos | 4 |
| [ADR-0028](03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) | Autorización declarativa ABAC con vales firmados, OTP para designados sin cuenta y publicación por lista blanca | 4 |
| [ADR-0029](03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) | Cifrado por sobres (`KEK_region` / `DEK_u`), custodia mTLS exclusiva, detección `≤ 5 min` y revocación `≤ 15 min` | 4 |
| [ADR-0030](03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) | Bitácora de auditoría inmutable y supresión verificable en dos fases sobre ambos planos (`≤ 30 días`) | 4 |
| [ADR-0031](03-adr/ADR-0031-residencia-de-datos-por-region.md) | Residencia de datos en tres clases y testigo transregional cifrado jurisdiccional (`R-6` cerrado) | 4 |
| [ADR-0032](03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | Dominio neutral al idioma, catálogos ICU en CDN y formateo CLDR con instantes `UTC + IANA TZ` | 4 |
| [ADR-0033](03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) | Evaluación espacial en el dispositivo móvil con geocodificación previa y degradación sin GPS | 4 |
| [ADR-0034](03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) | Punto de extensión del módulo avanzado nº 14 (Opción A y B) y recorte del prototipo por ASRs | 4 |
| [ADR-0035](03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | Ingesta sin OAuth mediante reenvío verificado / credenciales delegadas y flujo asistido ante formato desconocido | 4 |

## 4. Vistas arquitectónicas

| Vista | Qué muestra |
|---|---|
| [Contexto](04-vistas/vista-contexto.md) | El sistema como caja negra frente a su entorno |
| [Módulos — nivel 1](04-vistas/vista-modulos-nivel-1.md) | Descomposición en subsistemas y sus dependencias |
| [Módulos — nivel 2 (adaptadores, identidad y extensión)](04-vistas/vista-modulos-adaptadores.md) | Subsistema de complementos versionados, interior de `identity-access` y `sharing`, `locales-icu` y elemento nº 14 |
| [Componentes y conectores — nivel 1](04-vistas/vista-cyc-nivel-1.md) | Elementos en ejecución y cómo se comunican |
| [Despliegue — nivel 1](04-vistas/vista-despliegue-nivel-1.md) | Asignación a infraestructura multirregión |
| [Despliegue — nivel 2](04-vistas/vista-despliegue-nivel-2.md) | Interior regional en 3 AZs, topología de datos sin `R-1`/`R-4`, dimensionamiento y autoescalado |
| [Seguridad, privacidad y residencia de datos](04-vistas/vista-seguridad-y-datos.md) | Fronteras de confianza, cifrado por sobres, cierre gráfico de `R-6`, catálogo de PII y supresión en ambos planos |

## 5. Trazabilidad

[Matriz driver → decisión → vista → ADR (58/58 drivers · 100 %)](05-trazabilidad/matriz-drivers-decisiones.md)
