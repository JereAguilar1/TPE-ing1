# Iteración 5 — Paso 7: análisis del diseño

> Volver a la [iteración 5](README.md).

## Criterios de salida

| # | Criterio | Resultado | Evidencia |
|---|---|---|---|
| 1 | Cada decisión del interior del asistente tiene su ADR en MADR | ✅ Cumplido | [ADR-0037](../../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md) a [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) |
| 2 | El asistente tiene contrato antes de tener código (`CON-04`) | ✅ Cumplido | [`virtual-assistant.yaml`](../../../contratos/openapi/virtual-assistant.yaml) 1.0.0, validado con `openapi-spec-validator` |
| 3 | Cero interfaces nuevas en servicios existentes (`CON-06`) | ✅ Cumplido | Solo usa `GET /viajes`, `GET /viajes/{id}`, `PUT /reservas/{id}` y `POST /casos`, sin cambios; el contrato de eventos solo suma un consumidor |
| 4 | `RF-B1` y `RF-B2` quedan trazados a decisiones | ✅ Cumplido | Kanban de abajo |
| 5 | El paso 19 del prototipo puede empezar sin inventar decisiones | ✅ Cumplido | [Vista de módulos, intenciones y secuencias](README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces) |

## Kanban de los drivers que toca esta iteración

🟩 atendido en el diseño · 🟨 atendido en parte · ⬜ sin atender. «En código» indica en qué paso del
[plan del prototipo](../../../prototipo/README.md#plan-de-construcción) se construye.

| Driver | Antes | Después | Qué lo atiende | En código |
|---|---|---|---|---|
| **RF-B1** Consultas, reprogramaciones y problemas menores | ⬜ | 🟩 | Intenciones (D37), consultas directas y corrección confirmada (D38) | Paso 19 |
| **RF-B2** Derivar solo lo que el bot no resuelve | ⬜ | 🟩 | Cuatro disparadores con confirmación y caso idempotente (D39) | Pasos 12 y 19 |
| **CON-06** Alojar el módulo avanzado | 🟨 | 🟩 | Interior diseñado y contrato publicado sobre la frontera de ADR-0034 | Paso 19 |
| **CON-04** *Spec-driven* | 🟩 | = | Contrato del asistente antes del código | Paso 19 |
| **CON-01** Iteraciones de ADD | ✅ | = | Quinta iteración, aprobada por el profesor para la 2da entrega | — |
| **QA-14 / CON-10** Datos personales | 🟩 | = | Nada a terceros en el prototipo, redacción si se enchufa un modelo (D37), retención y supresión de fase 1 (D40) | Paso 19 (retención); la supresión de fase 1, en «Para completar el 100 %» |
| **QA-12** Solo el titular ve lo suyo | 🟩 | = | Sesión del viajero en cada llamada; sesiones y reservas ajenas responden `404` (D38, D40) | Paso 19 |
| **QA-04** Degradación ante picos | 🟩 | = | El asistente es carga de prioridad 2/3 (D40, ADR-0020) | — |
| **CON-A4** Menos de 15 elementos | 🟩 | = | `13` servicios + el nº 14 = `14 < 15` | — |

## Inconsistencias encontradas en la 1ra entrega

AGENTS.md pide informarlas y no corregirlas: la 1ra entrega ya se presentó. Se registran acá y, cuando
afectan una decisión, se resuelven con un ADR nuevo.

| Dónde | Qué dice | Qué pasa | Cómo se resuelve |
|---|---|---|---|
| [ADR-0034](../../03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md), punto 2 | El módulo avanzado «suscribe `CuentaSuprimida` para borrar su estado propio» | `CuentaSuprimida` no trae `usuarioId` por diseño ([ADR-0030](../../03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md)): el asistente no sabría qué borrar | [ADR-0040](../../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) lo precisa: el asistente entra en la fase 1 de ADR-0030 (borrado ordenado por `usuario_id`). El contrato de eventos deja de listar al «elemento 14» como consumidor de `CuentaSuprimida` y de `ViajeArmado` |
| [ADR-0035](../../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) | «`mail-ingest` asigna un alias» de reenvío | En el contrato `identity-access.yaml` el alias lo devuelve `identity-access` al conectar el buzón, y así está construido (paso 7) | No afecta una decisión: el contrato manda (AGENTS.md). Registrado en las decisiones de implementación del prototipo |

## Riesgos

| Riesgo | Qué puede pasar | Mitigación |
|---|---|---|
| **R-B1** Comprensión limitada | Las reglas no entienden frases fuera de los patrones previstos | Repregunta por debajo de 0,6 y derivación a los dos malentendidos (D37, D39); el modelo de lenguaje queda enchufable |
| **R-B2** Corrección sobre una reserva que cambió | El viajero confirma un cambio basado en datos viejos | Confirmación con la versión leída; un `409` de `itinerary` lleva a una propuesta nueva (D38) |
| **R-B3** Supresión pendiente | El borrado ordenado de la fase 1 no está construido en el prototipo para ningún servicio | La retención de 30 días borra las sesiones igual (D40); el borrado ordenado queda en «Para completar el 100 %» del plan |
