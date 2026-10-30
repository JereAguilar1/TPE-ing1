---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Francisco Lozano
consultados: Juan Emilio Pardo, Jeremias Aguilar
informados: equipo completo
iteracion: 4
drivers: QA-14, CON-10, QA-09, CRN-08, RF-08, RF-14, AMB-08, AMB-09
---

# ADR-0030: Bitácora de auditoría inmutable y supresión verificable de datos personales en dos fases sobre ambos planos

## Contexto y planteo del problema

El cumplimiento del **GDPR** (Arts. 15, 17 y 30) y de la **Ley 25.326 de Protección de Datos
Personales** de Argentina (`CON-10`), operacionalizado en **`QA-14`**, exige dos capacidades con plazos
estrictos:

1. Entregar ante solicitud del titular o auditoría regulatoria el **inventario completo de sus datos
   personales y el historial de quién accedió a ellos en `≤ 72 horas`**.
2. Ejecutar la **supresión verificable de sus datos personales en `≤ 30 días` en el `100 %` de los
   almacenes del sistema, incluido `analytics-store`**, cerrando el problema técnico que
   [ADR-0003](ADR-0003-separacion-planos.md) dejó explícitamente abierto en la iteración 1: en un
   almacén columnar sobre objetos Parquet inmutables, reescribir archivos masivos tras cada baja
   individual multiplica costos (`CRN-08`) y compite con las consultas analíticas (`QA-09`), pero
   conservar indefinidamente filas por seudónimo fijo con tabla de reidentificación viva sigue siendo
   dato personal según GDPR Art. 4(5).

## Drivers de decisión

* **QA-14** — exportación de inventario e historial de accesos en `≤ 72 h` y supresión verificable en
  el `100 %` de los almacenes en `≤ 30 días`.
* **CON-10** — cumplimiento normativo integral (GDPR y Ley 25.326): minimización, limitación de plazo
  de conservación y derechos ARCO/GDPR.
* **QA-09 / CRN-08 / RF-14** — no degradar el plano operacional ni disparar el costo de almacenamiento
  de objetos, preservando métricas históricas agregadas anónimas de negocio.
* **AMB-08 / AMB-09** — distinción entre archivar y eliminar viajes, y no persistir jamás el cuerpo
  crudo de los correos electrónicos.

## Opciones consideradas

* **E1** — Borrar únicamente en el plano operacional y mantener intacto `analytics-store` alegando que
  usa seudónimos.
* **E2** — Reescribir de forma inmediata las particiones Parquet de `analytics-store` ante cada baja
  individual de un usuario.
* **E3** — Cripto-supresión pura sin compactar nunca los objetos columnares del plano analítico.
* **E4** — Bitácora de auditoría inmutable encadenada + protocolo de supresión verificable en dos
  fases: borrado físico OLTP y destrucción inmediata de `DEK_u` y del mapa de seudónimo (`< 24 h`),
  seguidos de exclusión inmediata en lectura y compactación Parquet quincenal (`≤ 25 días < 30 días`)
  que purga filas individuales preservando contadores agregados anónimos.

## Resultado de la decisión

Se adopta **E4**:

