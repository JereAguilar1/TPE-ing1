# Prototipo de Trotamundos (2da entrega)

Implementación prototipo que demuestra la viabilidad de la arquitectura documentada en
[`docs/`](../docs/Home.md). El código se construye contra los contratos de
[`contratos/`](../contratos/README.md) y cada parte remite al ADR que implementa.

## Documentación del prototipo

Este archivo es la portada: qué se construyó, cómo correrlo y el plan. Lo demás, para consultar:

| Documento | Contenido |
|---|---|
| [Estado de las decisiones de arquitectura](docs/estado-de-los-adr.md) | Qué parte de cada ADR está en código (✅ / 🟨 / ➖) y qué falta |
| [Matriz código ↔ ADR](docs/matriz-codigo-adr.md) | Qué código implementa cada decisión y qué prueba lo verifica (QA-16) |
| [Diseñado y no construido](docs/disenado-y-no-construido.md) | Lo que queda solo en el diseño, dónde está diseñado y por qué no se construye |
| [Decisiones de implementación](docs/decisiones-de-implementacion.md) | Lo que los ADR no fijaban y se decidió al construir |
| [Estructura del código](docs/estructura.md) | Qué hay en cada carpeta y las reglas de arquitectura que verifican las pruebas |
| [Guion de demostración](demo/guion.md) | El recorrido de la defensa y los comandos de apoyo |

## Qué se construye y qué no

El alcance lo fija [ADR-0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) (CON-05):
una **tajada vertical** que demuestra las decisiones más riesgosas, no el sistema completo.

| Se construye | Para demostrar |
|---|---|
| Los caminos de los 5 ASRs | QA-01 (frescura ≤ 5 min), QA-04 (pico de disrupción), QA-05 (pérdida de región), QA-11 (formato de correo desconocido), QA-13 (custodia de credenciales) |
| Un adaptador de proveedor y un extractor de correo de ejemplo | QA-10 (proveedor nuevo sin tocar código) y QA-15 (tipo `tren` sin tocar el dominio) |
| El plano analítico separado | QA-09 (la analítica no afecta la operación) |
| El módulo avanzado **Opción B — asistente virtual** | RF-B1, RF-B2 (CON-06) |

Los terceros (proveedores de correo, aerolíneas, agencias, redes) se reemplazan por **simuladores**
que cumplen los mismos contratos. Las cifras de producción (por ejemplo, 9.000 req/s) no se buscan:
se demuestran los **mecanismos** que las sostienen.

## Tecnología

Decidida en [ADR-0036](../docs/03-adr/ADR-0036-tecnologia-del-prototipo.md): Python 3.12 + FastAPI,
PostgreSQL 16, Redpanda (API de Kafka) y Docker Compose.

## Cómo correrlo

Requisitos: Python 3.12, Docker con Compose.

```bash
cd prototipo
make instalar        # crea .venv e instala dependencias
make infra-arriba    # levanta PostgreSQL (puerto 55432; la región EU, 55433) y el broker (19092)
make pruebas         # corre las pruebas (las de PostgreSQL se saltean si no está arriba)
make servicios-arriba # además construye la imagen y levanta los servicios;
                      # la interfaz web queda en http://localhost:18111
.venv/bin/python demo/cargar_viajes.py ana@ejemplo.com  # viajes de ejemplo para ese correo
bash demo/demo.sh     # el recorrido completo de la demostración, por terminal
                      # con los servicios arriba, make pruebas también recorre los escenarios
                      # contra los contenedores (tests/escenarios: QA-01, QA-04, QA-05, QA-15 y
                      # otros) y la interfaz web; sin ellos, se saltean
make infra-abajo
```

**Integración continua.** En cada cambio de `prototipo/` o `contratos/`,
[`.github/workflows/pruebas.yml`](../.github/workflows/pruebas.yml) levanta PostgreSQL y Redpanda
con el mismo `docker-compose.yml` y corre todas las pruebas. Ahí se define
`TROTAMUNDOS_EXIGIR_INFRA=1`: sin base o sin broker, las pruebas fallan en lugar de saltearse. En
paralelo, el trabajo `servicios` construye la imagen y levanta todo el compose (`make
servicios-arriba`): si algún servicio no arranca, falla aunque sus pruebas estén en verde, y muestra
los registros de los contenedores. Con los contenedores sanos, corre los escenarios de
`tests/escenarios` que los usan y las pruebas de `tests/app_web` con `TROTAMUNDOS_EXIGIR_CONTENEDORES=1`: si un
contenedor no está, fallan en lugar de saltearse. El de QA-05 va último porque tira la región AM y la
vuelve a levantar.

