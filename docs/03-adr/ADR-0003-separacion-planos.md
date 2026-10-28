---
estado: aceptado
fecha: 2026-10-24
decisores: Francisco Lozano, Jeremias Aguilar
consultados: Juan Emilio Pardo
informados: equipo completo
iteracion: 1
drivers: QA-09, RF-14, QA-02, QA-04, CRN-08, AMB-07
---

# ADR-0003: Separación del plano operacional y del plano analítico

## Contexto y planteo del problema

El enunciado pide que Trotamundos recopile datos analíticos de los viajes —tendencias, destinos,
cancelaciones— «para su monetización por parte del equipo de datos, implicando la ejecución de
consultas analíticas pesadas». La analítica no es un extra: es una línea de ingresos declarada
(MN-4).

El problema es que esas consultas y las del panel del usuario tienen requisitos opuestos:

| | Camino del panel | Consulta analítica |
|---|---|---|
| Latencia objetivo | 800 ms p95 | 30 s p95 (AMB-07) |
| Alcance | Un usuario | Todas las cuentas, 3 años, ≈ 3.300 millones de registros |
| Forma del acceso | Lectura puntual por clave | Agregación masiva |
| Frescura necesaria | Segundos | ≤ 1 hora (AMB-07) |
| Frecuencia | 3.000 req/s | Episódica |

[QA-09](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica)
fija el límite: la consulta analítica no puede degradar el p95 operacional más de un **5 %**,
estando el plano operacional en carga pico. El problema de fondo no es el esquema de datos: es que
dos consultas con esos perfiles **compiten por los mismos recursos**.

## Drivers de decisión

* **QA-09** — degradación del p95 operacional < 5 % durante una consulta analítica; latencia de
  consulta ≤ 30 s; frescura ≤ 1 h.
* **RF-14** — consultas analíticas pesadas sobre tendencias, destinos y cancelaciones.
* **QA-02** — el presupuesto de 80 ms para el acceso a datos del camino de lectura.
* **QA-04** — durante un pico, la analítica debe poder degradarse antes que el panel.
* **CRN-08** — un segundo almacén cuesta dinero.

## Opciones consideradas

* **C1** — Un solo almacén, con réplicas de lectura para la analítica.
* **C2** — CQRS: vistas materializadas de lectura sobre el mismo almacén.
* **C3** — Plano analítico separado, alimentado por el flujo de eventos de dominio.
* **C4** — Plano analítico separado, alimentado por volcados nocturnos.

## Resultado de la decisión

Se adopta **C3**, y **además C2 dentro del plano operacional**. Son dos decisiones que se
complementan y es importante no confundirlas:

1. **Plano analítico separado** (`event-pipeline` + `analytics-store`): un almacén columnar
   alimentado de forma continua por el flujo de eventos de dominio que
   [ADR-0001](ADR-0001-estilo-arquitectonico.md) ya produce. Las consultas de RF-14 se ejecutan
   íntegramente ahí y **nunca tocan las bases operacionales**.
2. **Proyección de lectura dentro del plano operacional** (CQRS acotado): el camino de lectura del
   panel consulta una proyección optimizada para la forma exacta en que el panel presenta los
   datos —viajes con sus reservas agrupadas— en lugar de recomponerla desde el modelo normalizado
   en cada petición. Es lo que hace cerrar el tramo de 80 ms del presupuesto de QA-02.

La **frontera de degradación** de QA-04 queda definida acá: ante sobrecarga, el `event-pipeline` y
las consultas analíticas se degradan **antes** que el panel y las notificaciones. La consecuencia
aceptada es que durante una disrupción la frescura analítica puede exceder la hora.

### Consecuencias

* **Bueno,** porque QA-09 se satisface por construcción: la consulta analítica no puede degradar a
  la operación si no comparte recursos con ella. No es una optimización, es una imposibilidad
  estructural.
* **Bueno,** porque el almacén columnar es la herramienta correcta para agregaciones masivas, de
  modo que los 30 s de AMB-07 son holgados.
* **Bueno,** porque el flujo de eventos ya existe por ADR-0001: alimentar el plano analítico no
  agrega un mecanismo nuevo, solo un consumidor más.
