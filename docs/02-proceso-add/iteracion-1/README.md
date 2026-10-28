# Iteración 1 — Establecer la estructura general del sistema

> **Estado:** ✅ Completa · **Fecha:** 2026-10-24 · **Participantes:** los cuatro integrantes

| Página de esta iteración | Contenido |
|---|---|
| Esta página | Pasos 1, 2, 3, 5 y 6 del método |
| [Paso 4 — Conceptos de diseño y alternativas](paso-4-alternativas.md) | Las 7 decisiones de la iteración, con las alternativas evaluadas y descartadas |
| [Paso 7 — Análisis y kanban de drivers](paso-7-analisis.md) | Verificación del objetivo y estado de los 53 drivers |

---

## Paso 1 — Revisar las entradas

El sistema es *greenfield* y novedoso: no hay código previo, no hay una arquitectura de referencia
consolidada para el dominio de la agregación de itinerarios, y no hay un sistema del cual este sea
una variación. Esto determina el propósito de diseño y, con él, el objetivo de esta primera
iteración.

| Categoría de entrada | Contenido | Dónde está |
|---|---|---|
| **Propósito de diseño** | Diseñar un sistema nuevo completo, hasta el punto en que un prototipo pueda demostrar la viabilidad de la arquitectura frente a los escenarios más riesgosos | [1.1](../../01-analisis-inicial/01-proposito-y-alcance.md#propósito-de-diseño-en-el-sentido-de-add) |
| **Requisitos funcionales primarios** | 9 de 15, agrupados en 7 casos de uso primarios UC-1…UC-7 | [1.3](../../01-analisis-inicial/03-requisitos-funcionales.md#casos-de-uso-primarios) |
| **Escenarios de atributos de calidad** | QA-01…QA-18, de los cuales 5 son ASRs del cuadrante (Alto, Alto) | [1.4](../../01-analisis-inicial/04-escenarios-de-calidad.md) · [1.8](../../01-analisis-inicial/08-arbol-de-utilidad.md#escenarios-significativos-para-la-arquitectura-asrs) |
| **Restricciones** | CON-01…CON-10 del enunciado, más CON-A1…CON-A4 autoimpuestas | [1.5](../../01-analisis-inicial/05-restricciones.md) |
| **Inquietudes arquitectónicas** | CRN-01…CRN-10 generales, CRN-11…CRN-15 previstas | [1.6](../../01-analisis-inicial/06-concerns-arquitectonicos.md) |

### Lo que las entradas dicen antes de diseñar nada

Tres observaciones del análisis inicial condicionan esta iteración entera:

1. **Las cargas del sistema son radicalmente asimétricas.** La ingesta es una carga en ráfagas,
   asíncrona y tolerante a latencia de minutos (presupuesto de 300 s). La lectura del panel es
   una carga sostenida, sincrónica y sensible a milisegundos (presupuesto de 800 ms). La analítica
   es una carga pesada, rara y tolerante a horas de atraso. **Tres perfiles así no se dimensionan
   ni se escalan juntos.**
2. **El sistema es mayoritariamente una integración.** 12 de 16 interfaces externas son con
   sistemas de terceros, con contratos ajenos, disponibilidad ajena y cuotas ajenas. La
   interoperabilidad no es un requisito lateral: es la forma del sistema.
3. **El objetivo de disponibilidad no admite región única.** 5 minutos al mes no deja margen ni
   para una ventana de mantenimiento ni para un *failover* entre regiones de tipo activo-pasivo.

---

## Paso 2 — Establecer el objetivo de la iteración

> **Objetivo de la iteración 1:** establecer una estructura general del sistema que ofrezca un
> marco donde ubicar la funcionalidad primaria, y que **no impida** alcanzar los escenarios
> significativos para la arquitectura.

La formulación es deliberada. En una primera iteración de un sistema *greenfield* todavía no se
puede *cumplir* QA-01 ni QA-05 —faltan los elementos concretos y sus tácticas— pero sí se puede
elegir mal y volverlos inalcanzables para siempre. El criterio de éxito de esta iteración es por
lo tanto **habilitación**, no cumplimiento.

### Drivers seleccionados para esta iteración

| Driver | Por qué entra en la iteración 1 |
|---|---|
| **ASR-1** / QA-01 — propagación en ≤ 5 min | El mecanismo de obtención de datos externos define el plano de ingesta completo; elegirlo mal (sondeo uniforme) hace el objetivo inalcanzable |
| **ASR-2** / QA-04 — pico por disrupción masiva | Exige que las partes del sistema escalen por separado y que haya una frontera clara entre lo degradable y lo no degradable |
| **ASR-3** / QA-05 — pérdida de una región | Es una decisión de topología de despliegue: no se puede agregar después sin rediseñar |
| **ASR-4** / QA-11 — formato de correo desconocido | Exige una frontera donde contener la heterogeneidad externa antes de que llegue al dominio |
| **ASR-5** / QA-13 — custodia de tokens de correo | La ubicación de los secretos y la segmentación de privilegios son estructurales |
| QA-09 — aislamiento de la carga analítica | Es la asimetría de cargas de la observación 1: decide si hay uno o dos planos de datos |
| QA-02, QA-03 — latencia de web y móvil | Condicionan la capa de clientes y dónde se compone la respuesta |
| QA-10, QA-15 — proveedor nuevo, transporte nuevo | Comparten solución con ASR-4: la capa de anticorrupción |
| CON-01…CON-10, CON-A1…CON-A4 | Las restricciones se satisfacen siempre, en toda iteración |
| CRN-01, CRN-02, CRN-08 | Estructura general, asignación de trabajo a 4 personas, y costo |

### Drivers explícitamente excluidos de esta iteración

Para que el paso 7 pueda ser honesto, hay que declarar qué se dejó afuera a propósito:

| Excluido | Se trata en |
|---|---|
| RF-01…RF-15 en detalle (el *qué* hace cada elemento internamente) | Iteración 2 |
| QA-06, QA-07, QA-08 — tácticas concretas de disponibilidad y escalado | Iteración 3 |
| QA-12, QA-14, QA-16, QA-17, QA-18 — control de acceso, auditoría, i18n | Iteración 4 |
| CRN-11…CRN-15 — conflictos, idempotencia, consistencia, versionado, residencia | Iteraciones 2 a 4 |

---

## Paso 3 — Elegir los elementos del sistema a refinar

Al ser la primera iteración de un sistema *greenfield*, **el elemento a refinar es el sistema
completo**: no hay elementos previos sobre los que trabajar. El resultado de esta iteración será
la primera descomposición del sistema en subsistemas.

---

## Paso 4 — Elegir los conceptos de diseño

Esta es la parte sustantiva de la iteración y está en su propia página, porque incluye las
alternativas evaluadas y los motivos de descarte de cada una:

### → [Paso 4 — Conceptos de diseño y alternativas](paso-4-alternativas.md)

Resumen de las siete decisiones tomadas:

| # | Decisión | Concepto de diseño elegido | ADR |
|---|---|---|---|
| D1 | Estilo arquitectónico del *backend* | Microservicios orientados a eventos, con granularidad acotada | [ADR-0001](../../03-adr/ADR-0001-estilo-arquitectonico.md) |
| D2 | Topología de despliegue | Activo-activo en tres regiones | [ADR-0002](../../03-adr/ADR-0002-despliegue-multirregion.md) |
| D3 | Organización de los datos | Planos operacional y analítico separados, alimentados por flujo de eventos | [ADR-0003](../../03-adr/ADR-0003-separacion-planos.md) |
| D4 | Obtención del correo del usuario | Notificación por *push* del proveedor + sondeo de reconciliación escalonado | [ADR-0004](../../03-adr/ADR-0004-obtencion-de-correo.md) |
| D5 | Capa de clientes | Un *backend for frontend* por tipo de cliente | [ADR-0005](../../03-adr/ADR-0005-capa-de-clientes-bff.md) |
| D6 | Integración con sistemas externos | Capa de anticorrupción con adaptadores como complementos (*plugins*) | [ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md) |
| D7 | Identidad, autorización y compartición | OIDC para el usuario, delegación OAuth 2.0 para el correo, lista de designados para compartir | [ADR-0007](../../03-adr/ADR-0007-identidad-y-comparticion.md) |

Y dos decisiones que no son estructurales pero condicionan todo el resto, por lo que se toman acá:

| # | Decisión | ADR |
|---|---|---|
| D8 | Alcance y forma de medición del objetivo de disponibilidad | [ADR-0008](../../03-adr/ADR-0008-alcance-disponibilidad.md) |
| D9 | Los contratos como artefactos de primera clase (*spec-driven*) | [ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md) |

---

## Paso 5 — Instanciar elementos, asignar responsabilidades y definir interfaces

Aplicando las decisiones D1 a D7, el sistema queda descompuesto en **13 elementos** del plano
operacional, más el plano analítico. El número respeta CON-A4 (menos de 15), que viene de CON-09:
cuatro personas con dedicación parcial.

### Elementos del plano operacional

| Elemento | Responsabilidad única | Interfaz que ofrece | Depende de | Drivers que atiende |
|---|---|---|---|---|
| `edge` | Terminación TLS, caché de recursos estáticos, enrutamiento geográfico al despliegue regional sano | HTTPS público | — | QA-02, QA-03, QA-05 |
| `api-gateway` | Autenticación de la petición, autorización gruesa, limitación de tasa, enrutamiento a los BFF | HTTP/JSON | `identity-access` | QA-02, QA-04, QA-13 |
| `bff-web` | Composición de la respuesta para el cliente web, en una sola ida y vuelta | `GET /panel`, `GET /viajes/{id}` | `itinerary`, `preferences` | QA-02 |
| `bff-mobile` | Composición para el cliente móvil, con *payload* reducido y carga diferida de detalles | `GET /panel/resumen`, `GET /viajes/{id}` | `itinerary`, `preferences` | QA-03, QA-17 |
| `identity-access` | Autenticación del usuario vía OIDC; ciclo de vida del consentimiento de buzones; **custodia exclusiva de los tokens delegados**; emisión de decisiones de autorización | `POST /sesiones`, `POST /buzones`, `DELETE /buzones/{id}`, `POST /autorizaciones/evaluar` | Proveedor de identidad (E-14), bóveda de secretos | RF-01, QA-13, CRN-05 |
| `mail-ingest` | Gestión de suscripciones de notificación, recepción de notificaciones, descarga del mensaje, aplicación de filtros y whitelists. **No interpreta el contenido** | *webhook* entrante; publica `MensajeDeViajeRecibido` | `identity-access` (para obtener un token de uso acotado), proveedores de correo (E-05, E-06) | RF-02, RF-04, QA-01, QA-04 |
| `booking-extraction` | Extracción y normalización de reservas desde mensajes, mediante un registro de extractores por formato, con puntaje de confianza | consume `MensajeDeViajeRecibido`; publica `ReservaExtraida` | — | RF-03, QA-11 |
| `provider-sync` | Adaptadores por proveedor de viaje: obtención de detalles, actualizaciones y cancelaciones; traducción al modelo canónico | *webhook* entrante y trabajos programados; publica `ReservaActualizada`, `ReservaCancelada` | Proveedores (E-07…E-11) | RF-05, QA-10, QA-15 |
| `itinerary` | **Núcleo del dominio.** Custodia del modelo canónico; deduplicación y fusión entre fuentes; agrupación de reservas en viajes; ciclo de vida del viaje; alta, modificación y baja manual | `GET/POST/PUT/DELETE /reservas`, `GET /viajes`; consume los eventos de reserva; publica `ViajeArmado`, `ViajeCompletado` | — | RF-03, RF-06, RF-07, RF-08, RF-09, QA-01, QA-02 |
| `notification` | Decisión de qué notificar y por qué canal; emisión a los servicios de *push*, al correo y al canal interno de la aplicación | consume `ReservaActualizada`, `ReservaCancelada`, `DisrupcionDetectada`; publica `NotificacionEmitida` | Servicios de notificación (E-15) | RF-10, QA-01, QA-04 |
| `sharing` | Compartición de un viaje con una lista de designados, y publicación voluntaria de un resumen sin datos sensibles a redes sociales. **Son dos mecanismos distintos** (AMB-10) | `POST /viajes/{id}/comparticiones`, `POST /viajes/{id}/publicaciones` | `identity-access`, `itinerary`, redes sociales (E-13) | RF-11, RF-13, QA-12 |
| `support-liaison` | Armado del caso de soporte con el contexto del viaje y derivación a la agencia preferida del usuario | `POST /casos` | `itinerary`, `preferences`, agencia (E-12) | RF-12, QA-10 |
| `preferences` | Preferencias del usuario: agencia preferida, idioma, región, zona horaria, política de archivado | `GET/PUT /preferencias` | — | RF-15, QA-18 |

### Elementos del plano analítico

| Elemento | Responsabilidad única | Interfaz | Drivers |
|---|---|---|---|
| `event-pipeline` | Captura del flujo de eventos de dominio y materialización en el almacén analítico | consume todos los eventos de dominio | RF-14, QA-09 |
| `analytics-store` | Almacén columnar con la historia de viajes, optimizado para consultas pesadas | SQL analítico | RF-14, QA-09 |

### Eventos de dominio

Los eventos son la interfaz asíncrona del sistema y, bajo D9, se especifican contractualmente igual
que las APIs sincrónicas.

| Evento | Lo publica | Lo consumen |
|---|---|---|
| `MensajeDeViajeRecibido` | `mail-ingest` | `booking-extraction` |
| `ReservaExtraida` | `booking-extraction` | `itinerary` |
| `ReservaActualizada` | `provider-sync`, `itinerary` | `notification`, `event-pipeline` |
| `ReservaCancelada` | `provider-sync`, `itinerary` | `notification`, `event-pipeline`, `support-liaison` |
| `ViajeArmado` | `itinerary` | `event-pipeline`, *punto de extensión de la 2da entrega* |
| `ViajeCompletado` | `itinerary` | `event-pipeline`, `notification` |
| `DisrupcionDetectada` | `provider-sync` | `notification`, `support-liaison` |
| `NotificacionEmitida` | `notification` | `event-pipeline` |

### El punto de extensión para la 2da entrega

CON-06 obliga a alojar en la 2da entrega la Opción A (recomendación) o la Opción B (asistente
virtual). Las dos consumen lo mismo —el historial de viajes— y las dos producen lo mismo: una
sugerencia o una acción sobre el itinerario o sobre un caso de soporte.

Por eso la estructura las aloja **sin cambios estructurales**: un elemento nuevo que se suscribe a
`ViajeArmado` y `ReservaActualizada`, lee del `analytics-store`, y actúa mediante las interfaces
que `itinerary` y `support-liaison` ya publican. No hace falta ninguna interfaz nueva. Esto se
verifica como criterio de salida de la [iteración 4](../iteracion-4-plan.md).

---

## Paso 6 — Bosquejar vistas y registrar las decisiones de diseño

### Vistas producidas en esta iteración

| Vista | Qué muestra | Enlace |
|---|---|---|
| Contexto | El sistema como caja negra frente a sus 16 interfaces externas | [vista-contexto](../../04-vistas/vista-contexto.md) |
| Módulos — nivel 1 | Descomposición en subsistemas y dependencias permitidas | [vista-modulos-nivel-1](../../04-vistas/vista-modulos-nivel-1.md) |
| Componentes y conectores — nivel 1 | Los elementos en ejecución y los tres tipos de conector | [vista-cyc-nivel-1](../../04-vistas/vista-cyc-nivel-1.md) |
| Despliegue — nivel 1 | Asignación a tres regiones activo-activo | [vista-despliegue-nivel-1](../../04-vistas/vista-despliegue-nivel-1.md) |

### Decisiones registradas

Nueve ADRs en formato MADR, todos en estado `aceptado`:
[ADR-0001](../../03-adr/ADR-0001-estilo-arquitectonico.md) ·
[ADR-0002](../../03-adr/ADR-0002-despliegue-multirregion.md) ·
[ADR-0003](../../03-adr/ADR-0003-separacion-planos.md) ·
[ADR-0004](../../03-adr/ADR-0004-obtencion-de-correo.md) ·
[ADR-0005](../../03-adr/ADR-0005-capa-de-clientes-bff.md) ·
[ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md) ·
[ADR-0007](../../03-adr/ADR-0007-identidad-y-comparticion.md) ·
[ADR-0008](../../03-adr/ADR-0008-alcance-disponibilidad.md) ·
[ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md)

---

## Paso 7 — Analizar el diseño y revisar el logro del objetivo

### → [Paso 7 — Análisis y kanban de drivers](paso-7-analisis.md)

**Veredicto:** el objetivo de la iteración se alcanzó. Los cinco ASRs quedan **habilitados** —
ninguna decisión de esta iteración los vuelve inalcanzables — y 11 de los 53 drivers quedan
completamente tratados. El propósito de diseño global **no** está alcanzado: falta todo el
refinamiento de las iteraciones 2 a 4, y el análisis identifica tres riesgos residuales que la
iteración 3 debe resolver.
