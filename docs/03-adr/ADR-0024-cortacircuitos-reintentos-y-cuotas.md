---
estado: aceptado
fecha: 2026-10-29
decisores: Juan Emilio Pardo, Ivo Iriarte
consultados: Francisco Lozano, Jeremias Aguilar
informados: equipo completo
iteracion: 3
drivers: QA-06, CRN-09, QA-01, RF-02, RF-05
---

# ADR-0024: Mamparos, cortacircuitos de ventana deslizante, cola persistente y gobierno de cuotas de terceros

## Contexto y planteo del problema

Trotamundos depende de **doce sistemas externos** ([1.2 Diagrama de contexto](../01-analisis-inicial/02-diagrama-de-contexto.md)):
proveedores de correo con y sin *push*, proveedores de viajes (aerolíneas, hoteles, transporte, OAuth
de terceros), agencias/soporte y pasarelas de notificación. Dos drivers gobiernan simultáneamente esa
frontera:

* **`QA-06`** exige que, si un proveedor externo cae durante `15 minutos` o más, la lectura del panel
  sufra **`0` operaciones fallidas**, el cortacircuitos del adaptador abra en **`≤ 30 segundos`** y se
  recupere el **`100 %` de las actualizaciones pendientes** al restablecerse, reteniendo reintentos
  hasta **`24 horas`**.
* **`CRN-09`** advierte que todos los proveedores imponen cuotas estrictas de llamadas: reintentar de
  forma ingenua o reconectar en manada agota la cuota diaria y prolonga la interrupción.
* Además, [ADR-0004](ADR-0004-obtencion-de-correo.md) dejó pendiente para esta iteración fijar los
  intervalos exactos del sondeo de reconciliación y el objetivo de frescura específico para los
  buzones IMAP que carecen de notificaciones *push*.

## Drivers de decisión

* **QA-06** — `0` fallos en lectura del panel, apertura de cortacircuitos `≤ 30 s` y `0` pérdida de
  actualizaciones con cola persistente de `24 h`.
* **CRN-09** — presupuestos de cuota por proveedor externo, alertas preventivas y degradación ordenada.
* **QA-01** — frescura `p95 ≤ 5 min` en integraciones con *push* y objetivo explícito para buzones sin
  *push* ([ADR-0004](ADR-0004-obtencion-de-correo.md)).
* **RF-02 / RF-05** — continuidad de ingesta de correo y sincronización con proveedores.

## Opciones consideradas

* **X1** — Reintentos inmediatos en línea sobre un *pool* HTTP compartido por servicio.
* **X2** — Cortacircuitos por adaptador que descarta la operación fallida y espera al próximo ciclo de
  reconciliación periódica.
* **X3** — Mamparo por adaptador + cortacircuitos de ventana deslizante (`≤ 25 s`) + `cola_pendientes`
  persistente (`24 h`) con retroceso exponencial y *jitter* + limitador distribuido de cuota al `80 %`
  (alerta al `70 %`) + reconciliación escalonada por cercanía de viaje.

## Resultado de la decisión

Se adopta **X3**, instanciado de forma uniforme en los adaptadores de `provider-sync`, `mail-ingest` y
`support-liaison`:

1. **Aislamiento total respecto del panel y mamparos por adaptador.** Ninguna ruta de lectura del
   panel (`GET /panel`, `GET /panel/resumen`, `GET /viajes/{id}`) invoca jamás a terceros. Dentro de
   los servicios de integración, cada proveedor tiene su propio **mamparo (*bulkhead*)** con un máximo
   de `50` conexiones concurrentes por réplica, *timeouts* estrictos (`2 s` de conexión y `5 s` de
   lectura en viajes/correo; `3 s` en agencias) y cola interna aislada.
2. **Cortacircuitos de ventana deslizante en `≤ 25 s`.** Evalúa ventanas de `20 s` (mínimo `10`
   llamadas) y pasa a `Abierto` si los fallos transitorios (`5xx` o *timeout*) alcanzan el **`50 %`**
   o se producen **`5` *timeouts* consecutivos**, garantizando apertura en **`≤ 25 s < 30 s`**.
   Permanece `Abierto` durante `30 s` y pasa a `Semiabierto` enviando `3` sondas antes de cerrar.
   Clasificación semántica de respuestas:
   * `5xx` y *timeouts* de red: cuentan para abrir el cortacircuitos y se encolan para reintento.
   * `429 Too Many Requests`: activa el freno de cuota respetando `Retry-After` sin distorsionar la
     métrica de salud del proveedor.
   * `400 / 404` y `401 / 403`: **no reintentables**; en correo y cuentas vinculadas, un `401/403`
     tras intentar refrescar el token transiciona la conexión a `RequiereReautorizacion` y avisa al
     usuario.
