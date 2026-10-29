---
estado: aceptado
fecha: 2026-10-29
decisores: Francisco Lozano, Ivo Iriarte
consultados: Jeremias Aguilar, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: QA-02, QA-03, QA-01, RF-09, CRN-03, AMB-02
---

# ADR-0019: Caché multinivel acotada con invalidación por eventos y arranque móvil diferido

## Contexto y planteo del problema

El presupuesto de latencia de `QA-02` (`p95 ≤ 800 ms` a `3.000 req/s`) asigna como máximo **`80 ms`**
al acceso a datos asumiendo al menos un **`90 %` de aciertos de caché**, mientras que `QA-03` exige
un *First Contentful Paint* **`≤ 1,4 segundos` (p75)** en dispositivos móviles de gama media sobre 4G
(`RTT = 150 ms`, `1,6 Mbps`).

Agregar cachés en todas las capas de forma indiscriminada produce dos defectos graves: multiplica en
silencio la antigüedad del dato (comprometiendo los `5 minutos` de `QA-01`) y expone datos personales
si una respuesta privada queda retenida por error en un nodo compartido de borde.

## Drivers de decisión

* **QA-02** — carga del panel web `p95 ≤ 800 ms` y `p99 ≤ 1.500 ms` bajo `3.000 req/s` sostenidos.
* **QA-03** — primer contenido significativo móvil `p75 ≤ 1,4 s` sobre 4G (`150 ms` RTT, `1,6 Mbps`).
* **QA-01** — las actualizaciones externas deben verse en la aplicación en `≤ 5 min` (`p95`).
* **RF-09** — visualización unificada del panel en web y móvil, incluyendo `marcaFrescura`
  ([ADR-0008](ADR-0008-alcance-disponibilidad.md)).

## Opciones consideradas

* **S1** — Sin caché dedicada (lectura directa sobre réplicas relacionales de `panel_usuario`).
* **S2** — Caché de respuestas HTTP del panel de usuario en la red de distribución de borde (CDN).
* **S3** — Caché local en memoria dentro de cada proceso de `bff-*` e `itinerary-lectura`.
* **S4** — Caché multinivel de alcances disjuntos: estáticos/descriptores en CDN, proyección en
  clúster regional en memoria invalidada por eventos, e instantánea cifrada con carga diferida en
  móvil.

## Resultado de la decisión

Se adopta **S4**, fijando tres reglas estrictas:

1. **En el borde (`edge` / CDN) jamás se cachean datos de usuario.** Solo se almacenan recursos
   estáticos inmutables con *hash* y el catálogo público `GET /tipos-de-segmento` (`max-age=300,
   stale-while-revalidate=3600`). Toda respuesta de itinerario viaja con `Cache-Control: private,
   no-cache` y validación condicional por `ETag` (`304 Not Modified`).
2. **Un único punto de caché de dominio en el servidor: clúster en memoria regional** particionado
   por `usuario_id`, que guarda `panel_usuario`, `panel_resumen` y copia de `preferences`. El módulo
   `proyeccion-panel` actualiza o invalida la entrada en `< 5 ms` al procesar cada evento de dominio,
   con un TTL de seguridad de `15 min` y el campo obligatorio `marcaFrescura`.
3. **Arranque móvil acotado por contrato y diferido (`QA-03`).** `bff-mobile` garantiza que
   `GET /panel/resumen` no supere **`15 KB` comprimidos** (solo viajes activos/próximos y alertas),
   `app-movil` compila su paquete inicial de forma anticipada (AOT) difiriendo pantallas secundarias,
   y guarda en almacenamiento local cifrado la última instantánea válida para pintar en `≤ 250 ms` en
   reingresos mientras revalida en segundo plano.

### Consecuencias

* **Bueno,** porque el tramo de datos baja a **`~12 ms`** en el `≥ 92 %` de las lecturas y a
  `~58 ms` en los fallos contra la tabla indexada `panel_usuario`, cerrando `QA-02` en `497–568 ms`
  p95 total.
* **Bueno,** porque incluso el arranque móvil completamente frío sin instantánea previa cierra en
  **`1.180 ms`** (`220 ms` de margen frente a los `1.400 ms` de `QA-03`).
* **Bueno,** porque al no anidar TTLs de datos personales, un cambio consolidado se refleja en caché
  en milisegundos, protegiendo el presupuesto de `QA-01`.
* **Malo,** porque el clúster en memoria regional es una pieza con estado derivado que operar y
  monitorear en cada región; ante su pérdida total, el sistema degrada a lectura directa de
  `panel_usuario` consumiendo la reserva de `200 ms` de `QA-02` sin caerse.

### Confirmación

* Ejecución en el prototipo del escenario especificado para `QA-02` en
  [pruebas-de-carga-y-slos.md](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#escenario-1--qa-02-carga-pico-sostenida-del-panel-web),
  verificando `p95 ≤ 800 ms`, tasa de acierto en caché regional `≥ 90 %` y presencia del atributo
  `marcaFrescura`.
* Verificación contractual en CI de que la respuesta de `GET /panel/resumen` para un usuario con 5
  viajes activos pese `≤ 15 KB` comprimida, y medición de FCP en emulación 4G (`150 ms` RTT,
  `1,6 Mbps`) con resultado `p75 ≤ 1.400 ms`.
* Prueba de no almacenamiento en borde: inspección automática de cabeceras `Cache-Control` en todas
  las rutas autenticadas.

## Pros y contras de las opciones

### S1 — Sin caché dedicada

* Bueno, porque evita toda lógica de invalidación.
* **Malo, porque a `3.000–9.000 req/s` traslada toda la presión de lectura al motor transaccional** y
  no resuelve `QA-03`.

### S2 — Caché de paneles personales en CDN

* Bueno, porque acerca el dato al borde.
* **Malo, porque introduce riesgo severo de fuga de datos personales entre usuarios** y dificulta la
  invalidación inmediata por eventos.

### S3 — Caché en memoria local de cada réplica de servicio

* Bueno, porque ahorra el salto de red dentro de la región.
* **Malo, porque pierde efectividad al autoescalar horizontalmente** y muestra estados inconsistentes
  entre peticiones sucesivas del mismo usuario.

### S4 — Caché multinivel de alcances disjuntos invalidada por eventos

* Bueno, porque cumple simultáneamente `QA-02`, `QA-03` y `QA-01` sin riesgo de fuga en CDN.
* Malo, porque requiere mantener la disciplina del tope de `15 KB` en `bff-mobile` y operar el
  clúster en memoria regional.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D19](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d19--estrategia-de-caché-del-camino-de-lectura-y-arranque-móvil-qa-02-qa-03)
* Verificación numérica: [presupuesto de latencia web](../02-proceso-add/iteracion-3/README.md#1-presupuesto-de-latencia-web-qa-02-p95--800-ms-a-3000-reqs)
* Relacionados: [ADR-0005](ADR-0005-capa-de-clientes-bff.md), [ADR-0008](ADR-0008-alcance-disponibilidad.md), [ADR-0018](ADR-0018-consistencia-datos-multirregion.md)
