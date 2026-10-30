---
estado: aceptado
fecha: 2026-10-29
decisores: Juan Emilio Pardo, Jeremias Aguilar
consultados: Francisco Lozano, Ivo Iriarte
informados: equipo completo
iteracion: 4
drivers: CRN-14, QA-10, QA-15, QA-07, CRN-04, CON-04, CON-09
---

# ADR-0027: Evolución compatible de contratos por omisión, negociación de versión mayor y SemVer en complementos

## Contexto y planteo del problema

Trotamundos declara todas sus interfaces como artefactos explícitos ([ADR-0009](ADR-0009-contratos-spec-driven.md)):
especificaciones HTTP `OpenAPI` en el borde, los BFF y los servicios de dominio; `15` eventos de
dominio en `AsyncAPI` sobre el *broker* regional; los contratos de complementos
`AdaptadorDeProveedor` y `Extractor` ([ADR-0006](ADR-0006-capa-de-anticorrupcion.md)); y los
descriptores declarativos `TipoDeSegmento` (`D11`).

Al desplegar cada microservicio de manera independiente mediante entregas canarias progresivas por
región con reversión en `≤ 75 s` ([ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md)) y
atender aplicaciones móviles instaladas cuya actualización depende del usuario, conviven de forma
permanente productores en versión `N+1` con consumidores en versión `N` (y viceversa durante un
*rollback*). Sin una política normativa de evolución contractual (`CRN-14`), cualquier cambio rompe
clientes en producción; pero anteponer `/v1/`, `/v2/` en todas las rutas o duplicar tópicos por
versión multiplica la carga de mantenimiento de un equipo de cuatro personas (`CON-09`), invalida las
rutas canónicas ya fijadas en las iteraciones 2 y 3, fragmenta la caché regional (`ADR-0019`) y rompe
el orden estricto por `usuario_id` en el *broker*.

## Drivers de decisión

* **CRN-14** — reglas explícitas de versionado, evolución y retiro de los contratos publicados.
* **QA-10 / QA-15** — incorporar proveedores y nuevos medios de transporte sin cambios incompatibles
  ni rotura de datos históricos.
* **QA-07 / CRN-04 ([ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md))** — convivencia en vivo de versiones consecutivas durante canarios y reversiones sin tiempo de inactividad.
* **CON-04 / CRN-06** — verificación automatizada de contratos en integración continua.
* **CON-09** — sobrecarga mínima de mantenimiento para un equipo de cuatro integrantes.

## Opciones consideradas

* **A1** — Versionado sistemático en la ruta URL (`/v1/...`, `/v2/...`) y creación de tópicos nuevos
  por versión en el *broker*.
* **A2** — Evolución exclusivamente aditiva perpetua, prohibiendo para siempre retirar o cambiar la
  semántica de un campo.
* **A3** — Despliegue sincronizado (*lockstep*) de productor y consumidores ante cada cambio de
  interfaz.
* **A4** — Evolución compatible por omisión (*expand/contract* + *tolerant reader*), negociación por
  cabecera de medio únicamente ante rupturas mayores HTTP, `versionEsquema` con doble emisión acotada
  en eventos AsyncAPI y `SemVer` en manifiestos de complementos y descriptores.

## Resultado de la decisión

Se adopta **A4**, gobernando las cuatro familias de contratos del sistema con reglas verificables en
la tubería de integración continua:

1. **Regla general (*Evolution First* y *Tolerant Reader*).** Todo cambio cotidiano debe ser
   compatible hacia atrás y hacia adelante: solo se agregan rutas nuevas, parámetros opcionales con
   valor por omisión o atributos nuevos en respuestas y eventos. Todo consumidor ignora campos
   desconocidos sin fallar y jamás depende del orden de claves en objetos JSON.
2. **Contratos HTTP (`OpenAPI`).** Se preservan las rutas canónicas de recursos sin prefijo de versión
   (`GET /panel`, `GET /panel/resumen`, `GET /viajes/{id}`, `POST /reservas`, `POST /casos`). Cuando
   un cambio excepcional exija romper compatibilidad (`MAJOR`), el servidor negocia la representación
   mediante `Accept: application/vnd.trotamundos.v{N}+json` (asumiendo `v1` si se omite) y mantiene
   ambas representaciones activas durante una ventana mínima de **`90 días`**, emitiendo en cada
   respuesta antigua las cabeceras estándar `Deprecation` y `Sunset` (RFC 8594) mientras se monitorea
   en OpenTelemetry que el tráfico de la versión saliente baje de `< 0,1 %`.
