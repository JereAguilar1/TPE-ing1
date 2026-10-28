# Análisis inicial y pre-requisitos

Esta sección cubre el §3 del enunciado y es el **refinado de la especificación dada**: toma la
narrativa de «Trotamundos» y la convierte en un conjunto de drivers de diseño verificables, que
quedan **inmutables** durante el proceso ADD.

El refinado no es una transcripción. El enunciado contiene huecos y tensiones que hay que resolver
antes de poder diseñar, y la resolución de cada uno está documentada y marcada como tal:

- **Requisitos no verificables** → se refinaron hasta que cada uno tiene una medida numérica
  (por ejemplo, «el tiempo de respuesta desde la web debe ser de 800ms» no dice de qué operación
  ni en qué percentil; ver [AMB-01](07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)).
- **Números faltantes** → se derivaron a partir de los datos que sí da el enunciado, y los
  supuestos usados están etiquetados S-01…S-12.
- **Requisitos en conflicto entre sí** → se identificaron explícitamente y se resolvieron, o se
  dejaron asentados como tensiones que una decisión arquitectónica debe arbitrar.

| Página | Contenido |
|---|---|
| [1.1 Propósito y alcance](01-proposito-y-alcance.md) | Qué es el sistema, qué queda dentro y qué queda fuera |
| [1.2 Diagrama de contexto](02-diagrama-de-contexto.md) | Límites del sistema y sistemas/actores externos |
| [1.3 Requisitos funcionales](03-requisitos-funcionales.md) | RF-01…RF-15 priorizados y casos de uso primarios |
| [1.4 Escenarios de atributos de calidad](04-escenarios-de-calidad.md) | QA-01…QA-18 en formato de 6 partes |
| [1.5 Restricciones](05-restricciones.md) | CON-01…CON-10 |
| [1.6 Inquietudes arquitectónicas](06-concerns-arquitectonicos.md) | CRN-01…CRN-10 |
| [1.7 Supuestos, ambigüedades y carga derivada](07-supuestos-y-carga-derivada.md) | S-01…S-12, AMB-01…AMB-10, presupuestos |
| [1.8 Árbol de utilidad](08-arbol-de-utilidad.md) | Priorización y selección de ASRs |
| [1.9 Glosario y modelo conceptual](09-glosario.md) | Vocabulario del dominio |

## Las cuatro categorías de drivers

ADD toma como entrada cuatro categorías de drivers, más el propósito de diseño. Este es el
inventario completo:

| Categoría | Identificadores | Cantidad |
|---|---|---|
| Requisitos funcionales primarios | RF-01…RF-15 (9 marcados como primarios) | 15 |
| Escenarios de atributos de calidad | QA-01…QA-18 | 18 |
| Restricciones | CON-01…CON-10 | 10 |
| Inquietudes arquitectónicas | CRN-01…CRN-10 | 10 |
