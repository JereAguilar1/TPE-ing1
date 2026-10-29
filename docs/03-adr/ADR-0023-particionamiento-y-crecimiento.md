---
estado: aceptado
fecha: 2026-10-29
decisores: Francisco Lozano, Ivo Iriarte
consultados: Jeremias Aguilar, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: QA-08, QA-02, CRN-08
---

# ADR-0023: Particionamiento por *hash* consistente sobre `usuario_id` (64 *buckets*), división en línea y archivo frío

## Contexto y planteo del problema

En su punto de partida, Trotamundos opera con `15 millones` de cuentas registradas, `2 millones` de
usuarios activos semanales (WAU) y un almacén operacional de aproximadamente `12 TB` ([1.7 Supuestos y
carga derivada](../01-analisis-inicial/07-supuestos-y-carga-derivada.md)). El escenario `QA-08` exige
absorber la duplicación de volumen en 12 meses (`30 M` de cuentas y `4 M` de WAU) agregando capacidad
horizontal **sin detener el servicio (`0 s` de inactividad)**, **sin modificar contratos entre
elementos** y logrando que **el costo de infraestructura crezca a lo sumo de forma lineal con los
usuarios activos**.

Un único primario vertical por región choca contra límites físicos de escritura e IOPS y exhibe una
curva de precios supralineal; un particionamiento improvisado sobre el número actual de servidores
obliga a reparticionar deteniendo escrituras cuando ese número cambia; y retener indefinidamente en
almacenamiento SSD caliente las observaciones crudas y los viajes de años anteriores hace que el
costo crezca con la historia acumulada en vez de acompañar a los usuarios activos.

## Drivers de decisión

* **QA-08** — duplicar de `15 M` a `30 M` de cuentas (`2 M` a `4 M` WAU) con `0 s` de inactividad,
  sin cambios de contrato y con crecimiento de costo `≤ lineal` respecto de los usuarios activos.
* **QA-02** — acceso al almacén de lectura en `≤ 80 ms` sin *joins* distribuidos entre fragmentos.
* **CRN-08** — contención del gasto mensual de almacenamiento operacional caliente.

## Opciones consideradas

* **W1** — Escalado vertical del nodo primario por región más réplicas de lectura adicionales.
* **W2** — Particionamiento por rango (fecha de alta de la cuenta o inicial de país/apellido).
* **W3** — Particionamiento por *hash* consistente sobre `usuario_id` en **64 particiones lógicas
  (*buckets*)** por región con división en línea de fragmentos físicos, compactación asíncrona de
  observaciones y archivo frío por antigüedad.

## Resultado de la decisión

Se adopta **W3**:

1. **Clave de partición uniforme `hash(usuario_id)` con colocalización total.** Aprovechando el
   diseño lógico de la iteración 2 (`ADR-0010` y `ADR-0012`), todas las tablas operacionales de
   `itinerary` (`reserva`, `segmento`, `observacion`, `conflicto`, `viaje`, `panel_usuario`,
   `bandeja_entrada`, `bandeja_salida`), así como las de `preferences` y `notification`, llevan
   `usuario_id` como prefijo de su clave primaria y de partición dentro de la `región_primaria` del
   usuario ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md)). Ninguna consulta ni transacción
   del camino crítico cruza fragmentos distintos; la compartición (`RF-11`) resuelve el viaje por la
   tupla `(usuario_id_dueño, viaje_id)` codificada en el enlace o recurso compartido.
2. **64 *buckets* lógicos fijos sobre fragmentos físicos elásticos.** Cada región divide el espacio de
   *hash* en **64 particiones virtuales** desde el primer día, mapeadas inicialmente sobre `4`
   fragmentos físicos (*shards*). Para pasar a `30 M` de cuentas (`QA-08`), la plataforma reasigna
   subconjuntos de *buckets* hacia `8` o `16` fragmentos físicos mediante replicación lógica continua
   y conmutación atómica del mapa de enrutamiento por *bucket* (`< 500 ms` de pausa de cola interna,
   `0 s` de caída percibida y **cero cambios en esquemas o contratos**).
