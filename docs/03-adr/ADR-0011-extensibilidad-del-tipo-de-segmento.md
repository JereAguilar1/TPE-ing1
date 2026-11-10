---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: QA-15, QA-02, QA-10, QA-11, RF-07, RF-14
---

# ADR-0011: Registro de tipos de segmento con esquema declarado y núcleo común

## Contexto y planteo del problema

QA-15 exige incorporar un medio de transporte nuevo (tren, autobús) tocando **a lo sumo dos
elementos**. Los cinco tipos de segmento comparten casi todo (un inicio y un fin, en tiempo y
lugar, con un operador) y difieren en detalles: el coche y el asiento de un tren, la categoría de
un auto, la habitación de un hotel.

El enunciado pide explícitamente prever «la integración futura de otros medios de transporte».
Si cada tipo nuevo obliga a tocar el esquema de datos, los adaptadores, las notificaciones, los
clientes y la analítica, QA-15 no se cumple.

## Drivers de decisión

* **QA-15** — agregar «tren» toca a lo sumo dos elementos.
* **QA-02** — el panel responde en 800 ms (80 ms para el acceso a datos).
* **QA-10, QA-11** — adaptadores y extractores deben poder validar su salida.
* **RF-07** — la agrupación en viajes no debe depender de cada tipo.
* **RF-14** — el plano analítico debe absorber tipos nuevos.

## Opciones consideradas

* **K1** — Herencia de tablas (una tabla base y una por tipo).
* **K2** — Tabla única con columnas dispersas por tipo.
* **K3** — Registro de tipos con esquema declarado.

Comparación completa: [iteración 2, paso 4, D11](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d11--extensibilidad-del-tipo-de-segmento).

## Resultado de la decisión

Se adopta **K3: un registro de tipos de segmento**. Cada segmento se separa en dos partes:

* Un **núcleo común** en columnas propias: tipo, orden, inicio, fin, operador, referencia, estado.
* Un **detalle** por tipo, validado contra el esquema que declara el descriptor del tipo.

Cada tipo se declara en un **descriptor versionado** que contiene:

| Campo del descriptor | Lo consume | Para qué |
|---|---|---|
| `esquemaDeDetalle` | `itinerary`, adaptadores, extractores | Validar el detalle |
| `rolEnViaje` (`traslado`, `alojamiento`, `movilidadLocal`) | `itinerary` (módulo `viajes`) | Agrupar sin conocer el tipo |
| `camposRelevantes` | `notification` | Decidir qué cambios avisan y con qué severidad |
| `presentacion` | BFF y clientes (`GET /tipos-de-segmento`) | Renderizar sin código por tipo |
| `dimension` | `event-pipeline` | Qué atributos pasan a `dim_tipo_segmento` ([ADR-0016](ADR-0016-modelo-dimensional-analitico.md)) |

**La regla del núcleo:** todo lo que se filtre, ordene, agrupe o deduplique pertenece al núcleo.
El detalle sirve para presentar y notificar, y no se indexa.

Un ejemplo de descriptor (`tren`) está en la
[iteración 2, §5.2](../02-proceso-add/iteracion-2/README.md#52-el-modelo-canónico).

### Consecuencias

* **Bueno,** porque agregar un tipo es agregar un descriptor y, a lo sumo, un complemento por canal
  de datos; ningún elemento existente cambia su código (QA-15).
* **Bueno,** porque `notification`, los BFF y el plano analítico leen el descriptor y no necesitan
  código nuevo por tipo.
* **Bueno,** porque un extractor mal hecho se detecta: su salida tiene que validar contra el
  esquema del tipo (QA-11).
* **Malo,** porque el detalle no se indexa. Un requisito futuro que necesite filtrar por un campo
  del detalle obliga a promoverlo al núcleo.
* **Malo,** porque hay que construir el registro y la validación, que es trabajo propio.
* **Neutro,** porque la validación contra «tren» encontró un defecto (los boletos abiertos no
  tienen hora), que se corrigió agregando `precision` (`instante` o `dia`) al inicio y al fin del
  núcleo.

### Confirmación

* **Prueba de QA-15 en el prototipo:** agregar el descriptor `tren` y verificar en el historial del
  repositorio que ningún archivo de código de un servicio de dominio cambió
  ([guías de extensión](../02-proceso-add/iteracion-4/guias-de-extension.md)).
* **Suite de conformidad de complementos:** la salida de todo adaptador y extractor valida contra
  el esquema de su tipo ([ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md)).
* **Revisión de las reglas de agrupación:** ninguna referencia a un tipo concreto en el módulo
  `viajes`.

## Pros y contras de las opciones

### K1 — Herencia de tablas

* Bueno, porque es la respuesta clásica de orientación a objetos y tiene integridad fuerte.
* **Malo, porque incumple QA-15 literalmente:** cada tipo es una tabla nueva, una migración y un
  mapeo en cada elemento que lee o escribe segmentos.
* Malo, porque la lectura necesita *joins* por tipo.

### K2 — Tabla única con columnas dispersas

* Bueno, porque es simple y rápida de leer.
* Malo, porque cada tipo agrega columnas y una migración.
* **Malo, porque falla en silencio:** sin un esquema por tipo nada define qué debe traer un
  segmento de tren, y la salida de un extractor defectuoso se acepta (debilita QA-11).

### K3 — Registro de tipos con esquema declarado

* Bueno, porque cumple QA-15 y alimenta notificaciones, presentación y analítica desde una sola
  declaración.
* Malo, porque cuesta construir el registro y aceptar que el detalle no se indexa.

## Más información

* Drivers: [QA-15](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte),
  [QA-02](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-02--tiempo-de-respuesta-del-panel-web),
  [QA-11](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-11--formato-de-correo-desconocido)
* Análisis comparativo: [iteración 2, paso 4, D11](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d11--extensibilidad-del-tipo-de-segmento)
* Qué toca agregar «tren»: [iteración 2, paso 7](../02-proceso-add/iteracion-2/paso-7-analisis.md#qué-toca-agregar-tren)
* Vistas afectadas: [módulos N2](../04-vistas/vista-modulos-nivel-2.md)
* Relacionados: [ADR-0006](ADR-0006-capa-de-anticorrupcion.md), [ADR-0010](ADR-0010-modelo-canonico-reserva-segmento-viaje.md), [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0016](ADR-0016-modelo-dimensional-analitico.md), [ADR-0027](ADR-0027-versionado-y-evolucion-de-contratos.md) (versionado de descriptores)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