**Contraseña de la base local.** No está en el código: `make infra-arriba` la genera al azar la
primera vez y la guarda en `prototipo/.env`, que git ignora. Docker Compose y las pruebas la leen
de ahí. El puerto de PostgreSQL solo escucha en `127.0.0.1`. Si tenías la base creada con una
versión anterior del compose, recreala una vez: `docker compose down -v && make infra-arriba`.

**Dependencias.** `pyproject.toml` declara las directas; `requirements.txt` es el archivo de bloqueo
con todas, incluidas las transitivas, con versión exacta y los *hashes* de sus archivos. Es lo que
instala la imagen (`--require-hashes`). Si cambia una versión en `pyproject.toml`, hay que
regenerarlo; `tests/test_dependencias.py` avisa si no coinciden:

```bash
python3.12 -m venv /tmp/bloqueo && /tmp/bloqueo/bin/pip install pip-tools==7.4.1
.venv/bin/python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.in
/tmp/bloqueo/bin/pip-compile --generate-hashes --strip-extras --no-header -o /tmp/requirements.txt /tmp/requirements.in
# reemplazar todo menos el encabezado de requirements.txt por /tmp/requirements.txt
```

Servicios que levanta `make servicios-arriba`:

| Servicio | Puerto local | Contrato |
|---|---|---|
| `itinerary-escritura` | 18101 | Los comandos de [`openapi/itinerary.yaml`](../contratos/openapi/itinerary.yaml) (etiqueta `comando`). Además corre el trabajo periódico, publica su *outbox* y consume `ReservaExtraida` y `ReservaObservada` del broker |
| `itinerary-lectura` | 18102 | Las lecturas del mismo contrato (etiqueta `lectura`): panel, viajes, reservas y tipos de segmento |
| `identity-access` | 18103 | Sesiones OIDC/OTP, buzones, bóveda (`KEK_region`/`DEK_u`), vales ABAC, auditoría encadenada y privacidad ([`openapi/identity-access.yaml`](../contratos/openapi/identity-access.yaml)). Publica `EstadoDeBuzonCambiado` y `CuentaSuprimida` |
| `mail-ingest` | 18104 | Avisos de los proveedores (`/webhooks/correo`), reenvío verificado (`/webhooks/correo/reenvio`) y filtros del usuario ([`mail-ingest-webhooks.yaml`](../contratos/openapi/mail-ingest-webhooks.yaml), [`mail-ingest-filtros.yaml`](../contratos/openapi/mail-ingest-filtros.yaml)). Consume `EstadoDeBuzonCambiado`, pide los tokens a `identity-access` y publica `MensajeDeViajeRecibido` |
| `support-liaison` | 18105 | Casos de soporte derivados a la agencia preferida ([`support-liaison.yaml`](../contratos/openapi/support-liaison.yaml)). Toma la instantánea del viaje de `itinerary-lectura`, consume `PreferenciasActualizadas` y publica `CasoDerivado` |
| `virtual-assistant` | 18106 | Asistente virtual de la Opción B ([`virtual-assistant.yaml`](../contratos/openapi/virtual-assistant.yaml)). Lee de `itinerary-lectura`, corrige en `itinerary-escritura` y deriva en `support-liaison`, siempre con la sesión del viajero; consume `DisrupcionDetectada` |
| `booking-extraction` | 18107 | Consume `MensajeDeViajeRecibido`, ejecuta los extractores de correo y publica `ReservaExtraida` o `ExtraccionNoReconocida` ([`plugins/extractor.yaml`](../contratos/plugins/extractor.yaml)). Sin operaciones HTTP de negocio; el puerto sirve para el *healthcheck* |
| `bff-web` | 18108 | Operaciones públicas para `app-web` ([`bff-web.yaml`](../contratos/openapi/bff-web.yaml)): panel y viajes con `ETag`/`304` y `Cache-Control`, comandos con `X-Version-Usuario`, catálogo público de tipos y conversaciones con `virtual-assistant` |
| `provider-sync` | 18109 | Webhooks de proveedores de viaje (`/webhooks/proveedor` de [`provider-sync-webhooks.yaml`](../contratos/openapi/provider-sync-webhooks.yaml)) y sondeo periódico por adaptadores cargados como complementos ([`plugins/adaptador.yaml`](../contratos/plugins/adaptador.yaml)). Consume `ReservaActualizada` y `ReservaCancelada` para el seguimiento y publica `ReservaObservada` y `DisrupcionDetectada` |
| `event-pipeline` | 18110 | Consumidor de eventos de dominio hacia el esquema analítico separado `analytics_store` ([`analitica/modelo-dimensional.sql`](../contratos/analitica/modelo-dimensional.sql), ADR-0003, ADR-0016, ADR-0030). Retiene eventos crudos con seudónimo y materializa dimensiones, hechos y `lista_supresion_analitica` |
| `app-web` | 18111 | Interfaz web (paso 20, RF-09): el panel y el chat del asistente, el detalle de cada viaje (archivar, eliminar, conflictos), los viajes anteriores, confirmar o descartar lo dudoso y la carga manual. nginx sirve la página y enruta `/api/bff` a `api-gateway` (que la manda al `bff-web` de la región del viajero) y el inicio de sesión a `identity-access`, desde el mismo origen. Abrir [http://localhost:18111](http://localhost:18111) |
| `preferences` | 18112 | Preferencias del viajero ([`preferences.yaml`](../contratos/openapi/preferences.yaml)). Publica `PreferenciasActualizadas` y recibe la orden de borrado de la fase 1 |
| `notification` | 18113 | Avisos al viajero (RF-10): consume los eventos de cambios, disrupciones, buzones y casos, guarda el canal interno, entrega por push y correo simulados y publica `NotificacionEmitida`. Sin operaciones HTTP |
| `api-gateway` | 18114 | La API pública ([`api-gateway.yaml`](../contratos/openapi/api-gateway.yaml)): sesión, cubeta de fichas por usuario, `X-Deadline-Ms` y `X-Modo-Operativo` según el modo, `traceparent` y versión `v1`. Elige `bff-web` o `bff-mobile` con `X-Tipo-Cliente` y, con la multirregión (paso 16), el `bff-web` de la región del usuario: comprueba la salud de cada región y, si cae la primaria, lo manda a la de respaldo |
| `bff-mobile` | 18115 | Operaciones para `app-movil` ([`bff-mobile.yaml`](../contratos/openapi/bff-mobile.yaml)): las de itinerario de `bff-web` y `GET /panel/resumen` (≤ 15 KB) |
| `itinerary-escritura-eu`, `itinerary-lectura-eu` | 18121, 18122 | Región EU de la multirregión simulada (paso 16): el mismo `itinerary`, sobre `postgres-eu` (puerto 55433) y sin *broker*. Reproduce el testigo de los usuarios de AM si AM cae |
| `bff-web-eu` | 18128 | `bff-web` de la región EU, sobre el `itinerary` de EU. `api-gateway` le manda los usuarios de EU y, si AM cae, también los de AM |
| `sharing` | 18116 | Compartir un viaje con designados y publicar su resumen ([`sharing.yaml`](../contratos/openapi/sharing.yaml)). Pide la decisión ABAC a `identity-access` y verifica el vale; `identity-access` le pregunta los atributos de cada compartición |

Variables de entorno opcionales: `TROTAMUNDOS_CONTRATOS`, `TROTAMUNDOS_DSN`, `TROTAMUNDOS_BROKER`,
`TROTAMUNDOS_REGION`, `TROTAMUNDOS_INTERVALO_TAREAS` (segundos entre corridas del trabajo
periódico; 0 lo apaga) y `TROTAMUNDOS_PREFIJO_TOPICOS` (antepuesto a los tópicos; las pruebas lo
usan para no mezclarse). Con `TROTAMUNDOS_BROKER` vacío, un servicio no publica ni consume.
`mail-ingest` usa además `TROTAMUNDOS_URL_IDENTITY_ACCESS` (por omisión, `http://localhost:18103`), y
`support-liaison`, `TROTAMUNDOS_URL_ITINERARY_LECTURA` (por omisión, `http://localhost:18102`).
`virtual-assistant` usa esa misma, `TROTAMUNDOS_URL_ITINERARY_ESCRITURA` (`http://localhost:18101`) y
`TROTAMUNDOS_URL_SUPPORT_LIAISON` (`http://localhost:18105`). `bff-web` usa las dos de `itinerary` y
`TROTAMUNDOS_URL_VIRTUAL_ASSISTANT` (`http://localhost:18106`).
`TROTAMUNDOS_MODO` elige el modo de despliegue de `itinerary`: `completo` (por omisión), `lectura` o
`escritura`. Multirregión (paso 16): con `TROTAMUNDOS_DSN_TESTIGO` (la base de la región de
respaldo), `itinerary` registra ahí sus comandos manuales y reproduce los de su propio esquema
`testigo`; `api-gateway` conmuta entre los `bff-web` de `TROTAMUNDOS_URL_BFF_WEB_<REGIÓN>` (`AM`, `EU`
o `AP`). Sin esas variables, todo funciona en una sola región.

### Prueba de humo del correo (paso 9)

Desde `prototipo/`, con la infraestructura arriba:

```sh
TROTAMUNDOS_EXIGIR_INFRA=1 make pruebas
make servicios-arriba
.venv/bin/python -m tests.booking_extraction.humo_contenedores
```

El humo atraviesa el receptor de reenvío de `mail-ingest`, Redpanda, `booking-extraction` y
el panel de `itinerary`: alta confirmada, media por confirmar, baja y desconocida sin reservas,
y repetición sin duplicados. Crea un usuario y un buzón sintéticos únicos (imprime su UUID),
sin alterar datos existentes. El tiempo observado es evidencia local de QA-01, no una medición
p99 de producción ni el escenario de carga del paso 17. El corpus de 20 correos es sintético:
no demuestra cobertura sobre los veinte remitentes reales más frecuentes.

Después del humo se bajan solo los servicios, preservando base, broker y esquemas:

```sh
docker compose rm -sf $(docker compose config --services | grep -vx "postgres\|postgres-eu\|broker")
```

## Plan de construcción

Cada paso se entrega en uno o más commits chicos. La columna «Trazabilidad» indica qué decisiones
implementa. La columna «Prioridad» ordena lo que falta según el recorte acordado por el grupo
(ver [abajo](#recorte-para-la-entrega)). El reparto se acuerda en el grupo y se anota todo junto en
«Responsable»: un paso con responsable no lo empieza otro.

| # | Paso | Trazabilidad | Prioridad | Estado | Responsable |
|---|---|---|---|---|---|
| 1 | Base: tecnología, infraestructura, validación contra `contratos/` | ADR-0009, ADR-0036 | — | ✅ | Francisco Lozano |
| 2 | Registro de tipos de segmento y modelos canónicos | ADR-0010, ADR-0011 | — | ✅ | Francisco Lozano |
| 3 | `itinerary`: agregado `Reserva` y fusión determinista | ADR-0010, ADR-0013 | — | ✅ | Francisco Lozano |
| 4 | `itinerary`: persistencia, *outbox*, *inbox* y API interna | ADR-0012, ADR-0014 | — | ✅ | Francisco Lozano |
| 5 | `itinerary`: viajes, agrupación, ciclo de vida y proyección del panel | RF-07, RF-08 | — | ✅ | Francisco Lozano |
| 6 | *Broker*: publicador de la *outbox*, consumidores y carriles | ADR-0014, ADR-0020 | — | ✅ | Francisco Lozano |
| 7 | `identity-access`: sesiones, buzones, bóveda con cifrado por sobres, auditoría | QA-13, ADR-0029 | — | ✅ | Jeremias Aguilar |
| 8 | `mail-ingest`: webhooks, filtros, normalización, deduplicación | RF-02, RF-04 | — | ✅ | Francisco Lozano |
| 9 | `booking-extraction`: extractores, bandas de confianza, formato desconocido | QA-11, ADR-0015 | Sí o sí | ✅ completo: el recorte, más los extractores de boletos de tren y de reservas de hotel | Juan Pardo (recorte), Francisco Lozano (completo) |
| 10 | `provider-sync`: adaptador simulado, cortacircuitos, disrupciones | QA-10, ADR-0024 | Si sobra (reducido) | ✅ completo: el reducido, más la protección de ADR-0024 y el adaptador ferroviario | Ivo Iriarte (reducido), Francisco Lozano (completo) |
| 11 | BFF y `api-gateway`: panel, límite de tasa, plazos | QA-02, ADR-0020 | Debería (reducido) | ✅ completo: `bff-web` (reducido), más `bff-mobile`, `api-gateway`, plazo propagado, modos operativos y la degradación del asistente | Ivo Iriarte (reducido), Francisco Lozano (completo) |
| 12 | `notification`, `support-liaison` y `preferences` mínimo | UC-5, UC-7, ADR-0034 | Sí o sí (reducido) | ✅ completo: `support-liaison` (reducido), más `preferences` y `notification` | Francisco Lozano |
| 13 | `sharing`: compartición y `ResumenPublicable` | QA-12, ADR-0028 | Completar al 100 % | ✅ | Francisco Lozano |
| 14 | `event-pipeline` y plano analítico | QA-09, ADR-0016 | Si sobra (reducido) | ✅ completo: el reducido, más SCD tipo 2, compactación de fase 2 y fase 1 coordinada | Ivo Iriarte (reducido), Francisco Lozano (completo) |
| 15 | Tipo `tren` sin tocar código de dominio | QA-15 | Debería | ✅ | Francisco Lozano |
| 16 | Multirregión simulada: región primaria por usuario, testigo transregional y conmutación | QA-05, ADR-0018 | Completar al 100 % | ✅ versión mínima: dos regiones (AM y EU), testigo de los comandos manuales, conmutación en `api-gateway` y el escenario de QA-05 contra los contenedores | Francisco Lozano |
| 17 | Pruebas de contrato y de escenarios (QA-01, QA-04, QA-05) | ADR-0017 | Debería (reducido) | ✅ completo: escenarios de QA-01 y QA-04 contra los contenedores, más pruebas de contrato con Schemathesis de once contratos. El escenario de QA-05 se construyó con el paso 16 | Francisco Lozano |
| 18 | Iteración 5 de ADD: diseño de la Opción B (ADRs y contrato) | CON-06 | Sí o sí | ✅ | Francisco Lozano |
| 19 | `virtual-assistant`: intenciones y derivación a la agencia | RF-B1, RF-B2 | Sí o sí | ✅ | Francisco Lozano |
| 20 | Interfaz web mínima de demostración | RF-09 | Debería (reducido) | ✅ completo: el panel y el chat, más el detalle del viaje, los viajes anteriores, confirmar o descartar, resolver conflictos y la carga manual | Francisco Lozano |
| 21 | Matriz código ↔ ADR, guion de demostración y README final | QA-16 | Sí o sí | ✅ matriz verificada contra el código (cada ruta existe; todo módulo y toda prueba aparecen), README y wiki al día, guion con los cinco ASR y comandos de apoyo en `demo/apoyo.py`. Quedan el reparto de la presentación y el ensayo, del grupo | Francisco Lozano |

Los 21 pasos están hechos, incluidos el 13 y el 16, que el recorte había dejado afuera y se construyeron después. Lo que quedó afuera está en [Diseñado y no construido](docs/disenado-y-no-construido.md).

### Recorte para la entrega

Quedan menos de siete días y 13 pasos. El enunciado pide «una rigurosa gestión del tiempo» y
acotar el alcance del prototipo (§2), y [ADR-0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md)
ya fijó el criterio: una tajada vertical que demuestre los ASR (QA-01, QA-04, QA-05, QA-11, QA-13),
un adaptador o extractor de ejemplo (QA-10, QA-15), el aislamiento analítico (QA-09) y el módulo
avanzado. Por eso el grupo construye primero esa tajada, en este orden:

| Prioridad | Pasos | Qué entra |
|---|---|---|
| **Sí o sí** | 9, 12, 18, 19, 21 | `booking-extraction` con un extractor y las bandas de confianza (QA-11, cierra QA-01). Del paso 12, solo `support-liaison` con `POST /casos`, que usa la derivación de la Opción B. La iteración 5 de ADD y `virtual-assistant` (CON-06). El cierre: matriz código ↔ ADR, guion de demostración y README final |
| **Debería** | 11, 15, 17, 20 | Solo `bff-web` (el asistente se expone por el BFF, ADR-0034). El tipo `tren` sin tocar código de dominio (QA-15). Escenarios de QA-01 de punta a punta y de QA-04 con ráfaga (la prueba de humo con los contenedores ya está en la integración continua, adelantada el 17/11). Una página con el panel y el chat del asistente |
| **Si sobra** | 10, 14 | Un adaptador simulado que publica `ReservaObservada` y `DisrupcionDetectada` (QA-10). Un consumidor de eventos a un esquema analítico aparte, con una prueba de aislamiento (QA-09) |

**Fechas.** La entrega es el **lunes 23 de noviembre de 2026 a las 23:00**. El **congelamiento** es
el **lunes 23 a las 03:00**, 20 h antes de la entrega (se extendió desde el domingo 22 a las 23:00):
desde ahí no se empieza ningún paso nuevo, aunque sobren horas. El resto del lunes 23, hasta la
entrega, queda para el cierre (paso 21) y el ensayo de la defensa. Lo que al congelar no esté terminado se registra en [Diseñado y no construido](docs/disenado-y-no-construido.md).

La iteración 5 (paso 18) va primero: sin sus ADR y su contrato, el asistente (paso 19) no puede
empezar sin inventar decisiones.