1. **Minimización en origen y catálogo normativo.** Tal como fijó `AMB-09`, Trotamundos **jamás
   persiste el cuerpo crudo de los correos** (se descarta en memoria apenas `booking-extraction` emite
   el resultado). El inventario exhaustivo de categorías, almacenes, bases legales y plazos de
   retención se mantiene en la
   [vista de seguridad y datos](../04-vistas/vista-seguridad-y-datos.md#4-catálogo-de-datos-personales-con-10--qa-14).
2. **Bitácora de auditoría inmutable y exportación en `< 2 horas` (`≤ 72 h`).** `auditoria-y-revocacion`
   persiste `registro_auditoria` en modo *append-only* con encadenamiento criptográfico `SHA-256` por
   lote diario (cualquier adulteración rompe la cadena verificable), registrando actor autenticado,
   acción, recurso, motivo y marca temporal sobre accesos a tokens, viajes compartidos, casos de
   soporte y cambios administrativos. Ante un pedido de acceso/portabilidad (`GET/POST
   /privacidad/exportaciones`), un flujo asíncrono recolecta por clave de partición `usuario_id` los
   registros de todos los módulos operacionales más el historial de auditoría y entrega un paquete
   firmado en **`< 2 horas`** (`≤ 72 h`).
3. **Supresión verificable en dos fases dentro de los `30 días` (`DELETE /privacidad/cuenta`):**
   * **Fase 1 — Plano operacional y desvinculación criptográfica (`< 24 horas`):** `identity-access`
     revoca los consentimientos OAuth activos en los proveedores externos, ordena el borrado físico
     transaccional por `usuario_id` en el *bucket* correspondiente de `itinerary`, `preferences`,
     `sharing`, `support-liaison`, la caché regional y los viajes archivados en almacenamiento frío, y
     **destruye irrecuperablemente la clave `DEK_u` ([ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md))
     junto con la fila en `mapa_seudonimo_usuario`**. Con ello, cualquier copia de respaldo o registro
     testigo previo queda criptográficamente indescifrable de inmediato, y el `seudonimo_analitico`
     queda huérfano de identidad real.
   * **Fase 2 — Plano analítico columnar (`≤ 25 días`, cumpliendo `≤ 30 días`):** al emitirse el
     evento interno `CuentaSuprimida(seudonimo_analitico)` (sin PII), `event-pipeline` inserta al
     instante el seudónimo en `lista_supresion_analitica`, filtrada por todas las vistas de consulta
     de `analytics-store` desde el primer minuto (`R6` intacta: sin cruzar conexiones con OLTP). Cada
     **`15 días`** en horario valle, un trabajo de compactación agrupa todas las bajas de la quincena,
     reescribe una sola vez las particiones Parquet afectadas eliminando las filas individuales por
     `seudonimo_analitico` (consolidando su contribución únicamente en cubos agregados anónimos con
     umbral `k ≥ 50`), y registra el acta firmada de finalización antes del día `30`.

### Consecuencias

* **Bueno,** porque cierra con solidez técnica y legal el pendiente de `ADR-0003`, garantizando `0`
  registros personales recuperables en el `100 %` de los almacenes antes de los `30 días` sin perder
  métricas agregadas lícitas de negocio (`RF-14`).
* **Bueno,** porque agrupar las reescrituras Parquet cada `15 días` reduce en más de dos órdenes de
  magnitud el costo de I/O frente al borrado unitario continuo (`CRN-08`) y corre aislado del plano
  operacional (`QA-09`).
* **Malo,** porque requiere mantener la tabla `mapa_seudonimo_usuario` confinada en `identity-access`
  para traducir `usuario_id → seudonimo_analitico` justo en el instante de iniciar la baja antes de
  destruir ese vínculo.

### Confirmación

* **Prueba extremo a extremo de derecho al olvido (`QA-14`):** prueba automatizada sobre un usuario
  sintético con reservas activas, viajes archivados, comparticiones, entradas en caché y hechos en
  `analytics-store`; tras ejecutar la supresión y el barrido de compactación, una sonda de auditoría
  consulta todos los almacenes (OLTP, caché, frío, Parquet y copias cifradas sin `DEK_u`) y verifica
  `0` coincidencias legibles o vinculables, más la emisión del comprobante auditable.
* **Prueba de plazo de exportación:** verificar que el paquete de inventario e historial de accesos se
  genere con firma válida e integridad de cadena de auditoría en `< 72 h`.

## Pros y contras de las opciones

### E1 — Borrar solo en OLTP y dejar intacto `analytics-store`

* Bueno, porque no toca archivos Parquet.
* **Malo, porque incumple GDPR y `QA-14` («100 % de los almacenes, incluido el analítico»).**

### E2 — Reescribir Parquet inmediatamente por cada solicitud individual

* Bueno, porque purga el archivo columnar en minutos.
* **Malo, porque provoca amplificación masiva de escritura sobre objetos grandes y encarece
  desproporcionadamente `analytics-store`.**

### E3 — Cripto-supresión sin compactar nunca Parquet

* Bueno, porque es instantánea para respaldos cifrados.
* **Malo, porque en tablas analíticas columnares que se consultan descifradas deja trayectorias
  individuales por seudónimo que un auditor regulatorio puede objetar.**

### E4 — Bitácora inmutable + borrado OLTP y cripto-supresión (`< 24 h`) + compactación Parquet quincenal (`≤ 25 d`)

* Bueno, porque combina efecto inmediato, purga física verificable dentro de los `30 días` y costo
  operativo mínimo.
* Malo, porque añade un trabajo programado quincenal en `event-pipeline`.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D30](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d30--auditoría-e-implementación-de-supresión-de-datos-personales-en-ambos-planos-qa-14-con-10)
* Catálogo completo de datos personales: [vista-seguridad-y-datos §4](../04-vistas/vista-seguridad-y-datos.md#4-catálogo-de-datos-personales-con-10--qa-14)
* Relacionados: [ADR-0003](ADR-0003-separacion-planos.md), [ADR-0023](ADR-0023-particionamiento-y-crecimiento.md), [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md)
