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
│   │   ├── carriles.py         # carriles P1/P2/P3 y tópicos del broker      (ADR-0020)
│   │   ├── config.py           # configuración por entorno
│   │   ├── consumidor.py       # consumo por carriles, con eventos rechazados (ADR-0014, ADR-0020)
│   │   ├── contratos.py        # validación en ejecución contra contratos/   (ADR-0009, ADR-0017)
│   │   ├── eventos.py          # sobre, carga y representación en el broker  (AsyncAPI, ADR-0014)
│   │   ├── errores.py          # application/problem+json                    (comun.yaml)
│   │   ├── modelo.py           # modelo-canonico: ObservacionCanonica, Lugar, Extremo (ADR-0010)
│   │   ├── persistencia.py     # PostgreSQL: outbox, bandeja de entrada, Idempotency-Key (ADR-0012, ADR-0014)
│   │   ├── publicador.py       # de la outbox al broker, al menos una vez     (ADR-0012)
│   │   └── tipos_de_segmento.py # registro de descriptores de tipo           (ADR-0011, ADR-0027)
│   └── servicios/              # un subpaquete por servicio; ninguno importa a otro (ADR-0036)
│       └── itinerary/          # un módulo por cada módulo de la vista N2, más servicio.py
│           ├── reservas/       # agregado Reserva (ADR-0010) y su repositorio PostgreSQL (ADR-0012)
│           ├── viajes/         # agregado Viaje: agrupación y ciclo de vida (RF-07, RF-08) y su repositorio
│           ├── fusion/
│           │   ├── consolidacion.py # precedencia por fuente, fijados y conflictos (ADR-0013)
│           │   ├── identidad.py     # identificadores múltiples, unificación, sugerencias
│           │   └── eventos.py       # ReservaActualizada, ReservaCancelada, ConflictoDeFuentesDetectado
│           ├── gestion_manual.py    # alta, edición, baja, confirmación y conflictos (RF-06)
│           ├── ingesta.py           # ReservaExtraida y ReservaObservada con bandeja de entrada (ADR-0014)
│           ├── publicacion.py       # outbox (ADR-0012)
│           ├── proyeccion_panel.py  # lecturas de reserva, viaje y panel, mantenidas por eventos internos
│           ├── api.py               # API interna (openapi/itinerary.yaml)
│           └── servicio.py          # arma los módulos y define las transacciones
├── tests/
├── Dockerfile              # una imagen para todos los servicios (se construye desde la raíz)
├── docker-compose.yml      # PostgreSQL, broker y servicios
└── Makefile
```

### Reglas verificadas por las pruebas

`tests/test_arquitectura.py` comprueba en cada corrida las reglas de las vistas de módulos:

| Regla | Origen |
|---|---|
| Ningún servicio importa a otro; solo comparten `trotamundos.comun` | ADR-0036, ADR-0001 |
| `comun/modelo.py` solo usa la biblioteca estándar | R7, vista de módulos N1 |
| Ningún módulo menciona un tipo de segmento concreto (`vuelo`, `tren`…). Solo pueden hacerlo los complementos (adaptadores y extractores), que van en carpetas `complementos/` | I4, vista de módulos N2; ADR-0011 |
| Dentro de `itinerary`, cada módulo importa solo los módulos que la vista N2 le permite (`reservas` no conoce a `fusion` ni a `viajes`; `ingesta` solo conoce a `fusion`; `api` solo a `gestion_manual` y `proyeccion_panel`; `proyeccion_panel` y `publicacion` no importan dominio). La excepción declarada es `servicio`, el punto de armado, que ningún módulo importa. Un módulo que no está en la tabla hace fallar la prueba | I1, I3, I5, vista de módulos N2 |

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
| Si una observación liga dos reservas y alguna es manual, o el usuario la descartó o dio de baja, no se unifican: la observación va a la más antigua que el usuario ve, las otras visibles vuelven como `posiblesDuplicados` y sus identificadores no se copian | ADR-0013 pide confirmación del usuario, pero no dice dónde queda la observación mientras tanto. Así no se pierde, cada identificador sigue siendo de una sola reserva y una reserva dada de baja no absorbe a una que el usuario ve | Iteración 2 §5.8: `reserva_identificador` único por `(usuario_id, emisor, codigo)` |
| La sugerencia por parecido compara tipo, fecha local de inicio y lugar de inicio (código o, si no hay, nombre), entre reservas sin identificadores en común | Es el criterio mínimo que distingue la prueba negativa de ADR-0013 (dos habitaciones iguales la misma noche) y nunca fusiona: solo sugiere | ADR-0013 (M2 solo como sugerencia) |
| Las pruebas basadas en propiedades usan Hypothesis directamente (dependencia solo de desarrollo) | ADR-0017 y ADR-0010 las piden para comprobar que la fusión es determinista e idempotente. Hypothesis es el motor de Schemathesis, así que no suma una tecnología nueva; la versión fijada es compatible con la que pide Schemathesis | ADR-0036 elige `pytest` y Schemathesis para las pruebas |
| Una observación del proveedor, una manual o un correo de banda alta confirman la reserva. Una vez confirmada, los correos de banda media se guardan (y aportan identificadores) pero no cambian valores. Mientras está `PorConfirmar`, una cancelación no la lleva a `Cancelada`; `ReservaCancelada` se decide por el cambio de estado, no por la vista | Ningún dato dudoso entra como confirmado. La máquina de estados va de `PorConfirmar` a `Confirmada` y de ahí a `Cancelada`; la banda media no entra al itinerario confirmado ni dispara avisos críticos. Se decidió al revisar el paso 3: los documentos no cubren este caso | Iteración 2 §5.2 (estados de la reserva); ADR-0015 |
| Un extremo con `precision: dia` lleva como instante la medianoche UTC de la fecha del boleto | El contrato no fija cómo se escribe «ese día» en un `date-time`; así la fecha se lee igual en cualquier zona horaria. Es la convención que ya usan las pruebas del paso 2 | ADR-0011 (boletos abiertos); `Extremo` en `comun.yaml` |
| Cada servicio tiene su propio esquema de PostgreSQL en la misma instancia. La *outbox*, la bandeja de entrada y las claves de idempotencia son tablas iguales en todos, que crea `comun/persistencia.py` dentro del esquema de cada servicio | Cada servicio es dueño de sus datos, y todo productor y todo consumidor necesita esas tablas. Una instancia alcanza para el prototipo | ADR-0001, ADR-0012, ADR-0014 |
| Las transacciones de un mismo usuario se serializan con un bloqueo consultivo de PostgreSQL por `usuario_id` | Es lo que da en producción la partición por usuario en su región primaria: la bandeja de entrada y la resolución de identidad suponen que nada más escribe a la vez para ese usuario | ADR-0018 (riesgo R-4) |
| `servicio.py` arma los módulos de `itinerary` y define cada transacción (cambio, *outbox*, lectura y `versionUsuario`, todo o nada). No es un módulo de la vista N2 | La vista N2 describe módulos que no se importan entre sí (I1, I3), pero ADR-0012 exige que el cambio y su evento se escriban juntos: alguien tiene que componerlos | Vista de módulos N2; ADR-0012 |
| Los «eventos internos» de la vista N2 son los mismos eventos de dominio que van a la *outbox*. `publicacion` y `proyeccion_panel` reaccionan a ellos dentro de la misma transacción | Así esos módulos no importan dominio (I3), y la lectura queda al día con la escritura (*read-your-writes*) | Vista de módulos N2 (flechas dobles); ADR-0018 |
| `GET /reservas/{id}` se sirve de `reserva_lectura`, que mantiene `proyeccion_panel`, y no de las tablas del agregado. Una reserva descartada, dada de baja o absorbida responde 404 | La lectura se puede desplegar sola, sin la fusión (`itinerary-lectura`) | Regla I3; ADR-0021 |
| Están las diez tablas de §5.8 y cinco más: `comando_idempotente`, `usuario_version`, `evento_interno`, `reserva_lectura` y `viaje_lectura`. `reserva` guarda también `cancelada` y los fijados, con su valor y su instante; `viaje`, lo derivado de sus reservas y la próxima transición | `Idempotency-Key`, `versionUsuario` y la coordinación entre agregados las necesitan, y un conflicto se deriva del instante del fijado | Iteración 2 §5.8; ADR-0014; ADR-0018 |
| Una `Idempotency-Key` repetida con la misma solicitud devuelve la respuesta guardada; con otra solicitud, responde 400. Las claves duran 14 días, como la bandeja de entrada: el trabajo periódico borra lo vencido | El contrato pide «un solo efecto y la misma respuesta»; reutilizar la clave para otra cosa es un error del cliente | `comun.yaml` (`Idempotency-Key`); ADR-0014 |
| La baja manual (`DELETE /reservas/{id}`) pasa la reserva a `Descartada` desde cualquier estado y publica `ReservaActualizada`. La reserva se conserva: un correo posterior con el mismo localizador no la revive, pero un alta manual sí | «Baja como observación de fuente manual», sin perder la identidad. Se decidió al implementar el paso 4: los contratos no tienen un estado ni un evento de baja | Iteración 2, paso 7 (RF-06) |
| Una edición no agrega, quita ni cambia el tipo de los tramos, y quitar un campo del detalle no lo fija. La corrección al confirmar una reserva `PorConfirmar` se aplica como una edición, y con eso ya queda confirmada | Cambiar la estructura de una reserva automática sería pisar a sus fuentes. El usuario «confirma, corrige o descarta» la banda media | ADR-0013; ADR-0015 |
| `itinerary.yaml` 1.1.0 declara los `400`, `404` y `409` que los comandos sobre reservas ya podían devolver | Un error sin declarar sería una respuesta fuera del contrato | ADR-0027 (cambio compatible) |
| La API de `itinerary` todavía no verifica el vale interno (`X-Vale-Autorizacion`) ni descuenta `X-Deadline-Ms` | Dependen de otras partes del plan: el vale lo emite `identity-access` (ADR-0028), que se construye desde el paso 7, y los plazos son del paso 11 (ADR-0020). Quedan anotadas para no darlas por cumplidas | Contrato `itinerary.yaml` (`security`, `X-Deadline-Ms`) |
| `Reserva` y `Viaje` nunca se escriben en la misma transacción. Cada `ReservaActualizada` queda también en `evento_interno` (en la transacción del cambio) y `viajes` la procesa en una segunda. Un comando espera a las dos para responder con su `viajeId`. Si la segunda falla, el evento sigue en la cola y lo procesa el trabajo periódico | Es la coordinación por eventos internos de ADR-0010, sin perder el evento si algo falla entre las dos transacciones; responder con el estado resultante es la mitigación que prevé el mismo ADR | ADR-0010; vista N2 (regla I1) |
| `viajes` conoce cada reserva por un resumen (estado, tipo, inicio y fin de sus segmentos) que toma de `ReservaActualizada`, y el rol lo pide al registro de tipos | Así no importa a `reservas` (I1) ni nombra un tipo concreto (I4) | ADR-0010; ADR-0011 |
| Agrupación: una reserva se une al viaje activo que, ampliado 72 h, toca su período **y** con el que tiene continuidad (empieza en la misma ciudad que una llegada del viaje: el fin de un traslado, un alojamiento o una movilidad local). Si hay varios, el más cercano en el tiempo. La asignación se decide **una vez**: si la reserva cambia después, el viaje recalcula su período pero ella no cambia de viaje. Las `PorConfirmar` no entran y las `Descartada` salen | Es la regla 1 de §5.1, con la continuidad tomada en sentido amplio para incluir «un alojamiento en la ciudad de destino». Que no se reagrupe se decidió al implementar el paso 5, para que las reservas no salten de viaje sin que el usuario lo pida | Iteración 2 §5.1 y §5.11; ADR-0015 |
| «Misma ciudad»: a 50 km o menos si los dos lugares tienen coordenadas; si no, el mismo código; si no, el mismo nombre | `Lugar` no tiene ciudad. Los 50 km son un supuesto a calibrar, como los 72 h. Se decidió al implementar el paso 5 | Iteración 2 §5.1; iteración 4, paso 7 (RF-07) |
| El destino principal es el fin del primer traslado; si no hay, el alojamiento más largo; si no, el primer lugar del viaje. El título es «Viaje a {nombre del destino}» | El título y el período «se derivan de las reservas», sin más precisión | Iteración 2 §5.1 |
| Un viaje que se queda sin reservas pasa a `Eliminado`. Eliminar un viaje no toca sus reservas: quedan ocultas con él | Un viaje vacío no tiene qué mostrar, y ADR-0010 separa los dos agregados. Lo de las reservas se decidió al implementar el paso 5 | ADR-0010; iteración 2 §5.1 (RF-08) |
| El archivo manual se admite en cualquier estado salvo `Archivado` y `Eliminado` (si no, 409). Un viaje `Cancelado` no se completa solo: queda visible hasta que el usuario lo archiva o lo elimina | Es la fila `Cancelado` de la tabla del ciclo de vida | Iteración 2 §5.1 (RF-08) |
| `ViajeArmado` se publica al crearse el viaje y en cada cambio de miembros, período, título o estado, con su `version` | Así `event-pipeline` y la proyección del panel se enteran de cada cambio, en orden. Se decidió al implementar el paso 5; agregar `version` es un cambio compatible del contrato (AsyncAPI 1.3.0) | ADR-0027; contrato AsyncAPI |
| La gracia entre `Completado` y `Archivado` es de 3 días para todos | Es el valor por omisión de `diasDeGraciaArchivado`. El del usuario llegaría con `PreferenciasActualizadas`, pero `preferences` no está en el plan del prototipo | Iteración 2 §5.11; `preferences.yaml` |
| Un trabajo periódico (cada `TROTAMUNDOS_INTERVALO_TAREAS` segundos, 60 por omisión) procesa los eventos internos pendientes, avanza los viajes cuya `proxima_transicion` venció y purga la bandeja de entrada y las claves de idempotencia. Las transiciones se calculan en UTC a partir del fin local de cada tramo | §5.1 habla de trabajos «por zona horaria»: con un solo proceso no hace falta repartirlos, alcanza con que el instante de cada transición respete la zona del lugar | Iteración 2 §5.1; ADR-0014 |
| `panel_usuario` es una fila por usuario con el `Panel` completo, que se rearma con cada evento del usuario. Como se actualiza en la misma transacción que el cambio, `X-Min-Version` siempre se cumple en una sola región | UC-3 pide el panel en una sola ida y vuelta, y QA-02, un acceso | ADR-0018; ADR-0019; QA-02 |
| Cada carril es un tópico propio: el `address` del canal del contrato más el carril (`dominio.reserva-observada.p1`). El canal lógico sigue siendo el del contrato | Kafka no prioriza mensajes dentro de un tópico: con tópicos separados, P1 no espera detrás de una avalancha de P2. Que dos eventos del mismo usuario lleguen en otro orden por ir en carriles distintos es seguro, porque la fusión no depende del orden. Se decidió al implementar el paso 6 | ADR-0020; iteración 3 §5.3; ADR-0014 (N3) |
| El carril sale de `x-carril`. Si es una regla, la aplica el productor: `itinerary` manda `ReservaActualizada` por P1 si la reserva está en curso o sale en menos de 48 h, y por P2 si no. Se crean los tópicos de todos los carriles que el contrato nombra (los tres si no nombra ninguno) | Es la tabla de carriles de la iteración 3 («cambios sobre viajes EnCurso o con salida < 48 h») | Contrato AsyncAPI (`x-carril`); iteración 3 §5.3 |
| La *outbox* guarda el carril y un número de orden. Un único publicador por esquema (bloqueo consultivo) envía en ese orden, con clave `usuarioId`, y después marca. Si falla entre enviar y marcar, reenvía: es «al menos una vez» | Un solo publicador conserva el orden por usuario; el duplicado posible lo frena la bandeja de entrada del consumidor | ADR-0012; ADR-0014 |
| El consumidor lee de a un carril por vuelta y siempre el más urgente con mensajes; P3 se puede pausar. Un mensaje que no cumple el contrato se guarda en `evento_rechazado` y se sigue; cualquier otro error se reintenta sin avanzar el desplazamiento | Nada se descarta en silencio y un error transitorio no pierde el evento. Qué hacer con los inválidos se decidió al implementar el paso 6: los documentos no prevén una cola de fallidos | ADR-0020; ADR-0014; QA-11 |
| Los tópicos se crean al arrancar, con 6 particiones, y la creación falla si el broker rechaza alguno | La vista de despliegue N2 prevé 96 particiones por región; en una notebook alcanzan 6. El cliente no avisa si un tópico no se creó: se revisa la respuesta | Vista de despliegue N2 |
| Las pruebas que necesitan PostgreSQL se saltean, con el motivo, si no está levantado | Las del dominio corren en cualquier máquina; las de persistencia piden `make infra-arriba` | ADR-0017 |
| Todos los servicios usan la misma imagen, construida desde la raíz del repositorio para incluir `contratos/`; cada uno es un proceso con su comando | Un solo paquete y un proceso por servicio | ADR-0036 |

## Cómo correrlo

Requisitos: Python 3.12, Docker con Compose.

```bash
cd prototipo
make instalar        # crea .venv e instala dependencias
make infra-arriba    # levanta PostgreSQL (puerto 55432) y el broker (puerto 19092)
make pruebas         # corre las pruebas (las de PostgreSQL se saltean si no está arriba)
make servicios-arriba # además construye la imagen y levanta los servicios
make infra-abajo
```

Servicios que levanta `make servicios-arriba`:

| Servicio | Puerto local | Contrato |
|---|---|---|
| `itinerary` | 18101 | [`openapi/itinerary.yaml`](../contratos/openapi/itinerary.yaml): panel, viajes, reservas y tipos de segmento. Además publica su *outbox* y consume `ReservaExtraida` y `ReservaObservada` del broker |

Variables de entorno opcionales: `TROTAMUNDOS_CONTRATOS`, `TROTAMUNDOS_DSN`, `TROTAMUNDOS_BROKER`,
`TROTAMUNDOS_REGION`, `TROTAMUNDOS_INTERVALO_TAREAS` (segundos entre corridas del trabajo
periódico; 0 lo apaga) y `TROTAMUNDOS_PREFIJO_TOPICOS` (antepuesto a los tópicos; las pruebas lo
usan para no mezclarse). Con `TROTAMUNDOS_BROKER` vacío, un servicio no publica ni consume.

## Plan de construcción

Cada paso se entrega en uno o más commits chicos. La columna «Trazabilidad» indica qué decisiones
implementa.

| # | Paso | Trazabilidad | Estado |
|---|---|---|---|
| 1 | Base: tecnología, infraestructura, validación contra `contratos/` | ADR-0009, ADR-0036 | ✅ |
| 2 | Registro de tipos de segmento y modelos canónicos | ADR-0010, ADR-0011 | ✅ |
| 3 | `itinerary`: agregado `Reserva` y fusión determinista | ADR-0010, ADR-0013 | ✅ |
| 4 | `itinerary`: persistencia, *outbox*, *inbox* y API interna | ADR-0012, ADR-0014 | ✅ |
| 5 | `itinerary`: viajes, agrupación, ciclo de vida y proyección del panel | RF-07, RF-08 | ✅ |
| 6 | *Broker*: publicador de la *outbox*, consumidores y carriles | ADR-0014, ADR-0020 | ✅ |
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
