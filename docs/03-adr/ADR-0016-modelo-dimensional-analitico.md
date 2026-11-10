---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: RF-14, QA-09, QA-15, CON-10
---

# ADR-0016: Esquema en estrella alimentado desde eventos de dominio retenidos crudos

## Contexto y planteo del problema

El equipo de datos va a monetizar tendencias, destinos y cancelaciones con **consultas pesadas
sobre tres años de historia**, con frescura de hasta 1 hora (AMB-07).
[ADR-0003](ADR-0003-separacion-planos.md) ya separó el plano analítico del operacional; falta
decidir **qué forma tienen los datos** en el plano analítico.

El modelo tiene que absorber tipos de segmento nuevos sin rediseño (QA-15), dar resultados
consistentes entre consultas de distintos analistas y no exponer datos personales (previendo
CON-10).

## Drivers de decisión

* **RF-14** — consultas analíticas sobre tendencias, destinos y cancelaciones.
* **QA-09** — la carga analítica no degrada la operación.
* **QA-15** — un tipo de segmento nuevo no obliga a rediseñar el modelo analítico.
* **CON-10** — normativa de datos personales.

## Opciones consideradas

* **P1** — Esquema en estrella (hechos y dimensiones conformes).
* **P2** — Tabla ancha desnormalizada.
* **P3** — Eventos crudos con vistas.
* **P1 sobre P3 como capa de aterrizaje.**

Comparación completa: [iteración 2, paso 4, D16](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d16--modelo-dimensional-del-plano-analítico-rf-14).

## Resultado de la decisión

Se adopta **P1 alimentado desde P3**: los eventos de dominio se retienen crudos (inmutables) y de
ellos se construyen, en micro-lotes, los hechos y las dimensiones.

| Hecho | Granularidad | Medidas principales |
|---|---|---|
| `hecho_cambio_reserva` | Transaccional: una fila por evento de reserva (creada, actualizada, cancelada, unificada) | Cantidad, anticipación en días, proporción de cambios por fuente |
| `hecho_viaje` | *Snapshot* acumulativo: una fila por viaje, con hitos de creado, iniciado, completado y archivado | Reservas, segmentos, duración, cancelaciones, disrupciones, conflictos |

Seis dimensiones: `dim_fecha`, `dim_tipo_segmento` (alimentada desde el registro de tipos de
[ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md): **tipo nuevo = fila nueva**),
`dim_proveedor` (SCD tipo 2), `dim_lugar`, `dim_fuente` y `dim_usuario`, que guarda un
**seudónimo** y no datos personales.

El detalle está en la
[iteración 2, §5.9](../02-proceso-add/iteracion-2/README.md#59-el-modelo-dimensional-del-plano-analítico).

### Consecuencias

* **Bueno,** porque si el modelo dimensional cambia, se reconstruye desde los eventos crudos sin
  tocar el plano operacional.
* **Bueno,** porque las dimensiones compartidas dan resultados consistentes entre consultas.
* **Bueno,** porque un tipo de segmento nuevo es una fila en `dim_tipo_segmento`, no una columna.
* **Bueno,** porque el seudónimo en `dim_usuario` deja el plano analítico sin datos personales
  directos; la supresión completa se resolvió en la iteración 4
  ([ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)).
* **Malo,** porque hay dos copias de los datos (eventos crudos y modelo dimensional) y un proceso
  de transformación que operar.
* **Neutro,** porque la frescura de 1 hora admite micro-lotes y no exige procesamiento continuo.

### Confirmación

* **Prueba de reconstrucción:** regenerar los hechos desde los eventos crudos produce el mismo
  resultado.
* **Prueba de QA-15:** agregar el descriptor `tren` produce una fila en `dim_tipo_segmento` sin
  cambiar el esquema.
* **Revisión de esquema:** ninguna columna del plano analítico contiene un dato personal directo
  (nombre, correo, teléfono).

## Pros y contras de las opciones

### P1 — Esquema en estrella

* Bueno, porque es el modelo estándar para consultas analíticas y escala bien.
* Malo, porque solo, sin capa cruda, no se puede reconstruir si cambia.

### P2 — Tabla ancha desnormalizada

* Bueno, porque es la más rápida de construir y de consultar para lo previsto.
* **Malo, porque envejece mal:** los atributos de cada tipo la llenan de columnas casi vacías, y
  cada tipo nuevo cambia la tabla que usan todas las consultas.

### P3 — Eventos crudos con vistas

* Bueno, porque es flexible y absorbe tipos nuevos.
* **Malo, porque cada analista reinterpreta el JSON en cada consulta**, con resultados que
  difieren y un costo de consulta alto.

### P1 sobre P3

* Bueno, porque combina consultas eficientes y consistentes con la capacidad de reconstruir.
* Malo, porque duplica almacenamiento y agrega una transformación.

## Más información

* Drivers: [RF-14](../01-analisis-inicial/03-requisitos-funcionales.md),
  [QA-09](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica),
  [QA-15](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte)
* Análisis comparativo: [iteración 2, paso 4, D16](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d16--modelo-dimensional-del-plano-analítico-rf-14)
* Recorrido: [UC-6](../04-vistas/secuencias-casos-primarios.md)
* Relacionados: [ADR-0003](ADR-0003-separacion-planos.md), [ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md), [ADR-0030](ADR-0030-auditoria-y-supresion-datos-personales.md)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
