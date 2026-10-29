---
estado: aceptado
fecha: 2026-10-29
decisores: Francisco Lozano, Jeremias Aguilar, Ivo Iriarte, Juan Emilio Pardo
consultados: —
informados: equipo completo
iteracion: 3
drivers: CRN-08, QA-05, QA-08, QA-09, CON-09
---

# ADR-0026: Modelo de costo mensual y camino escalonado en tres etapas sin rediseño estructural

## Contexto y planteo del problema

La iteración 1 dejó explícito el riesgo **`R-3`** ([iteración 1, paso 7](../02-proceso-add/iteracion-1/paso-7-analisis.md#riesgos-residuales)):
para satisfacer `QA-05` (`99,9884 %`, caída de una región entera sin perder datos confirmados) y
`QA-09` (aislamiento del plano analítico), la arquitectura define tres regiones activas y un almacén
columnar separado ([ADR-0002](ADR-0002-despliegue-multirregion.md), [ADR-0003](ADR-0003-separacion-planos.md)).
Dimensionada de entrada para los `15 millones` de cuentas y `3.000 req/s` del enunciado, esa huella
ronda los **`USD 28.500/mes`**.

Para una *startup* que aún está validando su tracción comercial (`CRN-08`), afrontar `USD 28.500/mes`
desde el día uno es financieramente riesgoso; pero la reacción opuesta —lanzar un monolito en una
sola región sin particionamiento y mezclar OLTP con analítica «para ahorrar hoy»— destruye `QA-05` y
condena a un equipo de `4` personas (`CON-09`) a reescribir la plataforma entera justo cuando empiece
a crecer.

## Drivers de decisión

* **CRN-08 (`R-3`)** — viabilidad económica para una *startup* sin comprometer la evolución.
* **QA-05** — sostener la tolerancia a caída regional y `RPO = 0` desde el lanzamiento.
* **QA-08** — escalar de `15 M` a `30 M` de cuentas con crecimiento de costo `≤ lineal` respecto de
  los usuarios activos semanales.
* **QA-09** — mantener el plano analítico físicamente aislado del plano operacional en todas las
  etapas.
* **CON-09** — transiciones entre etapas ejecutables por `4` ingenieros mediante cambios declarativos,
  sin migraciones arquitectónicas.

## Opciones consideradas

* **Z1** — Desplegar las tres regiones simétricas a capacidad plena de `15 M` de cuentas desde el
  primer día.
* **Z2** — Lanzar en una sola región con base única compartida y rediseñar la arquitectura al crecer.
* **Z3** — Camino evolutivo en **tres etapas de capacidad** sobre exactamente la misma arquitectura de
  software (`13 + 2` elementos, contratos, particionamiento de `64` *buckets* y modelo `D18`).

## Resultado de la decisión

Se adopta **Z3**, gobernando la evolución exclusivamente mediante parámetros de infraestructura como
código (IaC):

1. **Etapa 1 — Lanzamiento y validación comercial (`≤ 1,5 M` cuentas · `200 K` WAU · `~USD 4.800/mes`):**
   * **Dos regiones de aplicación activas (`AM` y `EU`)** que absorben el `100 %` del tráfico con
     conmutación cruzada automática en `≤ 60 s` (`QA-05` preservado), más una **tercera región (`AP`)
     operando únicamente como testigo liviano de datos** (sin réplicas de aplicación encendidas).
   * Los `64` *buckets* lógicos ([ADR-0023](ADR-0023-particionamiento-y-crecimiento.md)) corren sobre
     `2` fragmentos físicos pequeños por región activa.
   * `event-pipeline` vuelca eventos en formato columnar (Parquet) sobre almacenamiento de objetos y
     `analytics-store` usa un **motor SQL sin servidor de pago por consulta** (`~USD 250/mes`),
     manteniendo `0 %` de impacto sobre la base operacional (`QA-09`).
2. **Etapa 2 — Escala nominal del enunciado (`15 M` cuentas · `2 M` WAU · `3.000 req/s` · `~USD 28.500/mes`):**
   * Se enciende el cómputo de aplicación en `AP` fijando `replicas_min_ap > 0` en IaC. Las **tres
     regiones operan activas con capacidad base asimétrica** ajustada a la distribución real de
     viajeros (`45 % AM · 35 % EU · 20 % AP`), combinada con autoescalado predictivo y reserva tibia
     del `15 %` ([ADR-0021](ADR-0021-estrategia-autoescalado.md)).
   * Los `64` *buckets* se reparten en `4` fragmentos físicos por región y `analytics-store` pasa a
     capacidad dedicada en horario laboral para sostener consultas sobre `~3.300 M` de eventos en
     `≤ 30 s`.
3. **Etapa 3 — Duplicación `QA-08` (`30 M` cuentas · `4 M` WAU · `6.000 req/s` · `~USD 51.200/mes`):**
   * División en línea de `4` a `8–16` fragmentos físicos por región y activación plena de
     compactación de observaciones (`> 90 d`) y archivo frío (`> 12 m`) ([ADR-0023](ADR-0023-particionamiento-y-crecimiento.md)).
   * Al duplicar usuarios y carga (`2,00×`), el gasto mensual pasa de `USD 28.500` a `USD 51.200`
     (**factor `1,80×`**, bajando el costo unitario de `USD 0,0143` a **`USD 0,0128` por WAU-mes**).

### Consecuencias

* **Bueno,** porque cierra el riesgo `R-3` reduciendo en **`83 %`** el costo inicial (`USD 4.800` vs.
  `USD 28.500/mes`) sin sacrificar `QA-05`, `QA-09` ni escribir deuda arquitectónica deliberada.
* **Bueno,** porque demuestra cuantitativamente la sublinealidad de costo exigida por `QA-08` (`1,80×`
  para `2,00×` de crecimiento).
* **Malo,** porque en la Etapa 1 los usuarios ubicados en Asia-Pacífico leen y escriben contra Europa
  o América (`+110–160 ms` de RTT geográfico) hasta que el volumen regional de `AP` justifica activar
  su plano de aplicación en la Etapa 2.

### Confirmación

* **Presupuesto y alertas de facturación (*FinOps*):** umbral de alerta mensual en nube al `85 %` del
  presupuesto de la etapa vigente y revisión trimestral del indicador **`USD / WAU-mes`**.
* **Prueba de activación declarativa de región:** verificar en entorno de ensayo que levantar una
  región desde modo «solo testigo de datos» a «región activa de aplicación» se completa ejecutando el
  módulo de IaC y habilitando el peso en el DNS global, sin tocar un solo archivo de código de los
  servicios.

## Pros y contras de las opciones

### Z1 — Tres regiones simétricas a escala plena desde el día 1

* Bueno, porque entrega latencia óptima global desde el primer minuto.
* **Malo, porque inmoviliza `~USD 28.500/mes` con capacidad mayormente ociosa durante la etapa de
  validación del negocio.**

### Z2 — Región única sin particionamiento y rediseño futuro

* Bueno, porque minimiza la factura de los primeros meses.
* **Malo, porque incumple `QA-05` y exige una migración traumática de datos, contratos y topología más
  adelante.**

### Z3 — Tres etapas de capacidad sobre arquitectura invariante

* Bueno, porque desacopla las decisiones irreversibles (límites de módulos, claves de partición,
  contratos, separación OLTP/OLAP) de las decisiones elásticas (cantidad de réplicas y regiones con
  cómputo encendido).
* Malo, porque requiere mantener parametrizada la topología desde el inicio mediante infraestructura
  como código.

## Más información

* Desglose numérico por rubro: [iteración 3, §5.10](../02-proceso-add/iteracion-3/README.md#510-modelo-de-costo-mensual-y-camino-escalonado-de-infraestructura-d26--r-3)
* Análisis comparativo: [iteración 3, paso 4, D26](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d26--modelo-de-costo-y-camino-escalonado-de-infraestructura-crn-08--r-3)
* Relacionados: [ADR-0002](ADR-0002-despliegue-multirregion.md), [ADR-0003](ADR-0003-separacion-planos.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md), [ADR-0021](ADR-0021-estrategia-autoescalado.md), [ADR-0023](ADR-0023-particionamiento-y-crecimiento.md)
