---
estado: aceptado
fecha: 2026-10-29
decisores: Juan Emilio Pardo, Francisco Lozano
consultados: Ivo Iriarte, Jeremias Aguilar
informados: equipo completo
iteracion: 4
drivers: QA-18, CRN-10, RF-15, RF-09, RF-10, QA-03
---

# ADR-0032: Dominio neutral al idioma, catálogos ICU externalizados en CDN y formateo local CLDR con instantes UTC más zona IANA

## Contexto y planteo del problema

Trotamundos atiende viajeros globales que consultan itinerarios que cruzan husos horarios, monedas y
convenciones culturales en distintos idiomas. El escenario **`QA-18`** y la inquietud **`CRN-10`**
exigen que la internacionalización (*i18n*) sea una propiedad estructural desde el inicio: incorporar
una región o idioma nuevo debe completarse en **`≤ 120 horas-persona`** (dominadas por la traducción),
con **`0` cadenas visibles embebidas en código** y **`0` modificaciones en elementos de lógica de
negocio**.

Además, en el dominio de viajes un error de localización temporal es crítico: si un vuelo despega de
Tokio a las `09:00` locales y la aplicación convierte ingenuamente la marca UTC al huso horario donde
hoy se encuentra el viajero (por ejemplo, Buenos Aires), le muestra el día y la hora equivocados.

## Drivers de decisión

* **QA-18** — `0` literales de interfaz o aviso en código, `0` elementos de lógica de negocio tocados
  y esfuerzo total `≤ 120 h-p` al incorporar una región nueva.
* **CRN-10** — internacionalización como propiedad estructural transversal (idioma, plurales, moneda,
  fechas y múltiples zonas horarias por viaje).
* **RF-15 / RF-09 / RF-10** — preferencia explícita de idioma y formato del usuario aplicada de manera
  consistente tanto en el panel (`app-web`, `app-movil`) como en los avisos asíncronos (`notification`).
* **QA-03** — no penalizar el primer pintado móvil (`≤ 1,4 s` en 4G) esperando descargas remotas de
  traducciones en el camino crítico de arranque.

## Opciones consideradas

* **G1** — Formatear mensajes, fechas y monedas dentro de cada microservicio de dominio según el
  idioma de la petición.
* **G2** — Empaquetar todos los recursos de idioma únicamente de forma estática dentro del binario de
  los clientes web y móvil.
* **G3** — Dominio completamente neutral al idioma (códigos canónicos ISO e instantes `UTC + IANA TZ`),
  catálogos `ICU MessageFormat` externalizados en el CDN de `edge` (con catálogo base pre-empacado en
  `app-movil`) y formateo nativo CLDR en los bordes de presentación.

## Resultado de la decisión

Se adopta **G3**:

1. **Neutralidad lingüística y temporal estricta en el dominio.** Ningún servicio de dominio ni de
   composición (`itinerary`, `sharing`, `support-liaison`, `preferences`, `bff-*`) produce ni persiste
   textos traducidos: emiten identificadores semánticos (`estado: Confirmada`, `motivoConflicto:
   HorarioDivergente`), códigos `ISO 3166-1` (país), `IATA/UN-LOCODE` (lugar), `ISO 4217` (moneda con
   entero menor o decimal exacto) y pares **`{ instanteUTC, zonaHorariaIANA }`** asociados al lugar
   físico de cada inicio y fin de segmento (`iteración 2 §5.2`).
2. **Catálogos externalizados `ICU MessageFormat`.** Todos los textos visibles —interfaz de `app-web` y
   `app-movil`, plantillas de correo/*push* de `notification` y etiquetas legibles de los descriptores
   `TipoDeSegmento`— viven fuera del código de negocio en paquetes versionados por idioma/región
   (`es-AR`, `es-ES`, `en-US`, `pt-BR`, `ja-JP`, etc.) con sintaxis estándar `ICU MessageFormat` para
   resolver género, interpolación y reglas de pluralización sin condicionales en código.
3. **Distribución sin impacto en `QA-03`.** Los catálogos se publican con *hash* de contenido e
   inmutabilidad en el CDN de `edge` ([ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md)).
   `app-movil` incluye en su paquete instalable el catálogo base para arrancar en frío en `0 ms` de
   red incluso sin señal, y descarga deltas actualizados en segundo plano; `notification` lee los
   catálogos cacheados en memoria al renderizar un aviso según el idioma guardado en su réplica local
   de `preferences`.
4. **Resolución jerárquica y formateo CLDR.** El idioma efectivo se resuelve en orden determinista:
   `preferencia explícita del usuario (RF-15)` → `cabecera Accept-Language / configuración del SO` →
   `idioma de respaldo regional`. El formateo de fechas, horas (siempre expresadas en la
   `zonaHorariaIANA` del lugar del tramo, aclarando el desplazamiento si difiere del huso actual del
   viajero), números y monedas se delega a las bibliotecas estándar **Unicode CLDR / `Intl`** de cada
   plataforma.

### Consecuencias

* **Bueno,** porque agregar un idioma o corregir una traducción no toca ni redespliega ningún servicio
  de dominio ni exige esperar aprobación en tiendas de aplicaciones móviles (`QA-18`).
* **Bueno,** porque elimina ambigüedades horarias en vuelos y trenes intercontinentales al preservar la
  zona IANA del evento físico.
* **Malo,** porque exige gobernar claves semánticas de traducción como un artefacto más del repositorio
  y verificar su completitud entre idiomas en CI.

### Confirmación

* **Regla de análisis estático en CI (`QA-18`):** *linter* obligatorio sobre `app-web`, `app-movil` y
  `notification` que rechaza cadenas literales visibles fuera de los catálogos `locales`, más un
  validador que comprueba paridad de claves e interpolaciones ICU entre el idioma base y cada idioma
  habilitado.
* **Prueba de husos horarios cruzados:** prueba unitaria y de contrato verificando que un segmento con
  salida en `Asia/Tokyo` se renderiza en hora local de Tokio independientemente del huso horario
  configurado en el navegador o teléfono del viajero.

## Pros y contras de las opciones

### G1 — Traducción y formateo dentro de los microservicios de dominio

* Bueno, porque entrega cadenas ya listas a clientes muy simples.
* **Malo, porque acopla el dominio a la presentación, fragmenta la caché por idioma y obliga a tocar
  servicios de negocio al sumar una región (`QA-18` incumplido).**

### G2 — Recursos de idioma compilados únicamente dentro de los binarios cliente

* Bueno, porque no requiere distribución desde CDN.
* **Malo, porque impide corregir traducciones sin publicar nueva versión en tiendas móviles y no cubre
  las plantillas asíncronas de `notification`.**

### G3 — Dominio neutral (`UTC + IANA TZ` / ISO) + catálogos ICU en CDN + CLDR nativo

* Bueno, porque cumple `QA-18` (`0` servicios de negocio tocados), protege `QA-03` y resuelve husos
  horarios de viaje de manera exacta.
* Malo, porque requiere validación automática de claves ICU en la tubería de construcción.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D32](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d32--estrategia-de-internacionalización-y-localización-qa-18-crn-10)
* Guía paso a paso verificada (`112 h-p ≤ 120 h-p`): [guias-de-extension.md §3](../02-proceso-add/iteracion-4/guias-de-extension.md#3-guía-cómo-incorporar-una-región-geográfica-nueva-verificación-de-qa-18)
* Vista afectada: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md)
* Relacionados: [ADR-0005](ADR-0005-capa-de-clientes-bff.md), [ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md), [ADR-0031](ADR-0031-residencia-de-datos-por-region.md)
