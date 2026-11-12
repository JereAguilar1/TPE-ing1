# Prototipo de Trotamundos (2da entrega)

Implementación prototipo que demuestra la viabilidad de la arquitectura documentada en
[`docs/`](../docs/Home.md). El código se construye contra los contratos de
[`contratos/`](../contratos/README.md) y cada parte remite al ADR que implementa.

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

## Estructura

```
prototipo/
├── trotamundos/
│   ├── comun/                  # lo único compartido (equivale a modelo-canonico + contratos)
│   │   ├── config.py           # configuración por entorno
│   │   ├── contratos.py        # validación en ejecución contra contratos/   (ADR-0009, ADR-0017)
│   │   ├── eventos.py          # sobre, carga y representación en el broker  (AsyncAPI, ADR-0014)
│   │   ├── errores.py          # application/problem+json                    (comun.yaml)
│   │   ├── modelo.py           # modelo-canonico: ObservacionCanonica, Lugar, Extremo (ADR-0010)
│   │   └── tipos_de_segmento.py # registro de descriptores de tipo           (ADR-0011, ADR-0027)
│   └── servicios/              # un subpaquete por servicio; ninguno importa a otro (ADR-0036)
│       └── itinerary/          # un módulo por cada módulo de la vista N2
│           ├── reservas.py     # agregado Reserva: observaciones, fijados, estados  (ADR-0010)
│           └── fusion/
│               ├── consolidacion.py # precedencia por fuente, fijados y conflictos (ADR-0013)
│               └── identidad.py     # identificadores múltiples, unificación, sugerencias
├── tests/
├── docker-compose.yml      # PostgreSQL + broker
└── Makefile
```

### Reglas verificadas por las pruebas

`tests/test_arquitectura.py` comprueba en cada corrida las reglas de las vistas de módulos:

| Regla | Origen |
|---|---|
| Ningún servicio importa a otro; solo comparten `trotamundos.comun` | ADR-0036, ADR-0001 |
| `comun/modelo.py` solo usa la biblioteca estándar | R7, vista de módulos N1 |
| Ningún módulo menciona un tipo de segmento concreto (`vuelo`, `tren`…). Solo pueden hacerlo los complementos (adaptadores y extractores), que van en carpetas `complementos/` | I4, vista de módulos N2; ADR-0011 |
| Dentro de `itinerary`, cada módulo importa solo los módulos que la vista N2 le permite (`reservas` no conoce a `fusion` ni a `viajes`; `proyeccion_panel` y `publicacion` no importan dominio). Un módulo que no está en la vista hace fallar la prueba | I1, I3, I5, vista de módulos N2 |

### Decisiones de implementación

Decisiones menores que los documentos de arquitectura no fijan explícitamente. Ninguna contradice
un ADR; si alguna llegara a afectar a un driver, se promueve a un ADR propio.

