# 1.1 Propósito y alcance

## Propósito del sistema

Trotamundos es un **panel de gestión de viajes en línea** que ofrece a cada viajero un **único
punto de verdad** para todos sus arreglos de viaje —hoteles, autos, vuelos, trenes y autobuses—
en una interfaz centrada en el viaje, accesible desde la web y desde el dispositivo móvil.

El problema que resuelve no es la falta de información, sino su **dispersión**: hoy el viajero
rastrea sus reservas entre múltiples aplicaciones de proveedores y una bandeja de correo llena de
confirmaciones heterogéneas. El valor del sistema está en consolidar eso automáticamente y
mantenerlo actualizado, sobre todo cuando algo se rompe (una cancelación, una disrupción
climática), que es justamente el momento en que el viajero más lo necesita y en que más carga
recibe el sistema.

## Metas de negocio

| ID | Meta de negocio | Atributos de calidad que induce |
|---|---|---|
| MN-1 | Ser el único punto de verdad de los arreglos de viaje del usuario | Interoperabilidad, rendimiento (frescura del dato) |
| MN-2 | Mitigar la frustración de rastrear múltiples aplicaciones y bandejas de correo | Usabilidad, rendimiento |
| MN-3 | Estar disponible precisamente durante las disrupciones de viaje | Disponibilidad, escalabilidad |
| MN-4 | Monetizar datos analíticos de viaje (tendencias, destinos, cancelaciones) | Escalabilidad, rendimiento (aislamiento de carga) |
| MN-5 | Operar en el mercado internacional desde el inicio | Usabilidad e internacionalización, disponibilidad |
| MN-6 | Crecer a 15 M de cuentas con 2 M de usuarios activos semanales | Escalabilidad |
| MN-7 | Expandirse a nuevos medios de transporte sin rediseñar | Evolucionabilidad y mantenibilidad |
| MN-8 | Resolver rápido los problemas del viajero apoyándose en su agencia preferida | Interoperabilidad |

## Alcance

### Dentro del alcance

- Agregación de reservas desde tres fuentes: correo del usuario, APIs de proveedores y alta manual.
- Modelo canónico de reserva/segmento/viaje, agrupación automática por viaje y ciclo de vida del
  viaje (archivado al completarse).
- Panel de consulta web y móvil, con notificación de actualizaciones y disrupciones.
- Compartición de itinerarios con personas designadas y publicación voluntaria a redes sociales.
- Derivación de casos de soporte a la agencia de viajes preferida del usuario.
- Plano analítico para las consultas pesadas del equipo de datos.
- Preparación arquitectónica para operación multirregión e internacionalización.

### Fuera del alcance

| Fuera de alcance | Por qué |
|---|---|
| Venta o emisión de reservas (motor de *booking* propio) | El enunciado describe un panel de gestión, no un canal de venta. El sistema lee y refleja reservas hechas en otros lados |
| Procesamiento de pagos | Consecuencia del punto anterior |
| Sistema interno de la agencia de viajes (CRM, ticketing) | Es un sistema externo; Trotamundos se integra con él, no lo implementa |
| Módulo avanzado — Opción A (recomendación) u Opción B (chatbot) | El enunciado los asigna explícitamente a la **2da entrega**. La arquitectura de esta entrega debe dejar el punto de extensión, no el módulo |
| Prototipo e implementación | Corresponde a la 2da entrega |
| Operación de los proveedores de correo y de viaje | Son sistemas de terceros, con su propio SLA. Esto tiene una consecuencia de diseño importante, tratada en [ADR-0008](../03-adr/ADR-0008-alcance-disponibilidad.md) |

### Deliberadamente diferido

Hay dos cosas que el sistema debe **poder** hacer pero cuyo diseño detallado se posterga:

1. **Trenes y autobuses.** El enunciado los nombra en el punto de verdad unificado y además pide
   prever la integración futura de otros medios de transporte. Se diseña el punto de extensión en
   la iteración 1 y se valida en la iteración 4 ([QA-15](04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte)),
   pero no se construyen los adaptadores concretos.
2. **El módulo avanzado de la 2da entrega.** La arquitectura debe alojarlo sin cambios
   estructurales, lo que es en sí un criterio de evaluación del diseño.

## Propósito de diseño (en el sentido de ADD)

> Diseñar la arquitectura de un sistema nuevo y novedoso (*greenfield*), hasta el nivel de detalle
> suficiente para que un prototipo pueda demostrar la viabilidad de la arquitectura frente a los
> escenarios de calidad más riesgosos.

Esta clasificación importa porque determina el objetivo de la primera iteración: en un sistema
*greenfield* y novedoso, la iteración 1 no puede saltarse el establecimiento de la estructura
general, y no puede apoyarse en una arquitectura de referencia del dominio dada por hecha.
