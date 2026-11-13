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
| Los eventos y las respuestas se validan en el mismo proceso contra los archivos de `contratos/`, sin un registro de esquemas | Da la misma garantía (nada sale del servicio sin cumplir el contrato) sin agregar otro servidor a la infraestructura local. La compatibilidad entre versiones se comprueba con pruebas (paso 17) | La iteración 4 prevé un registro de esquemas AsyncAPI con compatibilidad `BACKWARD_TRANSITIVE` (ADR-0027); el prototipo lo reemplaza, no lo contradice |
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
| La gracia entre `Completado` y `Archivado` es de 3 días para todos, por ahora | Es el valor por omisión de `diasDeGraciaArchivado`. La de cada usuario llega con `PreferenciasActualizadas`, cuando exista `preferences` (paso 12) | Iteración 2 §5.11; `preferences.yaml` |
| Un trabajo periódico (cada `TROTAMUNDOS_INTERVALO_TAREAS` segundos, 60 por omisión) procesa los eventos internos pendientes, avanza los viajes cuya `proxima_transicion` venció y purga la bandeja de entrada y las claves de idempotencia. Las transiciones se calculan en UTC a partir del fin local de cada tramo | §5.1 habla de trabajos «por zona horaria»: con un solo proceso no hace falta repartirlos, alcanza con que el instante de cada transición respete la zona del lugar | Iteración 2 §5.1; ADR-0014 |
| `panel_usuario` es una fila por usuario con el `Panel` completo, que se rearma con cada evento del usuario. Como se actualiza en la misma transacción que el cambio, `X-Min-Version` siempre se cumple en una sola región | UC-3 pide el panel en una sola ida y vuelta, y QA-02, un acceso | ADR-0018; ADR-0019; QA-02 |
| Cada carril es un tópico propio: el `address` del canal del contrato más el carril (`dominio.reserva-observada.p1`). El canal lógico sigue siendo el del contrato | Kafka no prioriza mensajes dentro de un tópico: con tópicos separados, P1 no espera detrás de una avalancha de P2. Que dos eventos del mismo usuario lleguen en otro orden por ir en carriles distintos es seguro, porque la fusión no depende del orden. Se decidió al implementar el paso 6 | ADR-0020; iteración 3 §5.3; ADR-0014 (N3) |
| El carril sale de `x-carril`. Si es una regla, la aplica el productor: `itinerary` manda `ReservaActualizada` por P1 si la reserva está en curso o sale en menos de 48 h, y por P2 si no. Se crean los tópicos de todos los carriles que el contrato nombra (los tres si no nombra ninguno) | Es la tabla de carriles de la iteración 3 («cambios sobre viajes EnCurso o con salida < 48 h») | Contrato AsyncAPI (`x-carril`); iteración 3 §5.3 |
| La *outbox* guarda el carril y un número de orden. Un único publicador por esquema (bloqueo consultivo) envía en ese orden, con clave `usuarioId`, y después marca. Si falla entre enviar y marcar, reenvía: es «al menos una vez» | Un solo publicador conserva el orden por usuario; el duplicado posible lo frena la bandeja de entrada del consumidor | ADR-0012; ADR-0014 |
| El consumidor lee de a un carril por vuelta y siempre el más urgente con mensajes; P3 se puede pausar. Un mensaje que no cumple el contrato se guarda en `evento_rechazado` y se sigue; cualquier otro error se reintenta sin avanzar el desplazamiento | Nada se descarta en silencio y un error transitorio no pierde el evento. Qué hacer con los inválidos se decidió al implementar el paso 6: los documentos no prevén una cola de fallidos | ADR-0020; ADR-0014; QA-11 |
| Los tópicos se crean al arrancar, con 6 particiones, y la creación falla si el broker rechaza alguno | La vista de despliegue N2 prevé 96 particiones por región; en una notebook alcanzan 6. El cliente no avisa si un tópico no se creó: se revisa la respuesta | Vista de despliegue N2 |
| `itinerary` se despliega en dos modos del mismo código: `itinerary-lectura` registra solo las rutas con etiqueta `lectura` del contrato e `itinerary-escritura`, solo las de `comando`, más el trabajo periódico y el *broker*. Al armar la API se verifica que toda ruta esté en el contrato | Es la separación de ADR-0021: la lectura escala y se despliega sin arrastrar la fusión. La etiqueta del contrato decide el modo de cada ruta, así el código no puede divergir. La Opción B lee de `itinerary-lectura` (ADR-0034) | ADR-0021; iteración 3 §5.4; ADR-0009 |
| El PostgreSQL local no tiene contraseña (`trust`) y su puerto solo escucha en `127.0.0.1` | Así no hay credenciales en el código, que SonarCloud marca como vulnerabilidad aunque sean de una base descartable. Un entorno real tomaría las credenciales de un gestor de secretos | ADR-0029 (custodia de secretos); análisis de SonarCloud |
| La imagen instala las dependencias desde un archivo de bloqueo (`requirements.txt`, todas con versión exacta) y solo como binarios; el código propio corre desde el fuente | Instalaciones reproducibles y sin ejecutar *scripts* de terceros al construir la imagen. Una prueba mantiene el bloqueo alineado con `pyproject.toml` | ADR-0036; análisis de SonarCloud |
| SonarCloud no analiza `contratos/analitica/*.sql` (`.sonarcloud.properties`) | Lo lee como PL/SQL de Oracle y marca como error el `CHAR` de SQL ANSI, que es el dialecto del contrato. Es un falso positivo | ADR-0016; `contratos/README.md` |
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

