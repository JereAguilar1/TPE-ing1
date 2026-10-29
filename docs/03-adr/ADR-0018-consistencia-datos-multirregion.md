---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Francisco Lozano
consultados: Jeremias Aguilar, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: QA-05, CRN-13, CRN-12, CRN-11, QA-02, RF-06, CON-10
---

# ADR-0018: Región primaria por usuario con testigo transregional selectivo, fusión convergente ante caída y lectura causal

## Contexto y planteo del problema

[ADR-0002](ADR-0002-despliegue-multirregion.md) estableció un despliegue activo-activo en tres
regiones (`América`, `Europa`, `Asia-Pacífico`) para sostener `QA-05` (detección `≤ 30 s`,
redirección `≤ 60 s`, `≤ 1,5 min` del presupuesto mensual y **pérdida de datos confirmados = 0**), y
trasladó deliberadamente a la iteración 3 el riesgo **`R-1`** (`CRN-13`: consistencia de datos entre
regiones activas).

En la iteración 2, el diseño interno de `itinerary` y `mail-ingest` agregó una segunda restricción
acoplada (**`R-4`**): tanto la bandeja de entrada de idempotencia (`D14` / `CRN-12`) como la
resolución de conflictos entre fuentes (`D13` / `CRN-11`) requieren que todas las operaciones sobre
un mismo usuario se serialicen en una única partición. Si dos regiones procesaran en simultáneo el
mismo mensaje o dos actualizaciones de una misma reserva, producirían notificaciones duplicadas o
versiones divergentes del itinerario, quebrando la promesa de «único punto de verdad» (`MN-1`).

Al mismo tiempo, coordinar por consenso transoceánico cada operación del sistema penalizaría con
`120–250 ms` adicionales cada transacción de ingesta y arruinaría los `80 ms` asignados al acceso a
datos en `QA-02`.

## Drivers de decisión

* **QA-05** — ante caída de una región completa: detección `≤ 30 s`, redirección `≤ 60 s`,
  **pérdida de datos confirmados = 0**, consumo `≤ 1,5 min` del presupuesto mensual.
* **CRN-13** — consistencia de datos entre regiones activas y comportamiento ante partición.
* **CRN-12 / CRN-11 (`R-4`)** — idempotencia de la bandeja de entrada y fusión determinista sin
  efectos laterales duplicados.
* **QA-02** — el camino de lectura del panel debe mantenerse local (`≤ 800 ms` p95 en el borde).
* **RF-06** — el usuario que crea o edita manualmente una reserva no puede verla desaparecer en la
  lectura siguiente (*read-your-writes*).
* **CON-10** — preparar la estructura para residencia normativa de datos por jurisdicción.

## Opciones consideradas

* **R1** — Partición por usuario con región primaria pura y replicación asíncrona simple.
* **R2** — Escritura libre sin región dueña apoyada exclusivamente en tipos convergentes (CRDT).
* **R3** — Consenso síncrono global entre las tres regiones en cada escritura.
* **R4** — Región primaria por usuario con quórum intra-región, testigo transregional selectivo para
  comandos manuales, conmutación con fusión determinista (D10/D13) y lectura causal por sesión.

## Resultado de la decisión

Se adopta **R4**, diferenciando la garantía según el tipo de operación:

1. **Propiedad de escritura por `región_primaria`.** Cada `usuario_id` tiene asignada una región
   primaria (`AM`, `EU` o `AP`, transportada en el token OIDC y en un directorio liviano cacheado en
   `edge`/`api-gateway`) y una `región_respaldo` determinista por `hash(usuario_id)`. En operación
   normal, el `100 %` de las escrituras del usuario —ingesta de `mail-ingest`, seguimiento de
   `provider-sync` y mutaciones de `itinerary-escritura`— se ejecutan en su `región_primaria` con
   **quórum síncrono en 2 de 3 zonas de disponibilidad** (`~3 ms` RTT) y replicación asíncrona
   continua (`< 1 s` p95) hacia las demás regiones.
2. **Lecturas siempre cercanas con consistencia causal (*read-your-writes*).** Toda lectura del
   panel (`GET /panel`, `GET /panel/resumen`) se sirve desde la réplica de la región sana más cercana
   al viajero, esté o no en su continente de origen. Cada mutación devuelve un contador monótono
   `version_usuario`; si el cliente presenta `X-Min-Version` mayor que la versión aplicada en la
   réplica local, el BFF sirve el estado desde la caché de sesión escrita en el comando o reenvía esa
   lectura puntual a la `región_primaria`.
