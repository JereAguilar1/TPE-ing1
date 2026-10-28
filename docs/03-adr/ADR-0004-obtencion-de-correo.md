---
estado: aceptado
fecha: 2026-10-24
decisores: Juan Emilio Pardo, Francisco Lozano
consultados: Jeremias Aguilar, Ivo Iriarte
informados: equipo completo
iteracion: 1
drivers: QA-01, RF-02, QA-04, QA-11, CRN-09, CRN-08, AMB-03
---

# ADR-0004: Obtención del correo por notificación *push* con sondeo de reconciliación

## Contexto y planteo del problema

El enunciado dice literalmente que «el sistema debe **sondear** y escanear el correo electrónico de
los usuarios», y al mismo tiempo que «las actualizaciones de viaje deben presentarse en la
aplicación dentro de los 5 minutos posteriores a su generación».

Leídos juntos, los dos requisitos describen un sondeo cada 5 minutos a todos los buzones
conectados. El refinado de la especificación hizo la aritmética
([cálculo completo](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#por-qué-el-sondeo-uniforme-es-inviable)):

| | Cálculo | Resultado |
|---|---|---|
| Buzones conectados | 15 M de cuentas × 60 % (S-07) | 9.000.000 |
| Sondeos por segundo, sostenidos 24 × 7 | 9.000.000 ÷ 300 s | **30.000 sondeos/s** |
| Llamadas a APIs de terceros por día | × 2 llamadas por sondeo | **≈ 5.180 millones/día** |
| Con notificación *push*, en cambio | solo buzones con actividad real (S-08) | **45 eventos/s** de promedio |

**La diferencia es de tres órdenes de magnitud.** El sondeo uniforme excede ampliamente las cuotas
publicadas de las APIs de correo, su costo es prohibitivo para una *startup* (CRN-08), y el
99,99 % de esos sondeos devolvería «nada nuevo».

Esto convierte la decisión en algo más que una elección técnica: es una **reinterpretación
documentada de un requisito del enunciado**, registrada como
[AMB-03](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución).
Se interpreta «sondear» como *obtener de forma continua*, y el mecanismo pasa a ser decisión de
diseño.

## Drivers de decisión

* **QA-01** — propagación de una actualización en ≤ 5 minutos (p95), con
  [presupuesto por tramo](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-frescura-5-minutos)
  que asigna 60 s al tramo «la fuente genera el cambio → la notificación llega».
* **RF-02** — obtener los mensajes de viaje de las cuentas conectadas de forma continua.
* **CRN-09** — cuotas y límites de tasa de las APIs de terceros, que el sistema no controla.
* **CRN-08** — costo de infraestructura y de llamadas a terceros.
* **QA-04** — durante una disrupción, los eventos de correo se multiplican por 10 (450/s).
* **QA-11** — la cobertura debe incluir proveedores sin notificación *push* (IMAP genérico, E-06).

## Opciones consideradas

* **E1** — Sondeo uniforme cada 5 minutos (la lectura literal del enunciado).
* **E2** — Sondeo con intervalo adaptativo según la actividad del buzón.
* **E3** — Notificación por *push* del proveedor, exclusivamente.
* **E4** — *Push* como camino principal, más sondeo de reconciliación escalonado.

## Resultado de la decisión

Se adopta **E4**:

1. **Camino principal: notificación *push* del proveedor.** Para los proveedores que lo soportan
   (Gmail API con `watch`, Microsoft Graph con *subscriptions* — E-05), `mail-ingest` mantiene una
   suscripción por buzón y recibe una notificación cuando hay actividad. Es el camino que cumple
   el tramo de 60 s del presupuesto de frescura.
2. **Red de seguridad: sondeo de reconciliación escalonado.** Un sondeo de baja frecuencia, con
   intervalo según la actividad observada del buzón, que cubre dos casos: los buzones **sin**
   soporte de *push* (IMAP genérico) y la **pérdida de notificaciones**, que ningún mecanismo de
   *push* garantiza evitar.
3. **El escalonamiento es parte de la decisión.** Los sondeos se distribuyen en el tiempo de forma
   determinista por identificador de buzón, para que la carga contra cada proveedor sea plana y no
   una ráfaga sincronizada.
4. **La reconciliación se implementa como carga episódica**, que es el caso acotado de *serverless*
   que [ADR-0001](ADR-0001-estilo-arquitectonico.md) contempló.

### Consecuencias

* **Bueno,** porque reduce la carga contra terceros en **tres órdenes de magnitud**, haciendo
  viables a la vez QA-01, CRN-09 y CRN-08.
* **Bueno,** porque la carga del sistema sigue a la actividad real de los usuarios: durante una
  disrupción sube junto con la necesidad, en lugar de estar siempre en el máximo.
* **Bueno,** porque la cobertura es completa: ningún buzón queda sin atender, aunque su proveedor
  no ofrezca notificaciones.
* **Bueno,** porque el sistema es resistente a la pérdida de notificaciones, que es un modo de
  falla real y silencioso.
* **Malo,** porque hay **dos caminos de ingesta** en lugar de uno, y los dos tienen que converger
  al mismo resultado. Esto convierte la **idempotencia** de la ingesta en un requisito duro: la
  misma reserva puede llegar por *push* y por reconciliación. Queda registrado como CRN-12 y
  asignado a la iteración 2.
* **Malo,** porque exige gestionar el ciclo de vida de 9 millones de suscripciones: creación,
  renovación periódica y baja al revocarse el consentimiento. Es trabajo que el sondeo no tendría.
* **Malo,** porque la frescura de los buzones que dependen solo de reconciliación (IMAP genérico)
  **no cumple el objetivo de 5 minutos**. Esta es una limitación honesta de la decisión: para esos
  buzones el objetivo de QA-01 se declara inalcanzable y se fija uno propio, a definir en la
  iteración 3 junto con la política de intervalos.
* **Neutro,** porque crea dependencia de mecanismos específicos de cada proveedor de correo, lo que
  es exactamente lo que la capa de anticorrupción de [ADR-0006](ADR-0006-capa-de-anticorrupcion.md)
  está ahí para contener.

### Confirmación

* **Medición del tramo de notificación:** retardo entre el momento en que el proveedor registra el
  mensaje y el momento en que `mail-ingest` lo recibe. Debe estar por debajo de los 60 s asignados
  en el presupuesto.
* **Prueba de idempotencia:** entregar la misma notificación dos veces y verificar que se crea
  **una sola** reserva.
* **Prueba de reconciliación:** descartar deliberadamente una notificación de *push* y verificar
  que el sondeo de reconciliación recupera el mensaje.
* **Verificación de la carga contra terceros:** el número de llamadas por hora a cada API de correo
  debe mantenerse por debajo de la cuota declarada del proveedor, con alerta al 70 %.

## Pros y contras de las opciones

### E1 — Sondeo uniforme cada 5 minutos

* Bueno, porque es la lectura literal del enunciado y no requiere interpretarlo.
* Bueno, porque funciona con cualquier proveedor, sin depender de mecanismos propietarios.
* Bueno, porque es trivial de razonar: no hay dos caminos ni suscripciones que mantener.
* **Malo, porque son 30.000 sondeos por segundo sostenidos:** excede las cuotas publicadas en
  órdenes de magnitud (CRN-09).
* **Malo, porque el costo es prohibitivo** para el beneficio: el 99,99 % de los sondeos no devuelve
  nada (CRN-08).
* Malo, porque la carga está siempre en el máximo, de modo que no queda margen elástico para el
  pico de QA-04.

### E2 — Sondeo con intervalo adaptativo

* Bueno, porque reduce la carga sin depender de mecanismos propietarios del proveedor.
* Bueno, porque mantiene un solo camino de ingesta, evitando el problema de idempotencia.
* **Malo, porque los buzones poco activos quedan fuera del objetivo de 5 minutos**, y un buzón
  poco activo puede recibir justamente la cancelación importante.
* Malo, porque reduce la carga pero no la elimina: sigue siendo mucho tráfico contra terceros.

### E3 — Notificación *push* exclusivamente

* Bueno, porque es la carga mínima posible y la frescura mejor.
* **Malo, porque IMAP genérico no ofrece un mecanismo comparable** (E-06): esos usuarios quedarían
  sin servicio.
* **Malo, porque ningún mecanismo de *push* garantiza la entrega:** una notificación perdida es una
  reserva que nunca aparece, en silencio. Es el peor modo de falla posible para MN-1.

### E4 — *Push* más sondeo de reconciliación escalonado

* Bueno, porque obtiene la frescura del *push* con la cobertura y la robustez del sondeo.
* Malo, porque son dos caminos, lo que obliga a resolver idempotencia (CRN-12).
* Malo, porque hay que gestionar millones de suscripciones.

## Más información

* Drivers: [QA-01](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-01--propagación-de-una-actualización-de-viaje),
  [AMB-03 y el cálculo del sondeo](../01-analisis-inicial/07-supuestos-y-carga-derivada.md#por-qué-el-sondeo-uniforme-es-inviable),
  [CRN-09](../01-analisis-inicial/06-concerns-arquitectonicos.md)
* Análisis comparativo: [iteración 1, paso 4, D4](../02-proceso-add/iteracion-1/paso-4-alternativas.md#d4--obtención-del-correo-del-usuario)
* Relacionados: [ADR-0006](ADR-0006-capa-de-anticorrupcion.md) contiene las diferencias entre proveedores; [ADR-0007](ADR-0007-identidad-y-comparticion.md) provee los tokens de uso acotado con que `mail-ingest` opera
* Pendiente: la política de intervalos de reconciliación y el objetivo de frescura propio para los buzones sin *push* se definen en la [iteración 3](../02-proceso-add/iteracion-3-plan.md)
