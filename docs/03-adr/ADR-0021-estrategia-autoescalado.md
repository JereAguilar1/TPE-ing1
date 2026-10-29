---
estado: aceptado
fecha: 2026-10-29
decisores: Francisco Lozano, Ivo Iriarte
consultados: Jeremias Aguilar, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: QA-04, QA-08, CRN-08, CRN-02, CON-09, CON-A4
---

# ADR-0021: Autoescalado híbrido con indicadores adelantados y despliegue separado de lectura y escritura en `itinerary`

## Contexto y planteo del problema

El tráfico de Trotamundos combina dos dinámicas distintas: picos semanales predecibles entre
domingo-lunes y jueves-viernes (`S-02`) y ráfagas súbitas por disrupciones donde `QA-04` exige
completar el escalado en **`≤ 3 minutos`**. Escalar únicamente por porcentaje de CPU llega tarde (es
un indicador atrasado) y levantar nodos fríos desde cero suele demorar varios minutos; mantener en
cambio el triple de servidores encendidos todo el mes arruina el costo (`CRN-08`).

Además, la iteración 2 registró el riesgo **`R-5`**: concentrar la lectura del panel (`3.000–9.000
req/s`) y la escritura/fusión de reservas en una sola unidad operativa de `itinerary` acopla sus
curvas de escalado y obliga a redesplegar la lectura ante cualquier ajuste en las reglas de fusión.

## Drivers de decisión

* **QA-04** — tiempo de escalado **`≤ 3 minutos`** ante una ráfaga imprevista de `3×` en lectura y
  `10×` en ingesta.
* **QA-08** — absorber horizontalmente la duplicación de cuentas y actividad en 12 meses.
* **CRN-08** — evitar pagar capacidad ociosa de pico durante las horas valle.
* **CRN-02 / CON-09 / CON-A4 (`R-5`)** — desacoplar lectura y escritura de `itinerary` sin superar el
  techo de `< 15` elementos lógicos.

## Opciones consideradas

* **U1** — Autoescalado puramente reactivo por CPU/memoria con un único despliegue de `itinerary`.
* **U2** — Capacidad fija preaprovisionada las 24 horas para el pico de disrupción (`9.000 req/s`).
* **U3** — Autoescalado híbrido (predictivo por calendario + reactivo por indicadores adelantados +
  reserva tibia del 15 %) con reducción conservadora y despliegue separado `itinerary-lectura` /
  `itinerary-escritura`.

## Resultado de la decisión

Se adopta **U3**:

1. **Dos unidades de despliegue desde el código de `itinerary` (`R-5`).** El elemento lógico
   `itinerary` se despliega en dos grupos independientes: `itinerary-lectura` (sirve `proyeccion-panel`
   y consultas `GET`) e `itinerary-escritura` (ejecuta `ingesta`, `fusion`, `reservas`, `viajes`,
   `gestion-manual` y `publicacion`), con *pools* de conexiones, presupuestos de recursos y canarios
   independientes.
2. **Escalado predictivo por calendario.** Treinta minutos antes de las franjas pico de domingo-lunes
   y jueves-viernes (según huso horario de cada región), el piso mínimo de réplicas se eleva de forma
   programada a la capacidad nominal de `3.000 req/s`.
3. **Escalado reactivo por métricas adelantadas y colchón tibio (`≤ 3 min`).** Los servicios HTTP
   escalan cuando superan el `65 %` de peticiones/s nominales por réplica o `p95 > 500 ms` durante
   `60 s`; los consumidores del *broker* escalan cuando `edad_mensaje_mas_antiguo > 20 s` en `P1`
   (`> 45 s` en `P2`), con techo máximo alineado al número de particiones y al cupo de conexiones de
   datos. Un `15 %` de capacidad de nodos tibios con imágenes precargadas garantiza réplicas listas en
   `≤ 45 s` y nodos nuevos en `≤ 150 s`.
4. **Reducción asimétrica conservadora.** Ventana de enfriamiento de `15 min` y reducción máxima del
   `20 %` cada `5 min`, drenando peticiones y particiones antes de apagar instancias.

### Consecuencias

* **Bueno,** porque los picos semanales conocidos tienen latencia de escalado cero y las ráfagas
  imprevistas entran debajo de los `3 minutos` exigidos por `QA-04` pagando solo un `15 %` de
  colchón tibio en lugar de un `200 %` extra fijo.
* **Bueno,** porque cierra **`R-5`** sin romper `CON-A4`: una tormenta de correos escala
  `booking-extraction` e `itinerary-escritura` sin multiplicar réplicas de `itinerary-lectura`, y un
  cambio en la fusión no toca el canario de lectura.
* **Malo,** porque exige mantener sincronizados los techos de réplicas consumidoras con los límites de
  conexiones de la base operacional para no trasladar la saturación aguas abajo.

### Confirmación

* Prueba bajo el escenario especificado para `QA-04` en
  [pruebas-de-carga-y-slos.md](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-2--qa-04-pico-súbito-por-disrupción-masiva)
  midiendo el intervalo entre el inicio del salto `3×` y la estabilización de réplicas nuevas: debe
  ser **`≤ 180 s`**.
* Verificación en la infraestructura declarativa ([vista de despliegue N2](../04-vistas/vista-despliegue-nivel-2.md))
  de que `itinerary-lectura` e `itinerary-escritura` poseen descriptores de despliegue, límites y
  reglas de autoescalado independientes.

## Pros y contras de las opciones

### U1 — Reactivo puro por CPU con despliegue único de `itinerary`

* Bueno, porque usa la configuración por omisión de cualquier orquestador.
* **Malo, porque reacciona tarde ante bloqueos de E/S, supera los `3 min` al pedir nodos fríos y
  mantiene vivo `R-5`.**

### U2 — Capacidad permanente de pico de disrupción

* Bueno, porque absorbe cualquier ráfaga al instante sin lógica elástica.
* **Malo, porque multiplica por tres el gasto fijo mensual de cómputo (`CRN-08`).**

### U3 — Autoescalado híbrido + separación operativa lectura/escritura

* Bueno, porque equilibra tiempo de respuesta `< 3 min`, eficiencia económica y aislamiento operativo.
* Malo, porque requiere calibrar los umbrales de peticiones/réplica en las pruebas de carga del
  prototipo.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D21](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d21--estrategia-de-autoescalado-y-separación-operativa-de-itinerary-qa-04-qa-08-r-5)
* Tabla completa de réplicas y umbrales: [vista de despliegue — nivel 2](../04-vistas/vista-despliegue-nivel-2.md)
* Relacionados: [ADR-0001](ADR-0001-estilo-arquitectonico.md), [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md), [ADR-0026](ADR-0026-modelo-costo-y-camino-escalonado.md)
