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
| 2026-10-29 | **Iteración 4 de ADD completa y cierre de la 1ra entrega** — interoperabilidad, seguridad/privacidad, evolucionabilidad, uso internacional y verificación del punto de extensión | [Iteración 4](../02-proceso-add/iteracion-4/README.md), [ADR-0027](../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) a [ADR-0035](../03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md), [vista de módulos N2 de adaptadores e identidad](../04-vistas/vista-modulos-adaptadores.md), [vista de seguridad y datos con catálogo de PII](../04-vistas/vista-seguridad-y-datos.md), [guías verificables de extensión (`QA-15` con `tren`, `QA-10`, `QA-18`)](../02-proceso-add/iteracion-4/guias-de-extension.md), verificación en papel de Opción A y B (`CON-06`), cierre de `R-6` y [matriz de trazabilidad al 100 % (58/58 drivers, `0 ⬜`)](../05-trazabilidad/matriz-drivers-decisiones.md) | Juan Emilio Pardo (con revisión del equipo) |
| 2026-11-10 | **Consolidación de artefactos de la iteración 2** que estaban enlazados y no existían | [ADR-0010](../03-adr/ADR-0010-modelo-canonico-reserva-segmento-viaje.md) a [ADR-0017](../03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md) en formato MADR (derivados de D10–D17 sin cambiar las decisiones), [vista de módulos N2](../04-vistas/vista-modulos-nivel-2.md), [secuencias UC-1…UC-7](../04-vistas/secuencias-casos-primarios.md), glosario ampliado, nota de actualización en ADR-0006; se retira el borrador `iteracion-2/verificar-y-borrar.md` | Francisco Lozano |
| 2026-11-10 | **Contratos de interfaz (Spec-driven)** que la iteración 2 declaraba y no estaban en el repositorio | [`contratos/`](../../contratos/README.md): 12 documentos OpenAPI 3.1, AsyncAPI 3.0 con los 16 eventos, contratos de complementos `Extractor` y `AdaptadorDeProveedor`, metaesquema y descriptores de los 5 tipos de segmento, y modelo dimensional SQL. Todos validados con herramientas de la especificación | Francisco Lozano |
| 2026-11-11 | **Inicio de la 2da entrega.** El grupo elige la **Opción B (asistente virtual)** y la tecnología del prototipo | [ADR-0036](../03-adr/ADR-0036-tecnologia-del-prototipo.md), base del [prototipo](../../prototipo/README.md): infraestructura (PostgreSQL + broker), validación en ejecución contra `contratos/` y plan de construcción en 20 pasos | Francisco Lozano |

## Próximos hitos

| Hito | Entregable | Estado |
|---|---|---|
| Iteración 2 — estructuras para la funcionalidad primaria | Diseño completo en `iteracion-2/`, `ADR-0010`…`0017`, vista de módulos N2, secuencias UC-1…UC-7 y `contratos/` | ✅ Completa |
| Iteración 3 — refinamiento para rendimiento, disponibilidad y escalabilidad | Vista de despliegue N2, análisis de presupuestos, modelo de costo, ADRs 0018–0026 y especificación ejecutable de pruebas de carga y SLOs | ✅ Completa |
| Iteración 4 — refinamiento para interoperabilidad, seguridad y evolucionabilidad | Vista de módulos de adaptadores, vista de seguridad y datos, guías de extensión (`tren` / proveedor / región), contratos versionados y ADRs 0027–0035 | ✅ Completa |
| Cierre de 1ra entrega | Revisión de consistencia entre vistas, verificación en papel de Opción A y B (`CON-06`) y matriz de trazabilidad al 100 % (`0` drivers en `⬜`) | ✅ Completa |
| 2da entrega | Módulo avanzado (Opción B: asistente virtual) + prototipo ejecutable trazable | En curso *(ver [plan de construcción](../../prototipo/README.md#plan-de-construcción))* |

## Cambios a drivers después de fijados

Esta tabla debe quedar vacía. Si no lo está, cada fila explica por qué fue necesario tocar un
driver que se había declarado inmutable.

| Fecha | Driver | Cambio | Motivo |
|---|---|---|---|
| — | — | — | — |
