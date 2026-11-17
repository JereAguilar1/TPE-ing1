# Iteración 5 — Paso 7: análisis del diseño

> Volver a la [iteración 5](README.md).

## Criterios de salida

| # | Criterio | Resultado | Evidencia |
|---|---|---|---|
| 1 | Cada decisión del interior del asistente tiene su ADR en MADR | ✅ Cumplido | [ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md) a [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md), más [ADR-0041](../../03-adr/ADR-0041-alias-de-reenvio-generado-por-identity-access.md) por una inconsistencia de ADR-0035 |
| 2 | El asistente tiene contrato antes de tener código (`CON-04`) | ✅ Cumplido | [`virtual-assistant.yaml`](../../../contratos/openapi/virtual-assistant.yaml) 1.0.0, validado con `openapi-spec-validator` |
| 3 | Cero interfaces nuevas en servicios existentes (`CON-06`) | ✅ Cumplido | Solo usa `GET /panel`, `GET /viajes`, `GET /viajes/{id}`, `PUT /reservas/{id}`, `POST /reservas/{id}/confirmacion`, `POST /reservas/{id}/conflictos/{cid}/resolucion` y `POST /casos`, sin cambios; el contrato de eventos solo suma un consumidor |
| 4 | `RF-B1` y `RF-B2` quedan trazados a decisiones | ✅ Cumplido | Kanban de abajo |
| 5 | El paso 19 del prototipo puede empezar sin inventar decisiones | ✅ Cumplido | [Vistas, intenciones y secuencias](README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces) y la [guía de entrada](#guía-de-entrada-para-el-paso-19) |
| 6 | El elemento nº 14 respeta las reglas de consistencia entre vistas y de dependencia | ✅ Cumplido | [Verificación de consistencia](#verificación-de-consistencia-entre-vistas) |

## Estado de los cinco ASR

La iteración 5 no cambia ninguno: el asistente es un consumidor más de lo que ya existía.

| ASR | Estado | Por qué esta iteración no lo afecta |
|---|---|---|
| **ASR-1** `QA-01` frescura `≤ 5 min` | = | El asistente lee el itinerario; no participa del camino de ingesta |
| **ASR-2** `QA-04` pico de disrupción | = | Es carga degradable de prioridad 2/3 con su propio mamparo ([ADR-0020](../../03-adr/ADR-0020-contrapresion-y-sobrecarga.md)); ante `Disrupción masiva` cede recursos a `itinerary` |
| **ASR-3** `QA-05` pérdida de una región | = | Lo que el viajero confirma va por `itinerary`, con su testigo síncrono; perder una conversación en curso es aceptable ([vista de despliegue](../../04-vistas/vista-despliegue-asistente.md)) |
| **ASR-4** `QA-11` formato de correo desconocido | = | No toca la extracción; ayuda a confirmar las reservas de banda media, que es el final del flujo de QA-11 ([ADR-0038](../../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md)) |
| **ASR-5** `QA-13` custodia de tokens de correo | = | No accede a la bóveda (regla R5) ni ve tokens de correo |

## Verificación de consistencia entre vistas

### 1. Las cinco reglas de consistencia transversal ([docs/04-vistas/README.md](../../04-vistas/README.md#reglas-de-consistencia-entre-vistas))

| Regla | ¿Se cumple para el elemento nº 14? | Evidencia |
|---|---|---|
| **1.** Todo módulo tiene un componente que lo realiza | ✅ | Los siete módulos de la [vista de módulos](../../04-vistas/vista-modulos-asistente.md) los realiza el componente `virtual-assistant` de la [vista C&C](../../04-vistas/vista-cyc-asistente.md) |
| **2.** Todo componente tiene un destino de despliegue | ✅ | `virtual-assistant` corre en la región primaria del viajero, en las tres regiones ([vista de despliegue](../../04-vistas/vista-despliegue-asistente.md)) |
| **3.** Toda dependencia entre módulos es un conector o es interna | ✅ | `contexto`, `acciones` y `derivacion` → conectores HTTP a `itinerary-lectura`, `itinerary-escritura` y `support-liaison`; `contexto` ← conector del *broker*. El resto es interno al componente |
| **4.** Toda interfaz externa del diagrama de contexto tiene un responsable | ✅ | El asistente no agrega interfaces externas. Si se enchufa un modelo de lenguaje ([ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md)), será una interfaz externa nueva, a cargo del complemento del intérprete, y entonces se agrega al diagrama de contexto |
| **5.** Toda interfaz entre componentes tiene contrato y regla de evolución | ✅ | [`virtual-assistant.yaml`](../../../contratos/openapi/virtual-assistant.yaml) 1.0.0, `itinerary.yaml`, `support-liaison.yaml` y AsyncAPI 1.5.0, todos bajo [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) |

### 2. Las siete reglas de dependencia ([vista-modulos-nivel-1](../../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia))

| Regla | ¿Se cumple? | Evidencia |
|---|---|---|
| **R1** De arriba hacia abajo en las capas | ✅ | El asistente está entre la composición y el dominio: lo llama `bff-web` y él llama a `itinerary` y a `support-liaison`, nunca al revés |
| **R2** Anticorrupción y dominio no se conocen | ✅ | El asistente no es de ninguna de las dos capas: es el punto de extensión de [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md), que lo autoriza a usar las dos por sus contratos |
| **R3** Ningún módulo de dominio importa un tipo externo | ✅ | Los tipos de un modelo de lenguaje quedan dentro de su complemento ([ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md)) |
| **R4** Los BFF no tienen lógica de dominio | ✅ | `bff-web` solo reenvía la sesión y el mensaje; toda la lógica del diálogo está en el asistente |
| **R5** Solo `identity-access` accede a la bóveda | ✅ | El asistente no tiene ninguna dependencia hacia la bóveda |
| **R6** El plano analítico no depende del operacional | ✅ | El asistente no participa del plano analítico |
| **R7** `modelo-canonico` no depende de nada | ✅ | El asistente no lo modifica |

## Kanban de los drivers que toca esta iteración

🟩 atendido en el diseño · 🟨 atendido en parte · ⬜ sin atender. «En código» indica en qué paso del
[plan del prototipo](../../../prototipo/README.md#plan-de-construcción) se construye.

La [matriz de trazabilidad](../../05-trazabilidad/matriz-drivers-decisiones.md) de la 1ra entrega quedó
cerrada con los 58 drivers de entonces y no se modifica: esta tabla la **extiende** con los drivers de
la Opción B (`RF-B1`, `RF-B2`) y con los que esta iteración vuelve a tocar.

| Driver | Antes | Después | Qué lo atiende | En código |
|---|---|---|---|---|
| **RF-B1** Consultas, reprogramaciones y problemas menores | ⬜ | 🟩 | Intenciones (D37); consultas directas, corrección confirmada del itinerario y problemas menores (reservas por confirmar y conflictos entre fuentes) con confirmación (D38) | Paso 19 |
| **RF-B2** Derivar solo lo que el bot no resuelve | ⬜ | 🟩 | Cuatro disparadores con confirmación y caso idempotente (D39) | Pasos 12 y 19 |
| **CON-06** Alojar el módulo avanzado | 🟨 | 🟩 | Interior diseñado y contrato publicado sobre la frontera de ADR-0034 | Paso 19 |
| **CON-04** *Spec-driven* | 🟩 | = | Contrato del asistente antes del código | Paso 19 |
| **CON-01** Iteraciones de ADD | 🟩 | = | Quinta iteración, aprobada por el profesor para la 2da entrega | — |
| **QA-14 / CON-10** Datos personales | 🟩 | = | Nada a terceros en el prototipo, redacción si se enchufa un modelo (D37), retención y supresión de fase 1 (D40) | Paso 19 (retención); la supresión de fase 1, en «Para completar el 100 %» |
| **QA-12** Solo el titular ve lo suyo | 🟩 | = | Sesión del viajero en cada llamada; sesiones y reservas ajenas responden `404` (D38, D40) | Paso 19 |
| **QA-04** Degradación ante picos | 🟩 | = | El asistente es carga de prioridad 2/3 (D40, ADR-0020) | — |
| **QA-18 / CRN-10** Internacionalización | 🟩 | = | Patrones y mensajes en catálogos por idioma, sin textos fijos en el código (D37, ADR-0032) | Paso 19, solo con el catálogo en español |
| **CON-A4** Menos de 15 elementos | 🟩 | = | `13` servicios + el nº 14 = `14 < 15` | — |

## Inconsistencias encontradas en la 1ra entrega

AGENTS.md pide informarlas y no corregirlas: la 1ra entrega ya se presentó. Se registran acá y, cuando
afectan una decisión, se resuelven con un ADR nuevo.

| Dónde | Qué dice | Qué pasa | Cómo se resuelve |
|---|---|---|---|
| [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md), punto 2 | El módulo avanzado «suscribe `CuentaSuprimida` para borrar su estado propio» | `CuentaSuprimida` no trae `usuarioId` por diseño ([ADR-0030](../../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md)): el asistente no sabría qué borrar | [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) lo precisa: el asistente entra en la fase 1 de ADR-0030 (borrado ordenado por `usuario_id`). El contrato de eventos deja de listar al «elemento 14» como consumidor de `CuentaSuprimida` y de `ViajeArmado` |
| [ADR-0035](../../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | «`mail-ingest` asigna un alias» de reenvío | En el contrato `identity-access.yaml` el alias lo devuelve `identity-access` al conectar el buzón, y así está construido (paso 7) | [ADR-0041](../../03-adr/ADR-0041-alias-de-reenvio-generado-por-identity-access.md) lo precisa: el alias lo genera `identity-access` y `mail-ingest` lo recibe por `EstadoDeBuzonCambiado`, como dicen los contratos |

## Riesgos

| Riesgo | Qué puede pasar | Mitigación |
|---|---|---|
| **R-B1** Comprensión limitada | Las reglas no entienden frases fuera de los patrones previstos | Repregunta por debajo de 0,6 y derivación a los dos malentendidos (D37, D39); el modelo de lenguaje queda enchufable |
| **R-B2** Corrección sobre una reserva que cambió | El viajero confirma un cambio basado en datos viejos | Confirmación con la versión leída; un `409` de `itinerary` lleva a una propuesta nueva (D38) |
| **R-B3** Supresión pendiente | El borrado ordenado de la fase 1 no está construido en el prototipo para ningún servicio | La retención de 30 días borra las sesiones igual (D40); el borrado ordenado queda en «Para completar el 100 %» del plan |

## Guía de entrada para el paso 19

Lo que recibe listo quien construya el asistente, y en qué orden conviene hacerlo:

| Orden | Qué construir | Dónde está decidido | Depende de |
|---|---|---|---|
| 1 | El servicio con su contrato, sus sesiones y la verificación de la sesión del viajero | [`virtual-assistant.yaml`](../../../contratos/openapi/virtual-assistant.yaml), [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) | — |
| 2 | El intérprete por reglas y los catálogos en español | [ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md), [§5.2](README.md#52-intenciones-que-entiende) | — |
| 3 | Consultas de estado y próximo tramo | [ADR-0038](../../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md) | `itinerary` (ya construido) |
| 4 | Acciones con confirmación: corrección y problemas menores | [ADR-0038](../../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md) | `itinerary` (ya construido) |
| 5 | Derivación a la agencia | [ADR-0039](../../03-adr/ADR-0039-politica-de-derivacion-a-la-agencia.md) | `support-liaison` (paso 12) |
| 6 | Consumo de `DisrupcionDetectada` | [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) | El evento lo publica `provider-sync` (paso 10); sin él, las pruebas lo inyectan en el *broker* |

**Qué queda afuera del paso 19:** el adaptador de modelo de lenguaje (diseñado, no construido) y la
supresión de fase 1 por `usuario_id`, que se construye con la del resto del plano operacional. Las
pruebas que confirman cada decisión están en la sección «Confirmación» de su ADR.
