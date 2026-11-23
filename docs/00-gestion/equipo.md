# Equipo y responsabilidades

## Integrantes

| Integrante | Rol principal en el diseño | Foco |
|---|---|---|
| Jeremias Aguilar | Coordinación de arquitectura y ADRs | Estructura general, trazabilidad, consistencia entre vistas y decisiones |
| Francisco Lozano | Rendimiento, escalabilidad y despliegue | Presupuestos de latencia, dimensionamiento, topología multirregión |
| Juan Emilio Pardo | Interoperabilidad e integración | Adaptadores de proveedores, contratos, ingesta de correo |
| Ivo Iriarte | Seguridad, privacidad y modelo de dominio | Identidad, delegación OAuth, compartición, modelo canónico de viaje |

Los roles indican **quién lidera** cada área, no quién trabaja en exclusiva: toda decisión
arquitectónica se revisa entre los cuatro antes de pasar un ADR a estado `aceptado`.

## Reparto de trabajo por iteración

| Iteración | Jeremias Aguilar | Francisco Lozano | Juan Emilio Pardo | Ivo Iriarte |
|---|---|---|---|---|
| Análisis inicial | Alcance, contexto, árbol de utilidad | Carga derivada y presupuestos | Requisitos funcionales, interoperabilidad | Escenarios de seguridad, glosario |
| Iteración 1 | Estructura general, ADR-0001/0008/0009 | ADR-0002, vista de despliegue | ADR-0004/0006, vista C&C | ADR-0005/0007, vista de módulos |
| Iteración 2 | Modelo canónico y ciclo de vida del viaje | Persistencia y particionamiento | Extracción y normalización de reservas | Diagramas de secuencia de los casos primarios |
| Iteración 3 | Revisión de consistencia y kanban de drivers | Tácticas de rendimiento y escalabilidad | Backpressure y cuotas de terceros | Tácticas de disponibilidad y degradación |
| Iteración 4 | Guía de extensión y trazabilidad final | Residencia de datos y multirregión | Versionado de contratos y nuevos transportes | Cifrado, bóveda de tokens, auditoría |
| Iteración 5 | Decisiones D37 a D41 (ADR-0037 a ADR-0041) | Responsable de la iteración: plan, alternativas, ADR, contrato `virtual-assistant.yaml` y vistas del asistente; decisiones D37 a D41 | Decisiones D37 a D41 | Decisiones D37 a D41 |
| Prototipo (2da entrega) | Paso 7: `identity-access` (sesiones, buzones, bóveda, ABAC y auditoría) | Pasos 1 a 6, 8, 12, 13 y 15 a 21; la versión completa de los pasos 9, 10, 11 y 14; revisión y correcciones de los pasos 1 a 7 | Paso 9 (recorte): `booking-extraction` | Pasos 10, 11 y 14 (recorte): `provider-sync`, `bff-web` y `event-pipeline` |

La tecnología del prototipo ([ADR-0036](../03-adr/ADR-0036-tecnologia-del-prototipo.md)) la
decidieron los cuatro. El detalle de cada paso del prototipo, con quién lo hizo, está en la columna
«Responsable» del [plan de construcción](../../prototipo/README.md#plan-de-construcción) y en la
[bitácora](bitacora.md); los commits de cada integrante, en el historial del repositorio.

## Convenciones de trabajo

- **Un commit por artefacto cerrado.** El mensaje nombra el artefacto y el identificador de los
  drivers involucrados, por ejemplo: `docs(iter1): ADR-0002 despliegue activo-activo (QA-05, QA-18)`.
- **Autoría visible.** Cada integrante commitea su propio trabajo con su cuenta, de modo que el
  historial del repositorio sea la evidencia de la labor individual que pide el enunciado (§4).
- **Los ADR no se editan una vez aceptados.** Si una decisión cambia, se crea un ADR nuevo que
  *supersede* al anterior y se actualiza el estado del viejo. El historial de decisiones es parte
  del entregable.
- **Los drivers son inmutables.** Los identificadores RF-xx, QA-xx, CON-xx y CRN-xx fijados en el
  análisis inicial no se renumeran ni se reinterpretan después. Si hace falta cambiar un driver,
  se documenta como cambio explícito en la [bitácora](bitacora.md).
