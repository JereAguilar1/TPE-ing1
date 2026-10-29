# Bitácora de evolución

Registro fechado del avance del trabajo. El propósito es doble: mostrar la evolución del diseño
(y no solo su estado final) y dejar constancia de la labor de cada integrante, como pide el §4 del
enunciado.

| Fecha | Hito | Artefactos producidos | Responsables |
|---|---|---|---|
| 2026-10-24 | Creación del repositorio y de la estructura de la wiki | `README.md`, `docs/Home.md`, `docs/_Sidebar.md` | Jeremias Aguilar |
| 2026-10-24 | **Refinado de la especificación dada.** Se convirtió la narrativa del enunciado en drivers verificables y se dejaron explícitas las ambigüedades, los supuestos y la carga derivada | Todo el [análisis inicial](../01-analisis-inicial/) (§1.1 a §1.9): alcance, contexto, RF-01…RF-15, QA-01…QA-18, CON-01…CON-10, CRN-01…CRN-10, supuestos S-01…S-12, ambigüedades AMB-01…AMB-10, árbol de utilidad | Los cuatro integrantes |
| 2026-10-24 | **Iteración 1 de ADD completa** — establecimiento de la estructura general del sistema | [Iteración 1](../02-proceso-add/iteracion-1/README.md), ADR-0001 a ADR-0009, vistas de contexto, módulos N1, C&C N1 y despliegue N1, kanban de drivers | Los cuatro integrantes |
| 2026-10-24 | Planificación de las iteraciones 2, 3 y 4 | [Plan de iteraciones](plan-de-iteraciones.md) y las páginas de plan de cada iteración | Jeremias Aguilar |
| 2026-10-28 | **Iteración 2 de ADD completa** — estructuras para la funcionalidad primaria | [Iteración 2](../02-proceso-add/iteracion-2/README.md), alternativas `D10`–`D17`, descomposición interna de `itinerary` y del plano de ingesta, recorridos `UC-1`…`UC-7` y kanban actualizado (55 drivers) | Francisco Lozano (con revisión del equipo) |
| 2026-10-29 | **Iteración 3 de ADD completa** — refinamiento para rendimiento, disponibilidad y escalabilidad | [Iteración 3](../02-proceso-add/iteracion-3/README.md), [ADR-0018](../03-adr/ADR-0018-consistencia-datos-multirregion.md) a [ADR-0026](../03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md), [vista de despliegue N2](../04-vistas/vista-despliegue-nivel-2.md), verificación tramo por tramo de presupuestos, modelo de costo en 3 etapas, [especificación de pruebas de carga y catálogo de SLOs](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md), cierre de riesgos `R-1`, `R-3`, `R-4` y `R-5` y kanban en 56 drivers | Ivo Iriarte (con revisión del equipo) |

## Próximos hitos

| Hito | Entregable | Estado |
|---|---|---|
| Iteración 2 — estructuras para la funcionalidad primaria | Diseño completo en `iteracion-2/`; resta materializar archivos externos (`ADR-0010`…`0017`, vistas N2 de módulos/secuencias y `contratos/`) | En consolidación |
| Iteración 3 — refinamiento para rendimiento, disponibilidad y escalabilidad | Vista de despliegue N2, análisis de presupuestos, modelo de costo, ADRs 0018–0026 y especificación ejecutable de pruebas de carga y SLOs | ✅ Completa |
| Iteración 4 — refinamiento para interoperabilidad, seguridad y evolucionabilidad | Vista de seguridad y datos, guía de extensión de transportes, contratos versionados y ADRs 0027–0035 | Pendiente *(lista para iniciar)* |
| Cierre de 1ra entrega | Revisión de consistencia final y matriz de trazabilidad al 100 % | Pendiente |
| 2da entrega | Selección del módulo avanzado (A o B) + prototipo trazable | Pendiente |

## Cambios a drivers después de fijados

Esta tabla debe quedar vacía. Si no lo está, cada fila explica por qué fue necesario tocar un
driver que se había declarado inmutable.

| Fecha | Driver | Cambio | Motivo |
|---|---|---|---|
| — | — | — | — |
