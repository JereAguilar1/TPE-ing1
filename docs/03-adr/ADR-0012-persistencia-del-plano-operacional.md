---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: QA-15, QA-02, QA-08, CRN-11, CRN-12, CON-09
---

# ADR-0012: Persistencia relacional con detalle semiestructurado y partición por `usuario_id`

## Contexto y planteo del problema

El modelo de [ADR-0010](ADR-0010-modelo-canonico-reserva-segmento-viaje.md) y
[ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md) necesita un almacenamiento que dé
**garantías transaccionales fuertes en tres puntos**:

1. Unicidad de los identificadores de una reserva por usuario (la deduplicación de
   [ADR-0013](ADR-0013-deduplicacion-y-conflictos.md) depende de eso).
2. Una bandeja de entrada de eventos con clave única (la idempotencia de
   [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md)).
3. La escritura del cambio junto con el evento a publicar (*outbox*).

Al mismo tiempo, el detalle por tipo de segmento varía y no debe obligar a migrar el esquema
(QA-15), el acceso a datos tiene un presupuesto de 80 ms dentro de los 800 ms de QA-02, y la
decisión no debe cerrar ninguna salida del riesgo R-1 (consistencia entre regiones).

## Drivers de decisión

* **QA-15** — un tipo de segmento nuevo no requiere migración.
* **QA-02** — 80 ms de acceso a datos en el camino de lectura.
* **CRN-11, CRN-12** — unicidad, bandeja de entrada y *outbox* transaccionales.
* **QA-08** — el almacenamiento debe crecer con la base de cuentas.
* **CON-09** — el equipo tiene más práctica con el modelo relacional.

## Opciones consideradas

* **L1** — Relacional normalizado, con esquema por tipo.
* **L2** — Documental, un documento por agregado.
* **L3** — Relacional con campos semiestructurados (JSON) para el detalle por tipo.

Comparación completa: [iteración 2, paso 4, D12](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d12--persistencia-del-modelo-canónico).

## Resultado de la decisión

Se adopta **L3: relacional, con el detalle por tipo en un campo JSON validado por el registro de
tipos**. Tres reglas forman parte de la decisión:

1. **Toda tabla del plano operacional lleva `usuario_id` como clave de partición.** Los agregados
   de un mismo usuario viven juntos, lo que es compatible con las dos salidas posibles de R-1.
2. **Las garantías críticas se expresan como restricciones de la base**, no como lógica de
   aplicación: único `(usuario_id, emisor, codigo)` en `reserva_identificador`, único
   `(reserva_id, fuente, id_de_fuente)` en `observacion`, único `(consumidor, evento_id)` en
   `bandeja_entrada`.
3. **Las observaciones se compactan:** se conservan las más recientes por fuente y las que dieron
   origen a un conflicto abierto; el resto queda resumido en el plano analítico por los eventos ya
   emitidos (QA-08).

El esquema completo de las diez tablas está en la
[iteración 2, §5.8](../02-proceso-add/iteracion-2/README.md#58-esquemas-de-persistencia-del-plano-operacional).

**Lo que esta decisión deja abierto a propósito:** el producto concreto y la topología de
replicación entre regiones. Elegirlos aquí sería decidir R-1 sin analizarlo; se resolvieron en la
iteración 3 ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md) y
[ADR-0023](ADR-0023-particionamiento-y-crecimiento.md)).

### Consecuencias

* **Bueno,** porque la deduplicación y la idempotencia descansan en restricciones de unicidad
  nativas, no en código que pueda divergir.
* **Bueno,** porque el *outbox* hace atómicos el cambio y su evento: no hay eventos perdidos ni
  eventos de cambios que no ocurrieron.
* **Bueno,** porque un tipo nuevo no requiere migración: el detalle es JSON validado.
* **Bueno,** porque la partición por usuario prepara el particionamiento físico y la región
  primaria por usuario de la iteración 3.
* **Malo,** porque las observaciones crecen sin cota si no se compactan; la compactación es un
  trabajo más que operar.
* **Malo,** porque las consultas sobre el detalle JSON son más lentas; la regla del núcleo de
  ADR-0011 las excluye del camino caliente.

### Confirmación

* **Revisión del esquema del prototipo:** las tres restricciones de unicidad existen y toda tabla
  tiene `usuario_id` en su clave.
* **Prueba de *outbox*:** una falla inyectada entre el cambio y la publicación no pierde ni duplica
  el evento.
* **Prueba de QA-15:** agregar el descriptor `tren` no genera ninguna migración de esquema.

## Pros y contras de las opciones

### L1 — Relacional normalizado

* Bueno, porque es el modelo más conocido por el equipo y tiene garantías nativas.
* **Malo, porque cada tipo de segmento es una migración** (incumple QA-15 y contradice ADR-0011).

### L2 — Documental

* Bueno, porque la flexibilidad del detalle es la misma que la de L3, y el agregado se lee en un
  acceso.
* Malo, porque la unicidad entre documentos y la publicación transaccional dependen del producto
  concreto y de transacciones entre documentos.
* Malo, porque el equipo tiene menos práctica con ese modelo.
* Neutro: queda como alternativa a reconsiderar si el detalle crece hasta dominar el modelo.

### L3 — Relacional con detalle semiestructurado

* Bueno, porque toma del modelo relacional las garantías que no se negocian y del documental la
  flexibilidad solo donde hace falta.
* Malo, porque exige compactar observaciones y aceptar que el detalle no se indexa.

## Más información

* Drivers: [QA-02](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-02--tiempo-de-respuesta-del-panel-web),
  [QA-08](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-08--crecimiento-de-la-base-de-cuentas),
  [QA-15](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte),
  [CRN-11 y CRN-12](../01-analisis-inicial/06-concerns-arquitectonicos.md)
* Análisis comparativo: [iteración 2, paso 4, D12](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d12--persistencia-del-modelo-canónico)
* Riesgo que genera: R-4, resuelto junto con R-1 en [ADR-0018](ADR-0018-consistencia-datos-multirregion.md)
* Relacionados: [ADR-0010](ADR-0010-modelo-canonico-reserva-segmento-viaje.md), [ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md), [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md), [ADR-0023](ADR-0023-particionamiento-y-crecimiento.md)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