* **Bueno,** porque da la frontera de degradación que QA-04 necesita, y la da de forma natural.
* **Malo,** porque el dato queda duplicado en dos almacenes con modelos distintos, y hay que
  mantener la correspondencia entre ellos. Un cambio en el modelo canónico se propaga a los dos.
* **Malo,** porque **complica el borrado de datos personales**: QA-14 exige suprimir en el 100 %
  de los almacenes en 30 días, y el plano analítico es uno de ellos. Suprimir de un almacén
  columnar inmutable no es trivial, y queda asignado a la iteración 4.
* **Malo,** porque cuesta un segundo almacén más una canalización (CRN-08).
* **Neutro,** porque introduce frescura eventual en los datos analíticos. AMB-07 ya lo aceptó
  fijando el objetivo en ≤ 1 hora.

### Confirmación

* **Prueba de aislamiento:** ejecutar la consulta analítica más pesada mientras el plano
  operacional está en carga pico, y medir el p95 operacional antes y durante. La degradación debe
  ser < 5 %.
* **Revisión de dependencias:** ninguna credencial del `analytics-store` debe dar acceso de lectura
  a las bases operacionales, y viceversa. Verificable por revisión de las políticas de acceso.
* **Medición de frescura:** retardo entre la emisión de un evento de dominio y su disponibilidad en
  el `analytics-store`, con alerta por encima de 1 hora.

## Pros y contras de las opciones

### C1 — Un solo almacén con réplicas de lectura para la analítica

* Bueno, porque es lo más simple y lo más barato.
* Bueno, porque no hay duplicación del dato ni problema de frescura.
* **Malo, porque no resuelve el driver.** Las réplicas comparten el flujo de replicación con el
  primario, y una consulta de 3 años sobre un esquema normalizado las satura: el retardo de
  replicación crece y afecta al camino de lectura operacional.
* Malo, porque un esquema normalizado y orientado a acceso por clave es malo para agregaciones
  masivas: los 30 s de AMB-07 serían difíciles.

### C2 — CQRS con vistas materializadas sobre el mismo almacén

* Bueno, porque mejora notablemente el camino de lectura operacional (y por eso **se adopta** para
  ese propósito).
* **Malo, porque no resuelve la analítica:** la vista materializada sigue viviendo en el almacén
  operacional y compitiendo por sus recursos.
* Malo, porque no ofrece la frontera de degradación que QA-04 necesita.

### C3 — Plano analítico separado alimentado por el flujo de eventos

* Bueno, porque satisface QA-09 por aislamiento físico, no por optimización.
* Bueno, porque aprovecha un mecanismo que ya existe (ADR-0001).
* Bueno, porque da frescura de minutos, muy por debajo del objetivo de 1 hora.
* Malo, porque duplica el dato y complica el borrado de QA-14.
* Malo, porque cuesta un almacén y una canalización más (CRN-08).

### C4 — Plano analítico separado alimentado por volcados nocturnos

* Bueno, porque es más simple que C3: un trabajo programado en lugar de una canalización continua.
* Bueno, porque aísla igual de bien que C3.
* **Malo, porque da una frescura de 24 horas y AMB-07 fijó el objetivo en ≤ 1 hora.** Es el motivo
  decisivo del descarte.
* Malo, porque el volcado masivo nocturno es él mismo una carga sobre el almacén operacional,
  justo lo que se quería evitar.

## Más información

* Drivers: [QA-09](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica),
  [RF-14](../01-analisis-inicial/03-requisitos-funcionales.md),
  [AMB-07](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución)
* Análisis comparativo: [iteración 1, paso 4, D3](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d3--organización-de-los-datos)
* Vistas afectadas: [C&C N1](../04-vistas/vista-cyc-nivel-1.md), [despliegue N1](../04-vistas/vista-despliegue-nivel-1.md)
* Relacionados: [ADR-0001](ADR-0001-estilo-arquitectonico.md) provee el flujo de eventos; la supresión en el plano analítico queda en la [iteración 4](../02-proceso-add/iteracion-4-plan.md)
