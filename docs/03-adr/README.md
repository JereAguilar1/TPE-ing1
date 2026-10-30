# 3. Decisiones arquitectónicas (ADR)

CON-02 exige que la arquitectura se documente «exhaustivamente utilizando ADRs bajo el formato
MADR». Esta carpeta es el **registro normativo** de las decisiones: cuando esta wiki y un ADR se
contradigan, manda el ADR.

## Reglas de este registro

1. **Un ADR por decisión**, no por tema. Si una página cubre dos decisiones que podrían revertirse
   por separado, son dos ADRs.
2. **Las alternativas descartadas son parte del ADR.** Un ADR que solo dice qué se eligió no sirve:
   lo que tiene valor dentro de un año es saber qué se consideró y por qué se rechazó.
3. **Todo ADR referencia los drivers que atiende** por su identificador (RF-xx, QA-xx, CON-xx,
   CRN-xx). Es la condición de QA-16.
4. **Un ADR aceptado no se edita.** Si la decisión cambia, se escribe uno nuevo que lo *supersede*
   y el viejo pasa a estado `reemplazado`, conservando su contenido. El historial de decisiones es
   parte del entregable.
5. **Toda decisión lleva su campo de confirmación**: cómo se va a verificar que efectivamente se
   implementó. Es lo que conecta el ADR con el prototipo de la 2da entrega (CON-04).

## Estados

| Estado | Significado |
|---|---|
| `propuesto` | Redactado, pendiente de revisión del equipo |
| `aceptado` | Decidido; vinculante para el diseño y el código |
| `reemplazado por ADR-nnnn` | Fue válido, lo reemplazó otra decisión |
| `rechazado` | Se consideró y no se adoptó; se conserva por el razonamiento |

## Índice

### Iteración 1 — Estructura general del sistema

| ADR | Decisión | Estado | Drivers principales |
|---|---|---|---|
| [ADR-0001](ADR-0001-estilo-arquitectonico.md) | Microservicios orientados a eventos con granularidad acotada | `aceptado` | QA-04, QA-09, CON-09, CRN-01, CRN-02 |
| [ADR-0002](ADR-0002-despliegue-multirregion.md) | Despliegue activo-activo en tres regiones | `aceptado` | QA-05, QA-02, QA-18, CRN-08 |
| [ADR-0003](ADR-0003-separacion-planos.md) | Separación del plano operacional y del plano analítico | `aceptado` | QA-09, RF-14, QA-02 |
| [ADR-0004](ADR-0004-obtencion-de-correo.md) | Obtención del correo por notificación *push* con reconciliación | `aceptado` | QA-01, RF-02, CRN-09, AMB-03 |
| [ADR-0005](ADR-0005-capa-de-clientes-bff.md) | Un *backend for frontend* por tipo de cliente | `aceptado` | QA-02, QA-03, QA-17, RF-09 |
| [ADR-0006](ADR-0006-capa-de-anticorrupcion.md) | Capa de anticorrupción con adaptadores como complementos | `aceptado` | QA-10, QA-11, QA-15, CON-07 |
| [ADR-0007](ADR-0007-identidad-y-comparticion.md) | OIDC, delegación OAuth y compartición por lista de designados | `aceptado` | QA-12, QA-13, CON-08, RF-01, RF-11 |
| [ADR-0008](ADR-0008-alcance-disponibilidad.md) | Alcance y forma de medición del objetivo de disponibilidad | `aceptado` | QA-05, QA-06, CRN-03, AMB-02 |
| [ADR-0009](ADR-0009-contratos-spec-driven.md) | Los contratos como artefactos de primera clase | `aceptado` | CON-04, QA-16, CRN-06 |

### Iteración 2 — Estructuras para la funcionalidad primaria

Decisiones `D10` a `D17` (`ADR-0010` a `ADR-0017`: modelo canónico `Reserva`/`Viaje`, extensibilidad de
segmentos, persistencia híbrida relacional, deduplicación y conflictos, idempotencia de ingesta,
bandas de confianza de extracción, modelo dimensional analítico y estrategia de pruebas por
contrato), documentadas con sus alternativas en
[Iteración 2 — Paso 4](../02-proceso-add/iteracion-2/paso-4-alternativas.md) *(archivos MADR individuales en consolidación de equipo)*.

### Iteración 3 — Refinamiento para rendimiento, disponibilidad y escalabilidad