3. **Testigo transregional síncrono para comandos manuales (`RPO = 0`).** Únicamente en mutaciones
   iniciadas por el usuario (`POST/PUT/DELETE /reservas`, resolución de conflictos, `POST /casos` —
   menos de `15 req/s` globales), antes de responder `200/201`, `itinerary-escritura` registra de
   forma síncrona una entrada compacta en el registro testigo de la `región_respaldo` (`~70–90 ms`
   por red troncal privada). Las ingestas automáticas no pagan ese salto porque la fuente externa
   conserva el mensaje y la reconciliación lo recupera de manera idempotente.
4. **Conmutación y reintroducción seguras.** Si cae la `región_primaria`, la `región_respaldo`
   aplica los registros testigo pendientes y asume la escritura en `≤ 45 s`. Cuando la región caída
   vuelve, sincroniza pasivamente las observaciones acumuladas (cuya consolidación es determinista
   por `D10`/`D13`) antes de reincorporarse al DNS global.

### Consecuencias

* **Bueno,** porque cierra en un solo diseño **`R-1` y `R-4`**, llevando `CRN-12`, `CRN-13` y `QA-05`
  a estado completamente tratado sin sacrificar la latencia local de lectura (`QA-02`).
* **Bueno,** porque cumple literalmente «pérdida de datos confirmados = 0» pagando latencia
  inter-regional únicamente donde hay confirmación humana (`< 15 req/s`), y no sobre los `3.000 req/s`
  de lectura ni sobre la ingesta asíncrona.
* **Bueno,** porque deja resuelta la mitad estructural de `CRN-15` para la iteración 4: cada usuario
  ya tiene jurisdicción primaria explícita.
* **Malo,** porque un viajero que edita manualmente una reserva estando en otro continente percibe
  `~150–220 ms` adicionales en ese `POST/PUT`, costo aceptable para una acción manual esporádica.
* **Malo,** porque replicar proyecciones y el registro testigo hacia otra región abre una tensión
  jurídica con regímenes estrictos de residencia de datos personales (`CON-10`), que queda
  registrada como riesgo **`R-6`** para tratarse en la iteración 4 (`ADR-0030`, `ADR-0031`).

### Confirmación

* **Prueba de caída regional (`QA-05`):** confirmar un `POST /reservas` en la región `EU`, aislar
  inmediatamente `EU` antes del ciclo asíncrono normal y verificar que en `≤ 60 s` el usuario lee la
  reserva intacta desde `AM` sin pérdida ni duplicación.
* **Prueba de concurrencia (`R-4` / `CRN-12`):** inyectar el mismo webhook por dos bordes regionales
  distintos y verificar una única entrada en `bandeja_entrada` y una única notificación emitida.
* **Prueba de *read-your-writes*:** ejecutar `POST /reservas` desde una región secundaria con atraso
  artificial de replicación de `2 s` y verificar que el `GET /panel` inmediato con `X-Min-Version`
  devuelve la reserva recién creada.

## Pros y contras de las opciones

### R1 — Región primaria pura con replicación solo asíncrona

* Bueno, porque es simple y serializa todas las escrituras de un usuario (`R-4`).
* **Malo, porque pierde comandos ya confirmados (`200/201`) que caigan en la ventana `< 1 s` previa
  a un desastre regional**, incumpliendo `QA-05`.

### R2 — Escritura libre multirregión con tipos convergentes puros (CRDT)

* Bueno, porque toda escritura es local y no requiere reasignar primario al caer una región.
* **Malo, porque no evita efectos laterales duplicados (`R-4`):** dos regiones que reciben la misma
  alerta procesan y notifican por duplicado antes de converger.

### R3 — Consenso síncrono transoceánico en toda escritura

* Bueno, porque ofrece consistencia fuerte global sin casos de borde.
* **Malo, porque penaliza el 100 % de las transacciones de escritura con RTT intercontinental** y
  encarece desproporcionadamente el motor de datos (`CRN-08`).

### R4 — Región primaria + testigo selectivo + fusión determinista + lectura causal

* Bueno, porque combina `RPO = 0` en comandos confirmados, lecturas locales rápidas e idempotencia
  exacta por partición.
* Malo, porque requiere protocolo de promoción y reintroducción pasiva bien automatizado y abre `R-6`
  para la iteración 4.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D18](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d18--modelo-de-consistencia-de-datos-entre-regiones-r-1--r-4--crn-13)
* Vista donde se instancia: [vista de despliegue — nivel 2](../04-vistas/vista-despliegue-nivel-2.md)
* Relacionados: [ADR-0002](ADR-0002-despliegue-multirregion.md), `ADR-0010`, `ADR-0012`, `ADR-0013`, `ADR-0014`