| Decisión | Por qué | Respaldo en la documentación |
|---|---|---|
| El registro de tipos de segmento vive en `comun/tipos_de_segmento.py`, no dentro de `itinerary` | Lo usan `itinerary` y también los extractores y adaptadores para validar su salida (QA-10, QA-11); como un servicio no puede importar a otro (ADR-0036), tiene que estar en lo compartido | La vista de módulos de adaptadores muestra los descriptores como «artefacto común transversal» usado por `booking-extraction`. La vista N2 lo ubica en `itinerary`: en el prototipo ese módulo es la exposición de `GET /tipos-de-segmento` |
| `CuentaSuprimida` se particiona por `seudonimoAnalitico` | El contrato prohíbe `usuarioId` en ese evento (ADR-0030); el seudónimo es el único identificador que trae, y mantiene en orden los eventos de supresión de una misma cuenta | Contrato AsyncAPI, `SobreSinUsuario` y carga de `CuentaSuprimida` |
| Los adaptadores y extractores van en carpetas `complementos/`, y son lo único que puede nombrar un tipo de segmento concreto | Traducen un formato externo a un tipo, así que necesitan conocerlo; el resto del código razona por descriptor (regla I4) | Vista de módulos N2 (regla I4) y vista de adaptadores (complementos aislados, reglas R2 y R3) |
| Los eventos y las respuestas se validan en el mismo proceso contra los archivos de `contratos/`, sin un registro de esquemas | Da la misma garantía (nada sale del servicio sin cumplir el contrato) sin agregar otro servidor a la infraestructura local. La compatibilidad entre versiones se comprueba con pruebas (paso 16) | La iteración 4 prevé un registro de esquemas AsyncAPI con compatibilidad `BACKWARD_TRANSITIVE` (ADR-0027); el prototipo lo reemplaza, no lo contradice |
| El campo `type` de los errores es `https://errores.trotamundos.app/{status}` | RFC 9457 pide una URI que identifique el tipo de problema; una por código de estado alcanza para el prototipo | `comun.yaml`, esquema `Problema` (`type` con `format: uri`) |
| Por cada clave `(fuente, idDeFuente)` la reserva guarda una sola observación: la de mayor `versionDeFuente` (ante un empate, decide el contenido). Repetirla o recibir una versión vieja no cambia nada | ADR-0014 identifica la observación por esa clave y la ordena por la versión de la fuente; así se cubren el duplicado de entrega y la reversión de estado | Iteración 2 §5.8: `observacion` única por `(reserva_id, fuente, id_de_fuente)` |
| De cada fuente cuenta solo su observación vigente (la de mayor `versionDeFuente`). Entre fuentes, la fusión es campo a campo: proveedor, correo y manual. El alta manual no fija campos: solo la edición los fija | Es la tabla de ADR-0013: gana la mayor versión de la fuente, el proveedor gana en los hechos operativos, el correo completa lo que el proveedor no informa y el usuario es la autoridad si la reserva es solo manual o si fijó el campo. Como la compactación conserva solo la vigente por fuente, compactar no cambia la vista (lo comprueba una prueba de propiedades) | ADR-0012 y ADR-0023 (compactación); `EdicionReserva` dice «cada campo tocado queda fijado» y `ReservaNueva` no |
| Los segmentos se alinean por posición. Una observación aporta valores a un segmento solo si tiene la misma cantidad de segmentos y el mismo tipo y versión del tipo en esa posición | Evita mezclar tramos (un vuelo con escala informado como uno o como dos) y detalles de versiones distintas del tipo | `ConflictoDeFuentes.campo` usa rutas por posición (`segmentos[0].inicio.instante`) |
| Un conflicto se abre si una observación automática **posterior al fijado** (por `versionDeFuente`) trae otro valor. Resolverlo es fijar de nuevo: el mismo valor (`mantenerFijado`) o el de la fuente elegida (`aceptarFuente`) | «Después» se mide con la versión de la fuente, no con la llegada, para que el resultado no dependa del orden (ADR-0010). Elegir un valor es una edición del usuario, y la edición fija | ADR-0013, filas «Edición manual» y «Cancelación del proveedor»; `resolverConflicto` en `itinerary.yaml` |
| Los ids de los segmentos y de los conflictos se derivan del id de la reserva (UUID v5) | Las mismas entradas dan la misma vista, ids incluidos | `Segmento.id` y `ConflictoDeFuentes.id` son `uuid` en `comun.yaml` |
| Si una observación liga dos reservas y alguna es manual, la observación va a la más antigua, la otra vuelve como `posiblesDuplicados` y sus identificadores no se copian | ADR-0013 pide confirmación del usuario, pero no dice dónde queda la observación mientras tanto. Así no se pierde y cada identificador sigue siendo de una sola reserva | Iteración 2 §5.8: `reserva_identificador` único por `(usuario_id, emisor, codigo)` |
| La sugerencia por parecido compara tipo, fecha local de inicio y lugar de inicio (código o, si no hay, nombre), entre reservas sin identificadores en común | Es el criterio mínimo que distingue la prueba negativa de ADR-0013 (dos habitaciones iguales la misma noche) y nunca fusiona: solo sugiere | ADR-0013 (M2 solo como sugerencia) |
| Las pruebas basadas en propiedades usan Hypothesis directamente (dependencia solo de desarrollo) | ADR-0017 y ADR-0010 las piden para comprobar que la fusión es determinista e idempotente. Hypothesis es el motor de Schemathesis, así que no suma una tecnología nueva; la versión fijada es compatible con la que pide Schemathesis | ADR-0036 elige `pytest` y Schemathesis para las pruebas |
| Una observación del proveedor, una manual o un correo de banda alta confirman la reserva. Una vez confirmada, los correos de banda media se guardan (y aportan identificadores) pero no cambian valores. Mientras está `PorConfirmar`, una cancelación no la lleva a `Cancelada`; `ReservaCancelada` se decide por el cambio de estado, no por la vista | Ningún dato dudoso entra como confirmado. La máquina de estados va de `PorConfirmar` a `Confirmada` y de ahí a `Cancelada`; la banda media no entra al itinerario confirmado ni dispara avisos críticos. Se decidió al revisar el paso 3: los documentos no cubren este caso | Iteración 2 §5.2 (estados de la reserva); ADR-0015 |
| Un extremo con `precision: dia` lleva como instante la medianoche UTC de la fecha del boleto | El contrato no fija cómo se escribe «ese día» en un `date-time`; así la fecha se lee igual en cualquier zona horaria. Es la convención que ya usan las pruebas del paso 2 | ADR-0011 (boletos abiertos); `Extremo` en `comun.yaml` |