**Integración continua.** En cada cambio de `prototipo/` o `contratos/`,
[`.github/workflows/pruebas.yml`](../.github/workflows/pruebas.yml) levanta PostgreSQL y Redpanda
con el mismo `docker-compose.yml` y corre todas las pruebas. Ahí se define
`TROTAMUNDOS_EXIGIR_INFRA=1`: sin base o sin broker, las pruebas fallan en lugar de saltearse.

**Base local sin contraseña.** El PostgreSQL de `docker-compose.yml` no tiene contraseña y solo
acepta conexiones desde esta máquina (`127.0.0.1:55432`) y desde la red interna del compose.

**Dependencias.** `pyproject.toml` declara las directas; `requirements.txt` es el archivo de bloqueo
con todas, incluidas las transitivas, y es lo que instala la imagen. Si cambia una versión en
`pyproject.toml`, hay que regenerarlo (`tests/test_dependencias.py` avisa si no coinciden):

```bash
python3.12 -m venv /tmp/bloqueo && /tmp/bloqueo/bin/pip install --only-binary :all: \
  $(.venv/bin/python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")
/tmp/bloqueo/bin/pip freeze --exclude pip   # reemplaza las líneas de requirements.txt (sin el encabezado)
```

Servicios que levanta `make servicios-arriba`:

| Servicio | Puerto local | Contrato |
|---|---|---|
| `itinerary-escritura` | 18101 | Los comandos de [`openapi/itinerary.yaml`](../contratos/openapi/itinerary.yaml) (etiqueta `comando`). Además corre el trabajo periódico, publica su *outbox* y consume `ReservaExtraida` y `ReservaObservada` del broker |
| `itinerary-lectura` | 18102 | Las lecturas del mismo contrato (etiqueta `lectura`): panel, viajes, reservas y tipos de segmento |

Variables de entorno opcionales: `TROTAMUNDOS_CONTRATOS`, `TROTAMUNDOS_DSN`, `TROTAMUNDOS_BROKER`,
`TROTAMUNDOS_REGION`, `TROTAMUNDOS_INTERVALO_TAREAS` (segundos entre corridas del trabajo
periódico; 0 lo apaga) y `TROTAMUNDOS_PREFIJO_TOPICOS` (antepuesto a los tópicos; las pruebas lo
usan para no mezclarse). Con `TROTAMUNDOS_BROKER` vacío, un servicio no publica ni consume.
`TROTAMUNDOS_MODO` elige el modo de despliegue de `itinerary`: `completo` (por omisión), `lectura` o
`escritura`.

## Estado de las decisiones de arquitectura

Qué ADR implementa el prototipo hasta ahora, cuál se implementa en un paso posterior y cuál queda
fuera del alcance que fija [ADR-0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md)
(una tajada vertical por los 5 ASR, no el sistema completo). Se actualiza al cerrar cada paso.

✅ implementado · 🟨 parcial · ⏳ en un paso posterior · ➖ fuera de alcance