3. **96 particiones por tópico regional en el *broker*.** Los tópicos de dominio se crean con `96`
   particiones enrutadas por `usuario_id`, habilitando escalar horizontalmente hasta `96` consumidores
   por región sin necesidad de recrear tópicos ni perder el orden por usuario.
4. **Ciclo de vida y contención del volumen caliente (`CRN-08` / `QA-08`):**
   * `bandeja_entrada` y `bandeja_salida` se particionan por día y se purgan mediante `DROP PARTITION`
     instantáneo pasados **14 días** (sin costo de `VACUUM` ni inflación de índices).
   * En viajes con estado `Archivado` desde hace más de **90 días**, un proceso de fondo compacta la
     tabla `observacion` conservando la última observación vigente por fuente más un resumen inmutable
     de auditoría, reduciendo en **`~60 %`** la huella de filas históricas.
   * Los detalles completos de viajes `Archivado` con más de **12 meses** de antigüedad se descargan a
     almacenamiento de objetos frío manteniendo en SSD únicamente la cabecera indexada del viaje; si
     el viajero abre un viaje antiguo (`RF-08`), `itinerary-lectura` lo hidrata bajo demanda.

### Consecuencias

* **Bueno,** porque el almacenamiento SSD caliente queda proporcional a los viajes vigentes y
  recientes (usuarios activos), permitiendo que al duplicar la escala (`2,00×`) el rubro de datos
  operacionales crezca apenas **`1,80×`** ([ADR-0026](ADR-0026-modelo-costo-y-camino-escalonado.md)).
* **Bueno,** porque desacopla para siempre la cantidad de particiones lógicas (`64`) de la cantidad de
  servidores físicos (`4 → 8 → 16`).
* **Malo,** porque las consultas globales entre distintos usuarios no pueden resolverse en el almacén
  operacional: deben ejecutarse exclusivamente en `analytics-store` ([ADR-0003](ADR-0003-separacion-planos.md)),
  lo cual refuerza además el aislamiento de `QA-09`.

### Confirmación

* **Ensayo de división en línea en preproducción (`QA-08`):** bajo carga sostenida de lectura y
  escritura, migrar `8` de los `64` *buckets* hacia un nuevo fragmento físico verificando `0` errores
  HTTP, `0` actualizaciones perdidas y `p95 ≤ 800 ms`.
* **Verificación de planes de ejecución:** auditoría en CI de que toda sentencia SQL operacional
  incluya `usuario_id` en el predicado `WHERE`, prohibiendo barridos entre múltiples *buckets* (*scatter-gather*).

## Pros y contras de las opciones

### W1 — Escalado vertical del primario regional

* Bueno, porque no requiere capa de enrutamiento de fragmentos.
* **Malo, porque tiene techo físico de escrituras y costo supralineal, incumpliendo `QA-08`.**

### W2 — Particionamiento por rango (fecha de alta o país)

* Bueno, porque facilita barridos secuenciales por cohorte.
* **Malo, porque genera fragmentos calientes severos (*hot shards*): los usuarios recién dados de alta
  o de una misma zona horaria concentran la carga al mismo tiempo.**

### W3 — *Hash* consistente sobre `usuario_id` + *buckets* lógicos + archivo por niveles

* Bueno, porque reparte carga de manera uniforme, colocaliza todo el grafo del viajero y escala sin
  corte de servicio.
* Malo, porque hidratar un viaje archivado hace más de un año suma `~150–250 ms` en la primera
  apertura de ese archivo histórico (fuera del camino crítico de `QA-02`, que mide viajes vigentes).

## Más información

* Análisis comparativo: [iteración 3, paso 4, D23](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d23--particionamiento-de-datos-y-plan-de-crecimiento-a-30-m-de-cuentas-qa-08)
* Relacionados: [ADR-0003](ADR-0003-separacion-planos.md), `ADR-0010`, `ADR-0012`, [ADR-0018](ADR-0018-consistencia-datos-multirregion.md), [ADR-0026](ADR-0026-modelo-costo-y-camino-escalonado.md)
