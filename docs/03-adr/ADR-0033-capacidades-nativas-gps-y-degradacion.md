---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Juan Emilio Pardo
consultados: Jeremias Aguilar, Francisco Lozano
informados: equipo completo
iteracion: 4
drivers: QA-17, QA-03, CON-10, RF-09
---

# ADR-0033: Evaluación espacial de ubicación en el dispositivo móvil con geocodificación previa y degradación automática sin GPS

## Contexto y planteo del problema

Cuando un viajero abre `app-movil` en medio de un traslado —llegando a un aeropuerto, en el andén de
una estación o frente a su hotel—, necesita ver de inmediato el tramo pertinente (puerta, asiento,
código de reserva o dirección de *check-in*) sin navegar menús. **`QA-17`** exige que el segmento
relevante quede visible en primer plano sin interacción adicional en **`≥ 90 %` de los casos**, y que
cuando el permiso de ubicación esté **denegado**, la aplicación degrade limpiamente mostrando el
itinerario completo ordenado por tiempo sin errores ni bloqueos.

Enviar coordenadas GPS continuas al servidor para decidir qué mostrar en pantalla introduciría tres
problemas graves: (1) crearía en el *backend* un registro sensible de movimientos físicos de millones
de personas (`CON-10`), (2) agregaría latencia de red al camino de arranque móvil (`QA-03`: `≤ 1,4 s`
en 4G) y (3) fallaría justamente en aviones, subterráneos o terminales con mala señal.

## Drivers de decisión

* **QA-17** — destacar automáticamente el segmento próximo o relevante en `≥ 90 %` de las aperturas en
  viaje activo y degradar sin fallos ni pérdida funcional si el permiso de ubicación está denegado.
* **CON-10** — minimización de datos personales y privacidad por diseño (evitar recolectar ni almacenar
  telemetría de ubicación del usuario en servidores).
* **QA-03 / RF-09** — mantener el arranque móvil por debajo de `1,4 s` sin viajes de red extra y
  funcionar sobre la instantánea local sin conectividad.

## Opciones consideradas

* **H1** — Enviar la posición GPS del teléfono al servidor (`bff-mobile`) en segundo plano o en cada
  apertura para que el *backend* ordene el panel.
* **H2** — Ordenar los segmentos únicamente por la hora actual del reloj del dispositivo, prescindiendo
  por completo del GPS.
* **H3** — Geocodificar una única vez los lugares de las reservas en ingesta (`E-16`), evaluar
  proximidad y ventana temporal localmente en `app-movil` al pasar a primer plano, y conmutar de forma
  transparente al selector cronológico cuando no hay permiso GPS o señal.

## Resultado de la decisión

Se adopta **H3**:

1. **Enriquecimiento geográfico único de lugares (sin datos del usuario).** Al consolidar una reserva
   en `itinerary-escritura`, si el `Lugar` del segmento (código IATA de aeropuerto, estación o
   dirección postal de alojamiento) no posee coordenadas en el catálogo cacheado de lugares, se
   consulta una sola vez el servicio externo de geocodificación (`E-16`, enviando únicamente el nombre
   o dirección comercial del establecimiento, nunca identidad del viajero). Las coordenadas `{ latitud,
   longitud }` viajan incluidas en el detalle del viaje `EnCurso` y quedan persistidas en la
   instantánea cifrada local de `app-movil` ([ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md)).
2. **Evaluación espacial *on-device* en primer plano (`contexto-ubicacion`).** Al abrir `app-movil`
   existiendo un viaje `EnCurso` y permiso de ubicación concedido («solo al usar la aplicación», sin
   rastreo en segundo plano), el módulo nativo `contexto-ubicacion` toma la lectura actual del sistema
   operativo (con tope no bloqueante de `150 ms` usando la última posición conocida si el fix tarda) y
   calcula en memoria local un puntaje combinado de **distancia Haversine** (`≤ 5 km` para aeropuertos,
   `≤ 1,5 km` para estaciones y alojamientos) y **ventana temporal** (`[-4 h, +2 h]` respecto del tramo
   o estadía activa), fijando la tarjeta contextual en el encabezado del panel. **Las coordenadas GPS
   del teléfono jamás se transmiten ni se registran en ningún servidor de Trotamundos.**
3. **Degradación determinista de primera clase.** Si el permiso de ubicación está denegado, desactivado
   a nivel sistema o sin lectura disponible, `contexto-ubicacion` aplica sin mostrar modales
   intrusivos ni reintentar permisos el selector puramente cronológico (siguiente segmento activo o en
   curso según `{ instanteUTC, zonaHorariaIANA }` y reloj local), conservando el `100 %` de las
   acciones e información del itinerario.

### Consecuencias

* **Bueno,** porque alcanza el `≥ 90 %` de pertinencia contextual de `QA-17` funcionando incluso en
  modo avión o subte, con `0 ms` de latencia de red adicional en el arranque (`QA-03`).
* **Bueno,** porque elimina por completo la superficie regulatoria y de seguridad de almacenar la
  geolocalización física de los usuarios (`CON-10`).
* **Malo,** porque requiere mantener en `app-movil` el puente nativo de ubicación de solo primer plano
  y cachear en *backend* las coordenadas de lugares frecuentes para acotar llamadas a `E-16` (`CRN-09`).

### Confirmación

* **Batería de escenarios simulados en `app-movil` (`QA-17`):** suite automatizada con `50` casos
  representativos de viajes multi-segmento (llegada temprana al aeropuerto, escala con demora, arribo
  al hotel, trasbordo ferroviario) inyectando coordenadas simuladas y verificando que `≥ 90 %`
  seleccionan el segmento esperado.
* **Prueba de degradación y privacidad:** prueba automatizada con permiso de ubicación revocado y modo
  avión verificando renderizado completo sin errores, más inspección de tráfico HTTP comprobando que
  ninguna petición hacia `bff-mobile` incluye coordenadas del dispositivo.

## Pros y contras de las opciones

### H1 — Envío de GPS del usuario al servidor

* Bueno, porque centraliza el cálculo en el *backend*.
* **Malo, porque recolecta datos de geolocalización altamente sensibles (`CON-10`), penaliza `QA-03`,
  consume batería y deja de funcionar sin señal móvil.**

### H2 — Selección exclusivamente por reloj sin GPS

* Bueno, porque no solicita permisos del sistema operativo.
* **Malo, porque falla cuando el usuario llega varias horas antes a la terminal, sufre reprogramaciones
  encadenadas o tiene alojamiento y traslado superpuestos el mismo día (`QA-17`).**

### H3 — Geocodificación única de lugares + cruce espacial en el dispositivo + caída a reloj

* Bueno, porque combina precisión contextual, funcionamiento *offline*, cero impacto en latencia y
  privacidad total por diseño.
* Malo, porque exige geocodificar direcciones postales de alojamientos al ingerir la reserva.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D33](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d33--capacidades-nativas-de-ubicación-gps-y-degradación-en-móvil-qa-17)
* Vistas afectadas: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md), [vista-seguridad-y-datos](../04-vistas/vista-seguridad-y-datos.md)
* Relacionados: [ADR-0005](ADR-0005-capa-de-clientes-bff.md), [ADR-0019](ADR-0019-cache-camino-lectura-arranque-movil.md), [ADR-0024](ADR-0024-cortacircuitos-reintentos-y-cuotas.md)