| ADR | Estado | Dónde está o cuándo llega |
|---|---|---|
| [0001](../docs/03-adr/ADR-0001-estilo-arquitectonico.md) Microservicios orientados a eventos | 🟨 | `itinerary` y lo compartido en `comun`; ningún servicio importa a otro (prueba de arquitectura). Los demás servicios, pasos 7 a 14 |
| [0002](../docs/03-adr/ADR-0002-despliegue-multirregion.md) Activo-activo en tres regiones | ⏳ | Paso 16, como multirregión simulada: dos regiones con región primaria por usuario (ver ADR-0018). Las tres regiones reales ➖ |
| [0003](../docs/03-adr/ADR-0003-separacion-planos.md) Plano operacional y analítico separados | ⏳ | Paso 14 |
| [0004](../docs/03-adr/ADR-0004-obtencion-de-correo.md) Correo por *push* con reconciliación | ⏳ | Paso 8 |
| [0005](../docs/03-adr/ADR-0005-capa-de-clientes-bff.md) Un BFF por tipo de cliente | ⏳ | Paso 11 |
| [0006](../docs/03-adr/ADR-0006-capa-de-anticorrupcion.md) Capa de anticorrupción con complementos | ⏳ | Pasos 9 y 10 (la prueba ya reserva las carpetas `complementos/`) |
| [0007](../docs/03-adr/ADR-0007-identidad-y-comparticion.md) OIDC, delegación OAuth y designados | ⏳ | Pasos 7 y 13 |
| [0008](../docs/03-adr/ADR-0008-alcance-disponibilidad.md) Alcance y medición de la disponibilidad | ➖ | Medir disponibilidad real no tiene sentido en una notebook; lo crítico se ejercita con QA-05 |
| [0009](../docs/03-adr/ADR-0009-contratos-spec-driven.md) Contratos como artefactos de primera clase | 🟨 | Todo cuerpo, respuesta y evento se valida contra `contratos/` en ejecución, y la integración continua corre todas las pruebas en cada cambio. La detección de cambios incompatibles entre versiones, paso 17 |
| [0010](../docs/03-adr/ADR-0010-modelo-canonico-reserva-segmento-viaje.md) Agregados `Reserva` y `Viaje` | ✅ | Pasos 3 a 5: ninguna transacción escribe los dos (probado) y se coordinan por eventos internos |
| [0011](../docs/03-adr/ADR-0011-extensibilidad-del-tipo-de-segmento.md) Registro de tipos de segmento | ✅ | Pasos 2 a 5 (regla I4 probada). El tipo `tren` sin tocar código (QA-15), paso 15 |
| [0012](../docs/03-adr/ADR-0012-persistencia-del-plano-operacional.md) Persistencia relacional por `usuario_id` | ✅ | Las diez tablas de §5.8, con las unicidades impuestas por la base y la *outbox*. La compactación, ver ADR-0023 |
| [0013](../docs/03-adr/ADR-0013-deduplicacion-y-conflictos.md) Identidad, precedencia y conflictos | ✅ | Paso 3: una prueba por regla, más pruebas de propiedades. La métrica «conflictos abiertos por usuario y por semana», paso 14 (desde `ConflictoDeFuentesDetectado`) |
| [0014](../docs/03-adr/ADR-0014-idempotencia-de-la-ingesta.md) Bandeja de entrada y fusión determinista | ✅ | Pasos 3 a 6: bandeja de entrada, `Idempotency-Key`, entrega repetida sin doble efecto y reversión 10:00 → 10:30 → 10:00 (probados). La de `mail-ingest`, paso 8 |
| [0015](../docs/03-adr/ADR-0015-politica-de-confianza-de-extraccion.md) Tres bandas de confianza | 🟨 | Del lado de `itinerary` está (`PorConfirmar`, la banda media no cambia lo confirmado). Los extractores y el corpus, paso 9 |
| [0016](../docs/03-adr/ADR-0016-modelo-dimensional-analitico.md) Esquema en estrella desde eventos | ⏳ | Paso 14 |
| [0017](../docs/03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md) Pruebas derivadas de la especificación | 🟨 | Propiedades de la fusión y validación contra contratos, en la integración continua (`.github/workflows/pruebas.yml`). Conformidad de complementos y corpus, pasos 9 y 10; Schemathesis y compatibilidad, paso 17 |
| [0018](../docs/03-adr/ADR-0018-consistencia-datos-multirregion.md) Región primaria, testigo y lectura causal | 🟨 | `versionUsuario` y escrituras serializadas por usuario. Región primaria, testigo transregional síncrono para los comandos manuales y conmutación, paso 16 (QA-05) |
| [0019](../docs/03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) Caché multinivel y arranque móvil | ⏳ | Paso 11 (el panel ya se lee en un acceso) |
| [0020](../docs/03-adr/ADR-0020-contrapresion-y-sobrecarga.md) Contrapresión, carriles y degradación | 🟨 | Carriles P1/P2/P3 (paso 6). Plazo propagado, colas acotadas y modos de degradación, pasos 11 y 17 |
| [0021](../docs/03-adr/ADR-0021-estrategia-autoescalado.md) Autoescalado y lectura/escritura separadas | 🟨 | `itinerary-lectura` e `itinerary-escritura` como modos del mismo código (`TROTAMUNDOS_MODO`). El autoescalado es de la plataforma de producción ➖ |
| [0022](../docs/03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) Entrega canaria y *expand/contract* | ➖ | Requiere varias regiones y tráfico real |
| [0023](../docs/03-adr/ADR-0023-particionamiento-y-crecimiento.md) Particionamiento, compactación y archivo frío | 🟨 | La clave de partición `usuario_id` está en toda tabla y en el *broker*. Los 64 *buckets*, la compactación y el archivo frío ➖ (volumen de producción); la consolidación ya es indiferente a la compactación (probado) |
| [0024](../docs/03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) Cortacircuitos, cola persistente y cuotas | ⏳ | Paso 10 |
| [0025](../docs/03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) Observabilidad y presupuesto de error | 🟨 | `traceparent` e `idDeCorrelacion` se propagan en HTTP y eventos. OpenTelemetry y SLO ➖: no están en el plan |
| [0026](../docs/03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) Modelo de costo | ➖ | Es una decisión de operación, no de código |
| [0027](../docs/03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) Evolución compatible de contratos | 🟨 | Los contratos evolucionan con SemVer y cambios compatibles (`itinerary.yaml` 1.1.0, AsyncAPI 1.3.0). El tipo de medio versionado de la API pública, paso 11 |
| [0028](../docs/03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) ABAC, vales firmados y designados | 🟨 | El mismo 404 para «no existe» y «no es tuyo». El vale interno, desde el paso 7; designados y publicación, paso 13 |
| [0029](../docs/03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) Cifrado por sobres y custodia | ⏳ | Paso 7 (QA-13) |
| [0030](../docs/03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) Auditoría y supresión de datos | 🟨 | Los errores no filtran datos internos. Auditoría, paso 7; supresión en el plano analítico, paso 14 |
| [0031](../docs/03-adr/ADR-0031-residencia-de-datos-por-region.md) Residencia de datos por región | ➖ | La multirregión del paso 16 se simula en una sola jurisdicción; las clases de residencia no aplican |
| [0032](../docs/03-adr/ADR-0032-internacionalizacion-y-localizacion.md) Internacionalización | 🟨 | Instantes en UTC con zona IANA aparte, en todo el modelo. Idioma y formateo, en los BFF (paso 11) |
| [0033](../docs/03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) GPS en el móvil | ➖ | No hay cliente móvil nativo en el prototipo |
| [0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) Módulo avanzado y recorte del prototipo | 🟨 | El recorte guía este plan. La Opción B, pasos 18 y 19 |
| [0035](../docs/03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) Buzones sin OAuth y formatos desconocidos | ⏳ | Pasos 8 y 9 |
| [0036](../docs/03-adr/ADR-0036-tecnologia-del-prototipo.md) Tecnología del prototipo | ✅ | Python 3.12, FastAPI, PostgreSQL, Redpanda y Docker Compose. Schemathesis, paso 17 |

