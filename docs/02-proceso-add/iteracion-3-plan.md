# Iteración 3 — Refinar para rendimiento, disponibilidad y escalabilidad

> **Estado:** 📋 Planificada · **Responsable de coordinación:** Francisco Lozano

Esta es la iteración donde se resuelven **dos de los tres riesgos residuales** de la iteración 1
(R-1 y R-3) y donde los presupuestos derivados pasan de cerrar en papel a cerrar con mediciones.

## Paso 1 — Entradas

Lo anterior, más las estructuras internas y los contratos de la iteración 2. La iteración 3 **no
puede empezar antes** de la 2: las tácticas de rendimiento y disponibilidad se aplican sobre
elementos concretos, y hasta la iteración 2 esos elementos no tienen interior.

## Paso 2 — Objetivo de la iteración

> Refinar las estructuras existentes aplicando tácticas de rendimiento, disponibilidad y
> escalabilidad, hasta que los presupuestos derivados en el análisis inicial sean verificables y el
> riesgo de consistencia entre regiones esté resuelto.

### Drivers que consume

| Driver | Estado tras la iteración 1 | Qué debe lograr esta iteración |
|---|---|---|
| QA-01 | 🟨 | Verificar el [presupuesto de frescura](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-frescura-5-minutos) con mediciones; definir intervalos de reconciliación y el objetivo propio de los buzones sin *push* |
| QA-02 | 🟨 | Tácticas de caché multinivel; verificar el presupuesto de 800 ms con pruebas de carga |
| QA-03 | 🟨 | Diseño del arranque de la aplicación móvil y de la carga diferida |
| QA-04 | 🟨 | Contrapresión, colas con prioridad, autoescalado (incluido el predictivo por calendario de picos) |
| QA-05 | 🟨 | **Resolver R-1:** modelo de consistencia entre regiones |
| QA-06 | 🟨 | Umbrales de cortacircuitos, políticas de reintento, retroceso exponencial y cola de pendientes |
| QA-07 | ⬜ | Despliegue progresivo, reversión automática, compatibilidad de esquemas |
| QA-08 | ⬜ | Particionamiento y plan de crecimiento a 30 M de cuentas |
| QA-09 | 🟩 | Verificar con medición la degradación < 5 % |
| CRN-03 | 🟨 | Instrumentación, indicadores de nivel de servicio y tablero de presupuesto de error |
| CRN-04 | ⬜ | Despliegue continuo sin inactividad |
| CRN-08 | 🟨 | **Resolver R-3:** modelo de costo y camino escalonado |
| CRN-09 | 🟨 | Límites de tasa por proveedor y comportamiento al alcanzarlos |
| CRN-13 | nuevo | Consistencia entre regiones (es la cara técnica de R-1) |

## Paso 3 — Elementos a refinar

El camino de lectura completo, el plano de ingesta, el plano de datos operacional y la topología de
despliegue. Es la iteración con el alcance más transversal.

## Paso 4 — Conceptos de diseño a evaluar

### Consistencia entre regiones — la decisión central (R-1 / CRN-13)

| Alternativa | Qué implica |
|---|---|
| Partición por usuario con región de origen | Cada usuario tiene una región dueña de sus escrituras; las otras sirven lecturas. Simple de razonar, pero el usuario que viaja escribe con latencia transoceánica |
| Tipos de datos convergentes para la fusión | Las escrituras concurrentes se fusionan de forma determinista sin coordinación. Potente, pero exige que el modelo canónico sea fusionable, lo que condiciona la iteración 2 |
| Consenso entre regiones para las escrituras | Consistencia fuerte, al costo de una ronda de consenso transoceánica por escritura: incompatible con el presupuesto de latencia |
| Consistencia causal con marcas de versión | Punto intermedio: el usuario nunca ve su propia escritura desaparecer |

### Otros conceptos a evaluar

| Decisión | Alternativas |
|---|---|
| Caché del camino de lectura | Caché en el borde · caché distribuida · caché en proceso · combinación por nivel, con política de invalidación por evento |
| Comportamiento ante sobrecarga (QA-04) | Rechazo con reintento sugerido · encolado con prioridad · degradación por nivel de servicio · descarte selectivo de carga |
| Autoescalado | Reactivo por métrica · predictivo por calendario de picos conocidos · combinación |
| Despliegue (QA-07) | Progresivo por porcentaje de tráfico · por región · azul-verde · combinación |
| Particionamiento (QA-08) | Por identificador de usuario · por región · jerárquico |
| Camino escalonado de costo (R-3) | Dos regiones activas más una de solo datos · tres regiones con capacidad asimétrica · plano analítico en modalidad de pago por consulta |

## Paso 6 — Artefactos esperados

| Artefacto | Contenido |
|---|---|
| Vista de despliegue nivel 2 | Dimensionamiento, autoescalado, topología del plano de datos entre regiones |
| Verificación de presupuestos | Cada tramo de los [tres presupuestos](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuestos-derivados) con su valor medido o estimado y su justificación |
| Especificación de pruebas de carga | Escenarios de QA-02, QA-04 y QA-09 como pruebas ejecutables, con criterios de aceptación |
| Catálogo de indicadores de nivel de servicio | Un indicador y un objetivo por función crítica de [ADR-0008](../03-adr/ADR-0008-alcance-disponibilidad.md) |
| Modelo de costo | Costo mensual estimado de la topología, y del camino escalonado |

## ADRs previstos

| ADR | Tema | Driver principal |
|---|---|---|
| ADR-0018 | Modelo de consistencia de datos entre regiones | QA-05, CRN-13, **R-1** |
| ADR-0019 | Estrategia de caché del camino de lectura | QA-02 |
| ADR-0020 | Contrapresión y comportamiento ante sobrecarga | QA-04 |
| ADR-0021 | Estrategia de autoescalado | QA-04, QA-08 |
| ADR-0022 | Estrategia de despliegue progresivo y reversión | QA-07, CRN-04 |
| ADR-0023 | Particionamiento de datos y plan de crecimiento | QA-08 |
| ADR-0024 | Políticas de cortacircuitos, reintento y cola de pendientes | QA-06, CRN-09 |
| ADR-0025 | Observabilidad, indicadores de nivel de servicio y presupuesto de error | CRN-03 |
| ADR-0026 | Camino escalonado de infraestructura y su costo | CRN-08, **R-3** |

## Criterios de salida

1. **R-1 resuelto:** hay una decisión de consistencia entre regiones que satisface QA-05 con cero
   pérdida de datos confirmados, y está registrada en un ADR.
2. **R-3 resuelto:** hay un modelo de costo y un camino escalonado que no exige rediseñar la
   estructura.
3. Los tres presupuestos (latencia, frescura, error) tienen cada tramo justificado con un número.
4. QA-01 a QA-09 están en 🟩, o el motivo de no estarlo está documentado.
5. Los escenarios QA-02, QA-04 y QA-09 existen como especificación de prueba ejecutable.

## Riesgo propio de esta iteración

Si la decisión de consistencia entre regiones (R-1) obliga a cambiar el modelo canónico —por
ejemplo, si la fusión sin coordinación exige que las entidades sean estructuras convergentes— habrá
**retrabajo sobre la iteración 2**. Mitigación: evaluar la fusionabilidad del modelo canónico ya en
la iteración 2, como entrada anticipada de esta decisión. Es la razón por la que la iteración 2
debe considerar explícitamente la alternativa de «agregados con límites transaccionales explícitos».