| ADR | Decisión | Estado | Drivers principales |
|---|---|---|---|
| [ADR-0018](ADR-0018-consistencia-datos-multirregion.md) | Consistencia multirregión con región primaria por usuario, testigo transregional y lectura causal | `aceptado` | QA-05, CRN-13, CRN-12, QA-02 |
| [ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md) | Caché multinivel del camino de lectura y optimización de arranque móvil | `aceptado` | QA-02, QA-03, QA-01, RF-09 |
| [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md) | Contrapresión extremo a extremo, colas con prioridad y modos automáticos de degradación | `aceptado` | QA-04, QA-01, QA-02 |
| [ADR-0021](ADR-0021-estrategia-autoescalado.md) | Autoescalado híbrido y separación operativa `itinerary-lectura` / `itinerary-escritura` | `aceptado` | QA-04, QA-08, CRN-08, CON-09 |
| [ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md) | Entrega progresiva canaria por región, reversión automática y migraciones *expand/contract* | `aceptado` | QA-07, CRN-04, QA-05, CON-04 |
| [ADR-0023](ADR-0023-particionamiento-y-crecimiento.md) | Particionamiento por *hash* consistente sobre `usuario_id` (`64` *buckets*), división en línea y archivo frío | `aceptado` | QA-08, QA-02, CRN-08 |
| [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md) | Mamparos, cortacircuitos de ventana deslizante, cola persistente y gobierno de cuotas de terceros | `aceptado` | QA-06, CRN-09, QA-01, RF-02, RF-05 |
| [ADR-0025](ADR-0025-observabilidad-sli-slo-presupuesto-error.md) | Observabilidad con OpenTelemetry, correlación extremo a extremo y gobierno por presupuesto de error | `aceptado` | CRN-03, QA-05, QA-07, CON-09 |
| [ADR-0026](ADR-0026-modelo-costo-y-camino-escalonado.md) | Modelo de costo mensual y camino escalonado en tres etapas sin rediseño estructural | `aceptado` | CRN-08, QA-05, QA-08, QA-09 |

### Iteración 4 — Interoperabilidad, seguridad, evolucionabilidad y uso internacional

| ADR | Decisión | Estado | Drivers principales |
|---|---|---|---|
| [ADR-0027](ADR-0027-versionado-y-evolucion-de-contratos.md) | Evolución compatible de contratos por omisión, negociación de versión mayor y `SemVer` en complementos | `aceptado` | CRN-14, QA-10, QA-15, QA-07, CON-04 |
| [ADR-0028](ADR-0028-autorizacion-comparticion-y-publicacion.md) | Autorización declarativa ABAC con vales firmados, OTP para designados sin cuenta y publicación por lista blanca | `aceptado` | QA-12, QA-14, RF-11, RF-13, AMB-10 |
| [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) | Cifrado por sobres (`KEK_region` / `DEK_u`), custodia mTLS exclusiva, detección `≤ 5 min` y revocación regional `≤ 15 min` | `aceptado` | QA-13, CRN-05, CON-08, RF-01 |
| [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md) | Bitácora de auditoría inmutable y supresión verificable en dos fases sobre ambos planos (`≤ 30 días`) | `aceptado` | QA-14, CON-10, QA-09, CRN-08 |
| [ADR-0031](ADR-0031-residencia-de-datos-por-region.md) | Residencia de datos en tres clases y testigo transregional cifrado bajo custodia jurisdiccional (`R-6` cerrado) | `aceptado` | CRN-15, CON-10, QA-18, QA-05 |
| [ADR-0032](ADR-0032-internacionalizacion-y-localizacion.md) | Dominio neutral al idioma, catálogos ICU externalizados en CDN y formateo local CLDR con `UTC + IANA TZ` | `aceptado` | QA-18, CRN-10, RF-15, QA-03 |
| [ADR-0033](ADR-0033-capacidades-nativas-gps-y-degradacion.md) | Evaluación espacial en el dispositivo móvil con geocodificación previa y degradación automática sin GPS | `aceptado` | QA-17, QA-03, CON-10, RF-09 |
| [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md) | Integración del módulo avanzado de la 2da entrega como elemento autónomo nº 14 y recorte del prototipo por ASRs | `aceptado` | CON-06, CON-05, CON-A4, QA-04 |
| [ADR-0035](ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | Ingesta sin OAuth mediante reenvío verificado / credenciales delegadas y flujo asistido ante formato desconocido | `aceptado` | CON-08, QA-11, QA-13, RF-01, RF-03 |

## Plantilla

→ [plantilla-madr.md](plantilla-madr.md)