Además de los ADR: `preferences` se construye como servicio mínimo en el paso 12, porque su evento
`PreferenciasActualizadas` lo consumen `itinerary` (la gracia de archivado de cada usuario) y la
Opción B (ADR-0034).

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
| 12 | `notification`, `support-liaison` y `preferences` mínimo | UC-5, UC-7, ADR-0034 | ⬜ |
| 13 | `sharing`: compartición y `ResumenPublicable` | QA-12, ADR-0028 | ⬜ |
| 14 | `event-pipeline` y plano analítico | QA-09, ADR-0016 | ⬜ |
| 15 | Tipo `tren` sin tocar código de dominio | QA-15 | ⬜ |
| 16 | Multirregión simulada: región primaria por usuario, testigo transregional y conmutación | QA-05, ADR-0018 | ⬜ |
| 17 | Pruebas de contrato y de escenarios (QA-01, QA-04, QA-05) | ADR-0017 | ⬜ |
| 18 | Iteración 5 de ADD: diseño de la Opción B (ADRs y contrato) | CON-06 | ⬜ |
| 19 | `virtual-assistant`: intenciones y derivación a la agencia | RF-B1, RF-B2 | ⬜ |
| 20 | Interfaz web mínima de demostración | RF-09 | ⬜ |
| 21 | Matriz código ↔ ADR, guion de demostración y README final | QA-16 | ⬜ |
