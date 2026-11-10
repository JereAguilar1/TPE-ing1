---
estado: aceptado
fecha: 2026-10-28
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 2
drivers: QA-11, RF-03, RF-04
---

# ADR-0015: Umbrales de confianza por extractor con tres bandas y confirmación del usuario en la banda media

## Contexto y planteo del problema

El riesgo **R-2** (fragilidad de la extracción desde correo) es el más frágil del diseño: los
formatos de correo cambian sin aviso. QA-11 pide dos cosas que tiran en direcciones opuestas:

* **0 % de extracción incorrecta silenciosa.**
* **95 % de acierto** sobre los 20 remitentes más frecuentes.

Un umbral de confianza muy alto sacrifica cobertura y devuelve al usuario a revisar su correo. Uno
muy bajo contamina el itinerario. Además, la confianza que reporta un extractor **no está
calibrada igual** entre extractores: un 0,9 de un formato estable y un 0,9 de uno con plantillas
cambiantes no significan lo mismo.

## Drivers de decisión

* **QA-11** — 0 % silenciosa y 95 % de acierto.
* **RF-03** — extraer y normalizar reservas desde el correo.
* **RF-04** — un remitente permitido cuyo formato no se reconoce no debe ignorarse en silencio.

## Opciones consideradas

* **O1** — Umbral fijo global.
* **O2** — Umbral por remitente (por extractor).
* **O3** — Confirmación del usuario por debajo del umbral.
* **O2 + O3, con dos umbrales (tres bandas).**

Comparación completa: [iteración 2, paso 4, D15](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d15--política-de-confianza-de-extracción-qa-11).

## Resultado de la decisión

Se adopta **O2 + O3: dos umbrales por extractor que dividen el resultado en tres bandas.**

| Banda | Condición | Qué ocurre |
|---|---|---|
| **Alta** | Confianza ≥ umbral alto del extractor **y** validación estructural superada | La reserva entra como `Confirmada`, con origen «correo», y se avisa que se agregó |
| **Media** | Entre el umbral bajo y el alto | Entra como `PorConfirmar`: sección propia del panel, **no** en el itinerario confirmado y **no** dispara avisos críticos. El usuario confirma, corrige o descarta |
| **Baja** | Menor que el umbral bajo, o ningún extractor reconoce el formato | **No entra nada.** Se publica `ExtraccionNoReconocida` y se ofrece la carga manual |

La confianza de una reserva es el **mínimo** de la confianza de sus campos obligatorios, no el
promedio. Los umbrales iniciales son **0,90 y 0,60**, un supuesto a calibrar con el corpus del
prototipo, no un driver.

La decisión incluye cinco mecanismos medibles que mitigan R-2:

| # | Mecanismo | Cómo se verifica |
|---|---|---|
| 1 | Corpus de referencia por extractor (correos anonimizados con salida esperada) | Puerta de integración continua: ≥ 95 % de acierto y **cero** errores en la banda alta |
| 2 | Validación estructural previa al puntaje (fin posterior al inicio, localizador con patrón del emisor, lugar resoluble, zona horaria presente) | Cualquier falla fuerza la banda media o baja |
| 3 | Observabilidad por extractor: proporción de cada banda y correcciones del usuario sobre la banda alta | Panel y alarma por extractor |
| 4 | **Disyuntor de calidad:** si las correcciones o la banda baja superan un umbral, el extractor pasa a «solo confirmación» | Prueba con corpus degradado: el disyuntor debe abrirse |
| 5 | Modo sombra para versiones nuevas de un extractor | Se promueve solo si no empeora el corpus ni la comparación |

### Consecuencias

* **Bueno,** porque ningún dato dudoso entra como confirmado: la regla de «no inventar» pasa a ser
  medible.
* **Bueno,** porque la revisión del usuario queda acotada a la banda media.
* **Bueno,** porque cada extractor se calibra contra su propio formato.
* **Malo,** porque hay que construir y mantener un corpus por extractor.
* **Malo,** porque un formato nuevo, sin corpus, no está cubierto hasta que alguien lo agregue. Por
  eso R-2 queda **mitigado, no cerrado** (el tratamiento del formato desconocido se completa en
  [ADR-0035](ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md)).
* **Neutro,** porque el 95 % solo es cierto sobre el corpus, no sobre el universo de correos.

### Confirmación

* **Puerta de integración continua** con el corpus de cada extractor (mecanismo 1).
* **Prueba de QA-11:** un correo de formato desconocido no crea ninguna reserva y publica
  `ExtraccionNoReconocida`.
* **Prueba del disyuntor:** con el corpus degradado, el extractor pasa a «solo confirmación».

## Pros y contras de las opciones

### O1 — Umbral fijo global

* Bueno, porque es lo más simple.
* **Malo, porque la confianza no está calibrada igual entre extractores:** un mismo número es laxo
  para unos y estricto para otros.

### O2 — Umbral por extractor

* Bueno, porque se calibra contra el corpus de cada formato.
* Malo, porque por sí solo no dice qué hacer con lo que queda entre umbrales.

### O3 — Confirmación del usuario

* Bueno, porque nada entra sin revisión.
* **Malo, porque sola convierte el sistema en un formulario de revisión**, anulando su propuesta
  de valor.

### O2 + O3 con tres bandas

* Bueno, porque combina calibración por formato con revisión acotada.
* Malo, porque exige calibrar y mantener cada extractor.

## Más información

* Drivers: [QA-11](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-11--formato-de-correo-desconocido),
  [RF-03, RF-04](../01-analisis-inicial/03-requisitos-funcionales.md)
* Análisis comparativo: [iteración 2, paso 4, D15](../02-proceso-add/iteracion-2/paso-4-alternativas.md#d15--política-de-confianza-de-extracción-qa-11)
* Interior de `booking-extraction`: [iteración 2, §5.3](../02-proceso-add/iteracion-2/README.md#53-booking-extraction) y [vista de módulos N2](../04-vistas/vista-modulos-nivel-2.md)
* Relacionados: [ADR-0006](ADR-0006-capa-de-anticorrupcion.md), [ADR-0011](ADR-0011-extensibilidad-del-tipo-de-segmento.md), [ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md), [ADR-0035](ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md)
* Nota de registro: la decisión se tomó en la iteración 2 (2026-10-28); este archivo MADR se
  consolidó el 2026-11-10 a partir del paso 4, sin cambiar el contenido de la decisión.