3. **Cola persistente de `24 h` y drenaje sin avalancha.** Cuando el cortacircuitos está `Abierto` o
   una llamada transitoria falla, el trabajo se guarda en `cola_pendientes` (retención **24 h**) con
   retroceso exponencial `5 s × 2^n` (tope `15 min`) y variación aleatoria (*full jitter*) de `±30 %`.
   Al volver el proveedor, el drenaje de atrasos consume como máximo el **`50 %` de la cuota por
   segundo**, reservando la otra mitad al tráfico nuevo en vivo.
4. **Presupuesto de cuota por proveedor (`CRN-09`).** Cada par `(proveedor, región)` opera bajo un
   limitador distribuido fijado al **`80 %` de la cuota contractual** (dejando `20 %` de margen de
   seguridad), con **alerta operativa al `70 %`**. El cupo interno se reparte por prioridad: **`60 %`**
   para *webhooks* y viajes `EnCurso`, **`25 %`** para viajes futuros y **`15 %`** para reconciliación
   de fondo (que estira automáticamente su período si el consumo supera el `70 %`).
5. **Cierre de los parámetros pendientes de [ADR-0004](ADR-0004-obtencion-de-correo.md):**
   * *Buzones con soporte push (`~90 %` — Gmail, Microsoft Graph):* reconciliación de seguridad cada
     **`6 h`** si el usuario tiene viaje en curso o salida en `< 14 días`, y cada **`24 h`** en
     reposo, repartida uniformemente por `hash(buzon_id)`. Mantienen el SLO pleno de **`p95 ≤ 5 min`**.
   * *Buzones IMAP sin soporte push (`~10 %`):* usan `IMAP IDLE` cuando el servidor lo sostiene y, en
     su defecto, verificación liviana de `UIDNEXT` cada **`15 min`** (viaje activo o salida `< 72 h`),
     cada **`60 min`** (viaje planificado) y cada **`6 h`** (sin viajes futuros). Su objetivo de
     frescura explícito queda fijado en **`p95 ≤ 20 min` en ventana de viaje activo** y **`p95 ≤ 60
     min` en viaje planificado**.

### Consecuencias

* **Bueno,** porque una caída total de cualquier aerolínea o proveedor de correo produce exactamente
  `0` errores en la lectura de itinerarios y recupera el `100 %` de los cambios pendientes sin generar
  tormentas de reconexión (*thundering herd*).
* **Bueno,** porque cierra con números verificables el pendiente de cuotas (`CRN-09`) y de buzones
  IMAP dejado por la iteración 1.
* **Malo,** porque agrega estado operativo (`cola_pendientes` y contadores distribuidos de cuota) que
  debe monitorearse en el tablero de observabilidad ([ADR-0025](ADR-0025-observabilidad-sli-slo-presupuesto-error.md)).

### Confirmación

* **Prueba de inyección de falla (`QA-06`):** en preproducción, simular `15 min` de respuestas `503` y
  *timeouts* en un proveedor de viajes verificando: `0` errores en `GET /panel`, apertura del
  cortacircuitos en `≤ 30 s`, retención íntegra en `cola_pendientes` y convergencia del `100 %` de las
  reservas dentro de los `5 min` posteriores a restaurar el proveedor sin superar el `80 %` de su
  cuota por segundo.

## Pros y contras de las opciones

### X1 — Reintentos inmediatos en línea sobre *pool* compartido

* Bueno, porque oculta hipos de red de pocos milisegundos sin infraestructura adicional.
* **Malo, porque agota hilos, contamina a los otros 11 adaptadores y multiplica la carga contra un
  proveedor caído.**

### X2 — Cortacircuitos con descarte y espera al próximo sondeo

* Bueno, porque protege los recursos propios con implementación mínima.
* **Malo, porque pierde eventos de proveedores puramente basados en *webhook* o demora horas la
  actualización tras una caída breve.**

### X3 — Mamparo + cortacircuitos deslizante + cola persistente 24 h + presupuesto de cuota

* Bueno, porque cumple simultáneamente `QA-06`, `CRN-09` y `QA-01`.
* Malo, porque exige distinguir rigurosamente errores transitorios, límites de cuota y fallos de
  autorización en cada adaptador (`ADR-0015`).

## Más información

* Análisis comparativo: [iteración 3, paso 4, D24](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d24--políticas-de-cortacircuitos-reintentos-pendientes-y-cuotas-de-terceros-qa-06-crn-09)
* Relacionados: [ADR-0004](ADR-0004-obtencion-de-correo.md), `ADR-0014`, `ADR-0015`, [ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md), [ADR-0025](ADR-0025-observabilidad-sli-slo-presupuesto-error.md)