3. **Contratos de eventos (`AsyncAPI`).** Todos los eventos conservan un **único tópico lógico** para
   no romper la serialización por clave `usuario_id` ([ADR-0018](ADR-0018-consistencia-datos-multirregion.md))
   e incluyen en su sobre el campo obligatorio `versionEsquema` (`"MAJOR.MINOR"`, ej. `"1.1"`). Un
   cambio `MINOR` agrega campos opcionales; un cambio `MAJOR` excepcional se introduce mediante doble
   emisión (o transformación *upcaster* en el consumidor) durante al menos **`14 días`**, superando
   con holgura los `7 días` de retención durable del *broker* ([ADR-0020](ADR-0020-contrapresion-y-sobrecarga.md)).
4. **Contratos de complementos (`AdaptadorDeProveedor`, `Extractor`) y descriptores `TipoDeSegmento`.**
   Cada complemento declara en su manifiesto el rango `SemVer` del contrato anfitrión (`apiContrato:
   "1.x"`), verificado por el cargador de `provider-sync` y `booking-extraction` en el arranque. Los
   descriptores `TipoDeSegmento` llevan un entero `version` (`tren v1`, `tren v2`): los segmentos ya
   persistidos conservan la tupla `(tipo, version)` con la que fueron validados, garantizando que el
   `100 %` del historial siga siendo legible (`QA-15`).

### Consecuencias

* **Bueno,** porque desacopla por completo el calendario de despliegue de los 13 servicios y de la
  aplicación móvil sin obligar a renombrar rutas ni fragmentar claves `ETag` en la caché regional.
* **Bueno,** porque mantiene el orden causal de eventos por `usuario_id` en un único tópico incluso
  durante evoluciones de esquema.
* **Malo,** porque ante una ruptura mayor obliga a sostener temporalmente dos mapeos de representación
  (`v{N}` y `v{N+1}`) hasta que venza la ventana `Sunset` de `90 días` (`14 días` en el *broker*).

### Confirmación

* **Puerta automática en CI:** ejecución obligatoria de detector de rupturas `OpenAPI` y validador de
  compatibilidad `BACKWARD_TRANSITIVE` sobre los esquemas `AsyncAPI`; cualquier eliminación de campo,
  cambio de tipo o nuevo campo requerido sin incremento `MAJOR` rechaza la fusión del cambio.
* **Pruebas de contrato guiadas por el consumidor (*CDC*) y suite de complementos (`D17`):** cada
  servicio consumidor verifica sus expectativas contra el contrato del productor, y el cargador de
  complementos rechaza en prueba automatizada un adaptador con `apiContrato` incompatible sin afectar
  al resto de los adaptadores activos.

## Pros y contras de las opciones

### A1 — Versionado sistemático en la ruta URL y tópicos separados por versión

* Bueno, porque hace visible la versión en cada dirección invocada.
* **Malo, porque duplica rutas y cachés ante evoluciones menores, contradice los contratos definidos
  en las iteraciones 2 y 3, y partir un tópico en el *broker* destruye el ordenamiento por usuario.**

### A2 — Prohibición perpetua de cualquier cambio incompatible

* Bueno, porque evita gestionar ventanas de retiro.
* **Malo, porque acumula deuda semántica indefinida e impide corregir errores de dominio o adaptarse a
  exigencias regulatorias futuras.**

### A3 — Despliegue sincronizado de productores y consumidores

* Bueno, porque evita mantener compatibilidad entre versiones.
* **Malo, porque destruye la desplegabilidad independiente (`ADR-0022`) y es inviable frente a
  clientes móviles ya instalados.**

### A4 — Evolución compatible por omisión + cabecera de medio en rupturas + `versionEsquema` + `SemVer`

* Bueno, porque resuelve el `95 %` de la evolución de forma aditiva sin fricción y provee un protocolo
  seguro y medible para el `5 %` restante.
* Malo, porque requiere disciplina de lectores tolerantes verificada en CI.

## Más información

* Análisis comparativo: [iteración 4, paso 4, D27](../02-proceso-add/iteracion-4/paso-4-alternativas.md#d27--versionado-y-evolución-de-los-contratos-publicados-crn-14-qa-10-qa-15)
* Vista afectada: [vista-modulos-adaptadores](../04-vistas/vista-modulos-adaptadores.md)
* Guías verificadas con este contrato: [guias-de-extension.md](../02-proceso-add/iteracion-4/guias-de-extension.md)
* Relacionados: [ADR-0006](ADR-0006-capa-de-anticorrupcion.md), [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md)