## Cómo correrlo

Requisitos: Python 3.12, Docker con Compose.

```bash
cd prototipo
make instalar        # crea .venv e instala dependencias
make pruebas         # corre las pruebas
make infra-arriba    # levanta PostgreSQL (puerto 55432) y el broker (puerto 19092)
make infra-abajo
```

Variables de entorno opcionales: `TROTAMUNDOS_CONTRATOS`, `TROTAMUNDOS_DSN`, `TROTAMUNDOS_BROKER`,
`TROTAMUNDOS_REGION`.

## Plan de construcción

Cada paso se entrega en uno o más commits chicos. La columna «Trazabilidad» indica qué decisiones
implementa.

| # | Paso | Trazabilidad | Estado |
|---|---|---|---|
| 1 | Base: tecnología, infraestructura, validación contra `contratos/` | ADR-0009, ADR-0036 | ✅ |
| 2 | Registro de tipos de segmento y modelos canónicos | ADR-0010, ADR-0011 | ✅ |
| 3 | `itinerary`: agregado `Reserva` y fusión determinista | ADR-0010, ADR-0013 | ✅ |
| 4 | `itinerary`: persistencia, *outbox*, *inbox* y API interna | ADR-0012, ADR-0014 | ⬜ |
| 5 | `itinerary`: viajes, agrupación, ciclo de vida y proyección del panel | RF-07, RF-08 | ⬜ |
| 6 | *Broker*: publicador de la *outbox*, consumidores y carriles | ADR-0014, ADR-0020 | ⬜ |
| 7 | `identity-access`: sesiones, buzones, bóveda con cifrado por sobres, auditoría | QA-13, ADR-0029 | ⬜ |
| 8 | `mail-ingest`: webhooks, filtros, normalización, deduplicación | RF-02, RF-04 | ⬜ |
| 9 | `booking-extraction`: extractores, bandas de confianza, formato desconocido | QA-11, ADR-0015 | ⬜ |
| 10 | `provider-sync`: adaptador simulado, cortacircuitos, disrupciones | QA-10, ADR-0024 | ⬜ |
| 11 | BFF y `api-gateway`: panel, límite de tasa, plazos | QA-02, ADR-0020 | ⬜ |
| 12 | `notification` y `support-liaison` | UC-5, UC-7 | ⬜ |
| 13 | `sharing`: compartición y `ResumenPublicable` | QA-12, ADR-0028 | ⬜ |
| 14 | `event-pipeline` y plano analítico | QA-09, ADR-0016 | ⬜ |
| 15 | Tipo `tren` sin tocar código de dominio | QA-15 | ⬜ |
| 16 | Pruebas de contrato y de escenarios (QA-01, QA-04, QA-05) | ADR-0017 | ⬜ |
| 17 | Iteración 5 de ADD: diseño de la Opción B (ADRs y contrato) | CON-06 | ⬜ |
| 18 | `virtual-assistant`: intenciones y derivación a la agencia | RF-B1, RF-B2 | ⬜ |
| 19 | Interfaz web mínima de demostración | RF-09 | ⬜ |
| 20 | Matriz código ↔ ADR, guion de demostración y README final | QA-16 | ⬜ |
