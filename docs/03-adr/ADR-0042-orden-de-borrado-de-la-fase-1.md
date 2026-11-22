---
estado: aceptado
fecha: 2026-11-22
decisores: Francisco Lozano
consultados: —
informados: equipo completo
iteracion: prototipo, paso 14 (precisión de ADR-0030)
drivers: QA-14, CON-10, CON-04, CRN-12
---

# ADR-0042: `identity-access` ordena el borrado de la fase 1 con una operación interna por servicio, guardando cada orden hasta que el servicio la confirma

## Contexto y planteo del problema

[ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md) decide la supresión en dos fases. En
la fase 1 (`< 24 h`), `identity-access` «ordena el borrado físico transaccional por `usuario_id`» en
`itinerary`, `preferences`, `sharing` y `support-liaison`, y [ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md)
suma al asistente virtual a esa lista. Ninguno de los dos dice **cómo** se da la orden, y ningún
contrato la declara.

El evento `CuentaSuprimida` no sirve: usa el `SobreSinUsuario` del AsyncAPI, que prohíbe el
`usuarioId` justamente para que el dato no viaje por el *broker*, y ADR-0040 dice que el asistente
no lo escucha. Un ADR aceptado no se edita: esta decisión precisa a ADR-0030.

## Drivers de decisión

* **QA-14 / CON-10:** borrado verificable de los datos personales en `< 24 h` en el plano operacional.
* **CON-04:** la operación tiene que estar en los contratos (*spec-driven*).
* **CRN-12:** ninguna orden se pierde si un servicio no responde en ese momento.
* No hacer viajar el `usuario_id` de una cuenta suprimida por el *broker*, donde queda retenido.

## Opciones consideradas

* **O1** — Un evento nuevo `BorradoOrdenado` con `usuarioId`, que consumen los servicios.
* **O2** — Una operación interna `DELETE /interno/usuarios/{usuarioId}` en cada servicio, que
  `identity-access` llama, guardando la orden hasta que el servicio la confirma.
* **O3** — Que cada servicio borre por su cuenta al vencer su retención.

## Resultado de la decisión

Se adopta **O2**:

1. Cada servicio operacional que guarda datos por usuario (`itinerary`, `support-liaison` y
   `virtual-assistant`; `preferences` y `sharing` cuando existan) declara en su contrato
   `DELETE /interno/usuarios/{usuarioId}` (cambio compatible, ADR-0027). Borra en una transacción
   toda fila con esa `usuario_id`, que por [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md)
   está en todas sus tablas, y responde `204`, también si no había nada (idempotente). Solo la llama
   `identity-access`, por la red interna (mTLS en producción): no la exponen los BFF.
2. `identity-access` guarda una orden por servicio en la **misma transacción** que la fase 1 local
   (tabla `orden_de_borrado`), la intenta enseguida y reintenta las que fallan en su trabajo
   periódico, con espera `5 s × 2^n` (tope 15 min, [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md)).
   Una orden pendiente pasadas las 24 h se registra como error operativo. Al confirmarse, la orden
   se borra: hasta entonces solo queda guardado el `usuario_id`.
3. `CuentaSuprimida` sigue igual: el plano analítico (fase 2) no cambia.

### Consecuencias

* **Bueno,** porque el `usuario_id` de una cuenta suprimida no queda retenido en el *broker*.
* **Bueno,** porque ninguna orden se pierde: si un servicio está caído, se reintenta hasta que
  confirme.
* **Bueno,** porque la operación queda en los contratos y se puede probar de punta a punta.
* **Malo,** porque `identity-access` conoce a qué servicios ordenar el borrado (una lista de
  configuración): un servicio nuevo con datos por usuario tiene que sumarse a esa lista.
* **Neutro,** porque es una interfaz interna nueva en servicios del núcleo; no la usa el asistente
  para su función, así que no contradice el «cero interfaces nuevas» de ADR-0034 para el módulo
  avanzado.

### Confirmación

* Prueba de que cada servicio borra todos los datos del usuario y deja los de los demás, de forma
  idempotente (`tests/test_supresion_fase1.py`).
* Prueba de que una orden que falla queda guardada y se cumple al reintentar.
* Escenario contra los contenedores: al suprimir la cuenta no queda nada del usuario en `itinerary`
  ni en el asistente, ni órdenes pendientes (`tests/escenarios/test_supresion_contenedores.py`).

## Pros y contras de las opciones

### O1 — Evento `BorradoOrdenado` con `usuarioId`

* Bueno, porque desacopla a `identity-access` de la lista de servicios.
* Malo, porque el `usuario_id` de una cuenta suprimida queda retenido en el *broker* durante su
  retención, lo que el `SobreSinUsuario` de `CuentaSuprimida` buscó evitar.

### O2 — Operación interna con orden guardada

* Bueno, porque nada queda en el *broker* y cada orden se confirma.
* Malo, porque `identity-access` mantiene la lista de servicios.

### O3 — Borrado por retención en cada servicio

* Malo, porque no cumple las 24 h de la fase 1: las retenciones son de días o meses.

## Más información

* [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md), [ADR-0040](ADR-0040-sesion-conversacional-y-privacidad.md).
* Contratos: `itinerary.yaml` 1.2.0, `support-liaison.yaml` 1.2.0, `virtual-assistant.yaml` 1.1.0.
