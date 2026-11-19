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
│   │   ├── sesion.py           # sesión OIDC de las operaciones públicas      (ADR-0007)
│   │   └── tipos_de_segmento.py # registro de descriptores de tipo           (ADR-0011, ADR-0027)
│   └── servicios/              # un subpaquete por servicio; ninguno importa a otro (ADR-0036)
│       ├── itinerary/          # un módulo por cada módulo de la vista N2, más servicio.py
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
│       ├── identity_access/         # identidad, buzones, bóveda, ABAC y auditoría (paso 7)
│           ├── auditoria_y_revocacion.py # bitácora SHA-256 y detector de anomalías (ADR-0029, ADR-0030)
│           ├── autenticacion_oidc.py     # OIDC simulado y OTP para invitados (ADR-0007, ADR-0028)
│           ├── consentimiento_buzones.py # ciclo de vida de buzones y revocación en bloque (RF-01, ADR-0035)
│           ├── custodia_boveda.py        # único módulo con KMS/AES-GCM (regla R5, ADR-0029)
│           ├── motor_autorizacion_abac.py# políticas ABAC y vales JWS de 60 s (ADR-0028)
│           ├── publicacion.py            # outbox: EstadoDeBuzonCambiado y CuentaSuprimida
│           ├── api.py                    # API (openapi/identity-access.yaml)
│           └── servicio.py               # arma los módulos y define las transacciones
│       ├── mail_ingest/             # obtención del correo (paso 8, vista N2 §3)
│           ├── suscripciones.py      # buzones a atender y suscripciones de avisos (ADR-0004)
│           ├── receptor.py           # aviso del proveedor: firma y a la cola (ADR-0020)
│           ├── reconciliador.py      # sondeo escalonado por buzón (ADR-0004, ADR-0024)
│           ├── cola.py               # «buzones con cambios»: donde convergen los dos caminos
│           ├── descargador.py        # token efímero de identity-access (ADR-0029)
│           ├── filtros.py            # permitidos, bloqueados y catálogo (RF-04)
│           ├── normalizador.py       # RFC 5322 → MensajeNormalizado
│           ├── deduplicador.py       # bandeja (buzón, idDeMensaje) (ADR-0014)
│           ├── receptor_reenvio.py   # alias de reenvío: DKIM/SPF/ARC y titular (ADR-0035)
│           ├── publicacion.py        # outbox: MensajeDeViajeRecibido
│           ├── interfaz_de_correo.py # lo que implementa cada complemento de proveedor (ADR-0006)
│           ├── complementos/         # proveedor de correo simulado (con push e IMAP)
│           ├── api.py                # webhooks y filtros (mail-ingest-*.yaml)
│           └── servicio.py           # arma los módulos y define las transacciones
│       ├── booking_extraction/     # extractor, bandas, calidad e inbox/outbox (paso 9)
│       │   ├── complementos/        # único extractor de correo simulado
│       │   ├── registro_de_extractores.py # carga por manifiesto y coordina la extracción
│       │   ├── validador_canonico.py # estructura y descriptor del segmento
│       │   ├── evaluador_de_confianza.py # mínimo de campos obligatorios y bandas
│       │   ├── observabilidad_de_calidad.py # huellas y disyuntor local
│       │   └── servicio.py         # inbox/outbox, broker y fábrica de Uvicorn
│       └── support_liaison/         # casos de soporte derivados a la agencia (paso 12, UC-7)
│           ├── casos.py              # el caso: instantánea, estados y reintento de derivación
│           ├── preferencias.py       # copia local de la agencia preferida (PreferenciasActualizadas)
│           ├── instantanea.py        # el viaje, leído de itinerary-lectura en nombre del viajero
│           ├── publicacion.py        # outbox: CasoDerivado
│           ├── interfaz_de_agencia.py # lo que implementa cada complemento de agencia (ADR-0006)
│           ├── complementos/         # agencia simulada
│           ├── api.py                # POST /casos y sus lecturas (support-liaison.yaml)
│           └── servicio.py           # arma los módulos y define las transacciones
│       ├── virtual_assistant/       # asistente virtual de la Opción B (paso 19, ADR-0037 a 0040)
│           ├── catalogos/es/         # patrones de cada intención y mensajes (recurso, sin código)
│           ├── catalogo.py           # lee los catálogos y formatea mensajes y fechas
│           ├── interprete.py         # puerto InterpreteDeIntenciones y su implementación por reglas
│           ├── dialogo.py            # un turno: entender, decidir, responder (sin base)
│           ├── acciones.py           # corrección y problemas menores, solo con confirmación
│           ├── derivacion.py         # los cuatro disparadores, la síntesis y POST /casos
│           ├── contexto.py           # panel y viajes en nombre del viajero; disrupciones conocidas
│           ├── sesiones.py           # sesiones, turnos, acción pendiente y retención de 30 días
│           ├── api.py                # virtual-assistant.yaml
│           └── servicio.py           # arma los módulos y define las transacciones
│       ├── bff_web/                 # BFF para app-web (paso 11, ADR-0005, ADR-0019, ADR-0027, ADR-0034)
│           ├── clientes.py           # adaptadores HTTP a itinerary-lectura, itinerary-escritura y virtual-assistant
│           ├── api.py                # bff-web.yaml: ETag/304, Cache-Control, v1+json y X-Version-Usuario
│           └── servicio.py           # arma el elemento sin estado propio
│       ├── provider_sync/           # sincronización con proveedores de viaje (paso 10, ADR-0006, QA-10)
│           ├── interfaz_de_adaptador.py      # puerto AdaptadorDeProveedor v1.x (plugins/adaptador.yaml)
│           ├── complementos/                 # adaptador NDC de aerolínea simulada (JSON y XML)
│           ├── catalogo_adaptadores.yaml     # manifiesto declarativo de adaptadores registrados
│           ├── registro_de_adaptadores.py    # carga por configuración, verifica SemVer y valida salidas
│           ├── seguimiento.py                # índice (adaptador, referencia) → (usuarioId, reservaId)
│           ├── receptor_de_notificaciones.py # firma HMAC-SHA256 y decodificación de webhooks
│           ├── programador.py                # sondeo periódico de proveedores con sondeo: true
│           ├── detector_de_disrupciones.py   # expande disrupciones a usuarios afectados con seguimiento
│           ├── publicacion.py                # outbox: ReservaObservada (P1/P2) y DisrupcionDetectada (P1)
│           ├── api.py                        # POST /webhooks/proveedor (provider-sync-webhooks.yaml)
│           └── servicio.py                   # arma los módulos, consume ReservaActualizada/Cancelada y publica
│       └── event_pipeline/          # canalización y plano analítico separado (paso 14, ADR-0003, ADR-0016, QA-09)
│           ├── aterrizaje.py                 # capa de aterrizaje evento_crudo con seudónimo (sin PII)
│           ├── modelo_dimensional.py         # esquema en estrella (modelo-dimensional.sql), reconstrucción y QA-15
│           └── servicio.py                   # consumidor hacia analytics_store y fábrica de Uvicorn
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
| Dentro de `virtual_assistant`, cada módulo importa solo lo que permite la vista de módulos del asistente, y solo `contexto`, `acciones` y `derivacion` hablan con otros servicios. Solo `interprete` usa los patrones, los módulos que le responden al viajero no tienen frases en el código y cada clave de mensaje usada existe en el catálogo | ADR-0037; vista de módulos del asistente |
| Dentro de `bff_web`, ningún módulo tiene persistencia propia ni lógica de dominio: solo compone respuestas de `itinerary-lectura`, `itinerary-escritura` y `virtual-assistant` por HTTP | R4, vista de módulos N1; ADR-0005, ADR-0034 |
| Dentro de `provider_sync`, cada módulo respeta las dependencias de la vista de adaptadores y ningún complemento en `complementos/` importa a otro complemento | R2, R3, vista de módulos de adaptadores §1; ADR-0006, QA-10 |
| Dentro de `event_pipeline`, ningún módulo hace llamadas HTTP ni publica eventos al plano operacional: solo consume eventos del *broker* y escribe en su esquema analítico propio (`analytics_store`) | R6, vista de módulos N1; ADR-0003, QA-09 |

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
| `identity-access.yaml` 1.2.0, `mail-ingest-filtros.yaml` 1.1.0 y `support-liaison.yaml` 1.1.0 declaran el `401` de toda operación con sesión, y el `400` de las que validan el cuerpo o la `Idempotency-Key` (`POST /casos`, `POST /privacidad/exportaciones`, `DELETE /privacidad/cuenta`) | El código ya los devolvía (`comun/sesion.py` y la validación contra el contrato): una respuesta sin declarar queda fuera del contrato, como se corrigió en `itinerary.yaml` 1.1.0. Se reusan `NoAutenticado` y `SolicitudInvalida` de `comun.yaml` | ADR-0027 (cambio compatible); ADR-0009 |
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
| Una reserva `Confirmada` pasa a `Finalizada` 24 h después del fin de su último tramo no cancelado (con `precision: dia`, del fin del día local). Lo marca el trabajo periódico, y cada consolidación lo recalcula: si una fuente corre el fin para más adelante, vuelve a `Confirmada`. `ReservaActualizada` publica la reserva con el estado nuevo, pero no lo lista en `cambios`, porque el contrato pide una fuente por cambio y a este lo provoca el paso del tiempo | La iteración 2 (§5.2) tiene el estado pero no dice cuándo se entra; se usa el mismo margen con que el viaje pasa a `Completado`. Acordado con el grupo. Los límites de un extremo (`limites_del_extremo`) pasaron a `comun/modelo.py` porque los usan `reservas` y `viajes`, que no se importan entre sí | Iteración 2 §5.1 y §5.2; vista N2 (regla I1) |
| `panel_usuario` es una fila por usuario con el `Panel` completo, que se rearma con cada evento del usuario. Como se actualiza en la misma transacción que el cambio, `X-Min-Version` siempre se cumple en una sola región | UC-3 pide el panel en una sola ida y vuelta, y QA-02, un acceso | ADR-0018; ADR-0019; QA-02 |
| Cada carril es un tópico propio: el `address` del canal del contrato más el carril (`dominio.reserva-observada.p1`). El canal lógico sigue siendo el del contrato | Kafka no prioriza mensajes dentro de un tópico: con tópicos separados, P1 no espera detrás de una avalancha de P2. Que dos eventos del mismo usuario lleguen en otro orden por ir en carriles distintos es seguro, porque la fusión no depende del orden. Se decidió al implementar el paso 6 | ADR-0020; iteración 3 §5.3; ADR-0014 (N3) |
| El carril sale de `x-carril`. Si es una regla, la aplica el productor: `itinerary` manda `ReservaActualizada` por P1 si la reserva está en curso o sale en menos de 48 h, y por P2 si no. Se crean los tópicos de todos los carriles que el contrato nombra (los tres si no nombra ninguno) | Es la tabla de carriles de la iteración 3 («cambios sobre viajes EnCurso o con salida < 48 h») | Contrato AsyncAPI (`x-carril`); iteración 3 §5.3 |
| La *outbox* guarda el carril y un número de orden. Un único publicador por esquema (bloqueo consultivo) envía en ese orden, con clave `usuarioId`, y después marca. Si falla entre enviar y marcar, reenvía: es «al menos una vez» | Un solo publicador conserva el orden por usuario; el duplicado posible lo frena la bandeja de entrada del consumidor | ADR-0012; ADR-0014 |
| El consumidor lee de a un carril por vuelta y siempre el más urgente con mensajes; P3 se puede pausar. Un mensaje que no cumple el contrato se guarda en `evento_rechazado` y se sigue; cualquier otro error se reintenta sin avanzar el desplazamiento | Nada se descarta en silencio y un error transitorio no pierde el evento. Qué hacer con los inválidos se decidió al implementar el paso 6: los documentos no prevén una cola de fallidos | ADR-0020; ADR-0014; QA-11 |
| Los tópicos se crean al arrancar, con 6 particiones, y la creación falla si el broker rechaza alguno | La vista de despliegue N2 prevé 96 particiones por región; en una notebook alcanzan 6. El cliente no avisa si un tópico no se creó: se revisa la respuesta | Vista de despliegue N2 |
| `itinerary` se despliega en dos modos del mismo código: `itinerary-lectura` registra solo las rutas con etiqueta `lectura` del contrato e `itinerary-escritura`, solo las de `comando`, más el trabajo periódico y el *broker*. Al armar la API se verifica que toda ruta esté en el contrato | Es la separación de ADR-0021: la lectura escala y se despliega sin arrastrar la fusión. La etiqueta del contrato decide el modo de cada ruta, así el código no puede divergir. La Opción B lee de `itinerary-lectura` (ADR-0034) | ADR-0021; iteración 3 §5.4; ADR-0009 |
| La contraseña del PostgreSQL local se genera al azar en `prototipo/.env` (ignorado por git) y su puerto solo escucha en `127.0.0.1` | Ni credenciales en el código ni una base sin contraseña: las dos cosas las marca SonarCloud. Un entorno real tomaría la contraseña de un gestor de secretos | ADR-0029 (custodia de secretos); análisis de SonarCloud |
| La imagen instala las dependencias desde un archivo de bloqueo (`requirements.txt`: versión exacta y *hash* de cada archivo, verificados con `--require-hashes`) y solo como binarios; el código propio corre desde el fuente | Instalaciones reproducibles, un paquete alterado no se instala y no se ejecutan *scripts* de terceros al construir la imagen. Una prueba mantiene el bloqueo alineado con `pyproject.toml` | ADR-0036; análisis de SonarCloud |
| SonarCloud no analiza `contratos/analitica/*.sql` (`.sonarcloud.properties`) | Lo lee como PL/SQL de Oracle y marca como error el `CHAR` de SQL ANSI, que es el dialecto del contrato. Es un falso positivo | ADR-0016; `contratos/README.md` |
| Las pruebas que necesitan PostgreSQL se saltean, con el motivo, si no está levantado | Las del dominio corren en cualquier máquina; las de persistencia piden `make infra-arriba` | ADR-0017 |
| Todos los servicios usan la misma imagen, construida desde la raíz del repositorio para incluir `contratos/`; cada uno es un proceso con su comando | Un solo paquete y un proceso por servicio | ADR-0036 |
| `identity-access.yaml` 1.1.0 agrega `POST /buzones/{id}/autorizacion` para completar el consentimiento OAuth (`Solicitado` → `Activo`) y guardar el *refresh token* bajo `DEK_u`. Las vías `reenvio` e `imapDelegado` pasan a `Activo` al crearse: cumplen lo que §5.7 pide para `Activo` (nada que consentir, o la credencial ya cifrada). Acordado con el grupo; la 1.1.1 lo dice en el resumen de `POST /buzones` | El contrato 1.0.0 devolvía `urlAutorizacion` en `POST /buzones`, pero no tenía operación de retorno para activar el buzón OAuth | ADR-0027 (cambio compatible); iteración 2 §5.7 (RF-01) |
| En local, la identidad mTLS de las rutas `x-interna: true` se simula con las cabeceras `X-Servicio-Cliente`, `X-Instancia-Cliente` y `X-Buckets-Arrendados` | Los servicios en `docker-compose.yml` hablan HTTP plano; `POST /buzones/{id}/token-efimero` exige `X-Servicio-Cliente: mail-ingest` (`403` en otro caso) y alimenta al detector de anomalías de 60 s | ADR-0029 (regla R5 y QA-13); ADR-0036 |
| `KmsLocal` en `custodia_boveda.py` simula el HSM/KMS regional con `KEK_region` en memoria (derivada de `TROTAMUNDOS_KMS_SECRETO`, que `make infra-arriba` genera en `.env` junto con `TROTAMUNDOS_JWT_SECRETO` y `TROTAMUNDOS_VALE_SECRETO`; al azar si no se fija) y `DEK_u` por usuario (`AES-256-GCM` + AAD). La tabla `kek_version` guarda solo qué versión está vigente y cuáles se inhabilitaron, y el servicio la carga al arrancar, como haría un KMS gestionado. `test_arquitectura.py` verifica que ningún otro módulo importe `cryptography` (`R5-estricto`) | Reemplaza el KMS gestionado de nube sin guardar claves maestras en PostgreSQL ni credenciales en código | ADR-0029; vista de adaptadores §4 (`R5-estricto`); ADR-0036 |
| La revocación regional en bloque inhabilita la versión de `KEK_region`, pasa a `v{N+1}` si era la vigente y descarta las `DEK_u` envueltas con ella y los secretos que protegían | Quedan ilegibles para siempre; sin una versión nueva, la reautorización y los buzones nuevos de la región fallarían | ADR-0029 (revocación en dos fases) |
| La revocación regional pasa a `RequiereReautorizacion` solo los buzones que guardan algo en la bóveda (`oauth`, `imapDelegado`); los de `reenvio` siguen `Activo`. Un `oauth` se reautoriza con `POST /buzones/{id}/autorizacion`; un `imapDelegado`, dándolo de baja y conectándolo con una credencial nueva | ADR-0029 revoca los *grants* y los tokens custodiados: el alias de reenvío no es un secreto. El contrato no tiene una operación para renovar la credencial IMAP | ADR-0029; ADR-0035 |
| Los proveedores de correo (OAuth con *push* e IMAP) se simulan con un complemento en `mail_ingest/complementos/`, en memoria. La demostración de punta a punta usa el reenvío, que recibe el mensaje crudo por HTTP | No hay proveedores reales en el prototipo. Acordado con el grupo, igual que `ProveedorOidcSimulado` en el paso 7 | ADR-0006; ADR-0036 |
| La firma `X-Firma` de los avisos es un HMAC-SHA256 del cuerpo con `TROTAMUNDOS_SECRETO_WEBHOOK_CORREO` (de `.env`). Un aviso de una suscripción que no es de un buzón activo responde `202` y no hace nada | `comun.yaml` admite HMAC o JWS. Responder igual no revela qué suscripciones existen | ADR-0020; `mail-ingest-webhooks.yaml` |
| Reconciliación con los intervalos «en reposo» de ADR-0024 (24 h con *push*, 6 h IMAP), escalonada por `buzon_id`; `MensajeDeViajeRecibido` va siempre por P2 | El ajuste por viaje en curso y el P1 del contrato necesitan saber de viajes, y `mail-ingest` no los consume. Acordado con el grupo | ADR-0004; ADR-0020; ADR-0024 |
| El catálogo de remitentes se deriva de `comun/catalogo_extractores.yaml`, el mismo manifiesto que carga `booking-extraction`; `mail-ingest` lo lee sin importar el servicio | Catálogo y registro tienen una sola fuente declarativa; se conserva bloqueados > permitidos > catálogo antes de descargar el cuerpo | ADR-0006; vista N2; RF-04 |
| El receptor de reenvío acepta un mensaje si su `Authentication-Results` del servidor propio (`ingesta.trotamundos.app`) dice `dkim=pass` y además `spf=pass` o `arc=pass`, y si quien reenvía (`Return-Path`, o `From` si no está) es el titular del buzón. Lo rechazado responde `403` y queda en `reenvio_rechazado` sin el contenido. El servidor de correo propio se identifica con `X-Servicio-Cliente: mta-entrante`, como el mTLS del paso 7 | Las cabeceras de autenticación que escribió otro servidor las puede poner cualquiera. El ARC es lo que sobrevive a un reenvío automático | ADR-0035; `mail-ingest-webhooks.yaml` |
| En el reenvío solo cuentan los remitentes bloqueados: no hace falta que el remitente esté permitido ni en el catálogo | Reenviar ya es una elección explícita del usuario, y en un reenvío manual el remitente es él mismo. Acordado con el grupo | ADR-0035; RF-04 |
| Los filtros se evalúan sobre los metadatos y solo se baja lo que pasa. Lo que no se publica (filtrado, bloqueado, ilegible o que no cumple el contrato) queda en `mensaje_recibido` con el motivo, y no frena a los mensajes que vienen detrás. Del mensaje pasan solo las cabeceras que lo identifican y fechan; los adjuntos no viajan | Nada se descarta en silencio. Los adjuntos piden una referencia a un almacenamiento cifrado que no está en el plan | Iteración 2 §5.4; vista de seguridad y datos |
| Para leer un buzón, `mail-ingest` primero lo saca de la cola (lo «reclama») en una transacción corta y recién después lo lee. Si la lectura falla, vuelve a la cola con una espera de `5 s × 2^n`, con tope de 15 min | Un aviso que llega mientras se lee el buzón lo vuelve a encolar en lugar de perderse, la cola no queda bloqueada mientras se habla con el proveedor, y un proveedor caído no recibe un reintento por vuelta. La espera es la de ADR-0024, sin la variación aleatoria | ADR-0004; ADR-0024 |
| El p99 de tokens por minuto de una réplica de `mail-ingest`, sobre el que `identity-access` bloquea a la réplica (3 veces ese valor), se configura con `TROTAMUNDOS_P99_TOKENS_POR_MINUTO` (20 por omisión) | `mail-ingest` pide un token por cada lectura de buzón: con muchos buzones (o en las pruebas de carga del paso 17) hay que calibrarlo para no bloquear una réplica sana, y el bloqueo no se levanta solo | ADR-0029 |
| `support-liaison` toma la agencia preferida de su copia local, que alimenta `PreferenciasActualizadas`. Como `preferences` quedó fuera del recorte, las pruebas y la demostración inyectan ese evento en el *broker* | Es lo que dice UC-7 («copia local de preferences»): cuando exista `preferences`, funciona sin cambios. Acordado con el grupo frente a construir un `preferences` mínimo o usar una agencia por omisión, que contradiría el `422` del contrato | Iteración 2 §5.7; UC-7 |
| La agencia es un complemento (`adaptador-agencia-simulada`), sin interfaz de estado: el viajero marca el caso resuelto. Si no acusa recibo, el caso queda `Abierto` y se reintenta con espera de `5 s × 2^n` (tope 15 min) durante 24 h; el viajero recibe igual el caso, con su estado real | Iteración 2 §5.7 prevé los dos casos de agencia; la espera y las 24 h son las de ADR-0024, sin cortacircuitos ni mamparo, que son del paso 10 | ADR-0006; ADR-0024 |
| `POST /casos` repetido con la misma `Idempotency-Key` devuelve el caso en su **estado actual** (por ejemplo, `Derivado` si la agencia acusó recibo después); `Caso.agencia` es el nombre de la agencia | El viajero ve qué pasó con su pedido, no una foto vieja. El nombre es lo que se le muestra | `support-liaison.yaml`; ADR-0014 |
| El caso no se copia al testigo transregional ni se purga a los 24 meses en el prototipo | La multirregión (paso 16) quedó fuera del recorte; la supresión por `usuario_id`, con la del resto del plano operacional | ADR-0018; ADR-0030 |
| El asistente suma el módulo `catalogo`, que lee los catálogos y formatea los mensajes, y `dialogo` no toca la base: recibe el estado de la sesión y devuelve el nuevo, que guarda `servicio` | La vista de módulos del asistente deja los catálogos como recurso sin lógica; alguien tiene que leerlos. Así `dialogo` se prueba sin base y las transacciones quedan en un solo lugar, como en el resto de los servicios | ADR-0037; vista de módulos del asistente |
| Los mensajes usan el subconjunto de ICU MessageFormat que necesita el catálogo: argumentos simples (`{titulo}`) y plurales (`{n, plural, one {…} other {…}}`), sin biblioteca externa. Los días de la semana salen del mismo catálogo | Alcanza para el español del prototipo sin sumar una dependencia; otro idioma con reglas de plural más ricas pediría la biblioteca ICU | ADR-0032; ADR-0037 |
| Fechas relativas del intérprete: «hoy», «mañana» y «pasado mañana» se cuentan en la zona del tramo. Un día de la semana, sobre un tramo, es el más cercano a la fecha del tramo sin caer antes de hoy (el vuelo del jueves 3/12 «pasado al sábado» queda el 5/12); sin tramo, el próximo después de hoy. Una fecha sin año es la próxima vez que llega. «De la mañana», «de la tarde» y «de la noche» son franjas del día, no fechas: «a las 9 de la noche» son las 21. Un tramo que vale todo el día (`precision: dia`) solo cambia de fecha | ADR-0037 pide fechas relativas en la zona del tramo pero no fija estos casos; el ejemplo de ADR-0038 cuenta el día desde la fecha del vuelo | ADR-0037; ADR-0038; ADR-0032 |
| El intérprete reconoce el código de una reserva solo como palabra entera (con o sin espacios o guiones: «AR 1402») y de 3 caracteres o más | Un código corto o contenido en otro («AR14» en «AR1402») elegía la reserva equivocada | ADR-0037 |
| El asistente propone derivar **una sola vez por disrupción**: al abrir el caso, la proyección guarda su `casoId`, y una nueva consulta sobre esa reserva lo recuerda en lugar de proponer otro caso. Pedir la agencia por otro motivo sigue funcionando | La `Idempotency-Key` de ADR-0039 se deriva de la acción, así que dos propuestas distintas abrían dos casos por la misma disrupción | ADR-0039; ADR-0040 |
| Un viaje en foco que ya no existe o no es del viajero deja de estar en foco en el turno siguiente | Si no, el asistente quedaba contestando «no encuentro ese viaje» y derivaba sobre un viaje inexistente | ADR-0040 |
| «Una consulta de estado nunca termina en derivación» se interpreta así: una consulta nunca abre un caso, y solo **propone** derivar cuando la reserva por la que se pregunta (el próximo tramo, o la nombrada por su código) tiene una disrupción de severidad alta. El caso se abre recién con la confirmación | Es lo que muestra la secuencia de derivación por disrupción («¿qué pasa con mi vuelo?») y el disparador de disrupción de ADR-0039 | ADR-0039; secuencias del asistente |
| Para confirmar una reserva o resolver un conflicto, si el mensaje no dice qué hacer («confirmala», «mantené el mío»), el asistente muestra los datos y pregunta, sin proponer una opción por omisión | Proponer una opción que el viajero no eligió lo llevaría a confirmar algo sin leerlo | ADR-0038 |
| Un «sí» escrito no confirma: la confirmación es siempre la `confirmacion` con el `accionId`, y el asistente vuelve a mostrar la propuesta. Un mensaje con `texto` y `confirmacion` se atiende como confirmación y el texto queda como el turno del viajero | ADR-0038 pide una confirmación explícita de ese `accionId` | ADR-0038; `virtual-assistant.yaml` |
| La confirmación **reclama** la acción pendiente en una transacción corta, antes de llamar a `itinerary` o a `support-liaison`: otra confirmación simultánea de la misma acción responde `409`. Si el otro servicio no responde, la acción vuelve a quedar pendiente hasta que venza | No se mantiene una transacción abierta durante una llamada a otro servicio, y una acción no se ejecuta dos veces | ADR-0038; ADR-0014 |
| Si el viajero tiene varios viajes y no dijo de cuál habla, el asistente le pregunta y le pide que repita el pedido eligiendo el viaje (`viajeId` del mensaje o el nombre del viaje); no guarda el pedido a medias | Mantiene la sesión en lo que fija ADR-0040 (viaje en foco, acción pendiente y contador) | ADR-0039; ADR-0040 |
| La proyección de disrupciones del asistente se purga con la ventana de la bandeja de entrada (14 días) | ADR-0040 dice que se purga con la bandeja de entrada | ADR-0040; ADR-0014 |
| El asistente responde siempre en español: sin `preferences` no conoce el idioma del viajero, y ADR-0040 dice que no consume `PreferenciasActualizadas` hasta que haga falta el idioma | El prototipo trae solo el catálogo en español (ADR-0037) | ADR-0037; ADR-0040 |
| `bff-web.yaml` 1.1.0 suma las tres rutas públicas del asistente (`/asistente/sesiones*`), la revalidación condicional (`If-None-Match` → `304`, `Cache-Control: private, no-cache`) en las lecturas de viajes y los errores `400`/`401` de las operaciones con sesión; `itinerary` devuelve `X-Version-Usuario` también en las respuestas `204` | El contrato del asistente (`virtual-assistant.yaml`) se expone a través del BFF (ADR-0005, ADR-0034), y `bff-web.yaml` declara `X-Version-Usuario` en todas las mutaciones de itinerario | ADR-0005; ADR-0018; ADR-0019; ADR-0027 (cambio compatible); ADR-0034 |
| `bff-web` calcula el `ETag` de `GET /panel` y `GET /viajes/{id}` como un *hash* `SHA-256` determinista del JSON canónico de la respuesta y responde `304 Not Modified` si coincide con `If-None-Match` | Cualquier cambio en `versionUsuario`, en una reserva, un conflicto o un viaje cambia el `ETag` de inmediato sin estados intermedios en el BFF | ADR-0019 (`ETag` y `Cache-Control: private, no-cache`) |
| Al crear una reserva nueva, la fusión de `itinerary` usa el registro de tipos del servicio (el alta manual y la ingesta lo pasan), en lugar del registro por omisión | La prueba de QA-15 con un tipo que el código no conoce mostró que el registro inyectado se perdía. En producción no cambia nada, porque los dos se leen de la misma carpeta de contratos | ADR-0011; QA-15 |
| Los catálogos del asistente (`patrones.yaml` y `mensajes.yaml`) cuentan como recursos de presentación de un tipo, igual que las etiquetas de los clientes (elemento 2 de la [guía de extensión](../docs/02-proceso-add/iteracion-4/guias-de-extension.md)). Un tipo que no está en ellos se encuentra por su código y se nombra «reserva»; para reconocerlo por su nombre («mi barco») se agrega ahí | El asistente es posterior a la guía de la iteración 4. Así QA-15 sigue en ≤ 2 elementos tocados y 0 servicios de dominio | QA-15; ADR-0032; ADR-0037 |
| Un tipo de segmento nuevo se incorpora con un despliegue: cada servicio lee los descriptores de `contratos/` una vez, al arrancar | QA-15 plantea la incorporación «para el siguiente *release*»; recargar descriptores en caliente no es un requisito | QA-15; ADR-0011 |
| Los adaptadores HTTP del asistente aceptan un cliente `httpx` opcional | La prueba de QA-15 conecta el asistente con la API real de `itinerary` dentro del mismo proceso, ejercitando los mismos adaptadores que en los contenedores | QA-15; ADR-0038 |
| Los escenarios de QA-01 y QA-04 corren **contra los contenedores** (`make servicios-arriba`), con cada servicio en su proceso y el *broker* real: el viajero inicia sesión en `identity-access`, conecta un buzón por reenvío, recibe correos y avisos de la aerolínea, y el panel se lee en `bff-web`. No se inyectan eventos a mano. Sin los contenedores se saltean; el trabajo `servicios` de la integración continua los corre con `TROTAMUNDOS_EXIGIR_CONTENEDORES=1` | La integración continua ya levantaba todo pero no recorría caminos entre servicios (AGENTS.md). Así los ASR quedan probados de punta a punta en cada cambio | ADR-0017; QA-01; QA-04 |
| QA-01 mide cada tramo con las marcas de tiempo de las *outbox* y bandejas de entrada (ADR-0014) y lo compara con el presupuesto de frescura: recepción y despacho ≤ 60 s (encolado 15 s más descarga 45 s), extracción, normalización y deduplicación ≤ 45 s, y persistencia hasta el cliente ≤ 75 s. El p95 y el p99 salen de una muestra de 3 correos y 10 avisos del proveedor | El análisis inicial reparte los 5 minutos por tramo; medir solo el total no mostraría dónde se gasta | QA-01; ADR-0014 |
| QA-04 se prueba a escala de prototipo: 4 viajeros, 100 reservas que llegan por correo dos veces cada una y 200 avisos del proveedor (uno nuevo y uno viejo por reserva, en desorden), con 6 lectores del panel sin pausa | Lo que se demuestra es el mecanismo (sin pérdidas, sin duplicados, el aviso viejo no pisa al nuevo, el panel responde), no las cifras de producción (ADR-0034) | QA-04; ADR-0013; ADR-0014; ADR-0034 |
| La sesión OIDC de las operaciones públicas se verifica en `comun/sesion.py` (`HS256` con `TROTAMUNDOS_JWT_SECRETO`, compartido por `.env`); la usan `identity-access` y la API de filtros de `mail-ingest` | El token lo emite `identity-access`. En producción cada servicio verificaría con la clave pública de `identity-access` | ADR-0007 |
| El alias de reenvío lo genera `identity-access` al conectar el buzón y lo devuelve en `POST /buzones`; `mail-ingest` lo recibe por `EstadoDeBuzonCambiado` | ADR-0035 dice que lo asigna `mail-ingest`, pero el contrato `identity-access.yaml` lo devuelve al conectar el buzón, y el contrato manda (AGENTS.md). Lo precisa [ADR-0041](../docs/03-adr/ADR-0041-alias-de-reenvio-generado-por-identity-access.md) | ADR-0035; ADR-0041; `identity-access.yaml` |
| AsyncAPI 1.4.0: `EstadoDeBuzonCambiado` suma `via`, `proveedor`, `aliasReenvio` y `correoDelTitular`, que viajan solo cuando el buzón pasa a `Activo` | `mail-ingest` necesita saber cómo atender cada buzón y, para un reenvío, con qué correo comparar el remitente (ADR-0035). Acordado con el grupo frente a un endpoint interno en `identity-access`: un solo mecanismo y sin llamadas sincrónicas. En los demás cambios alcanza con `buzonId`, así el correo no viaja de más | ADR-0004; ADR-0027 (cambio compatible); ADR-0035 |
| `DELETE /privacidad/cuenta` publica `EstadoDeBuzonCambiado` (`desconectadoPorUsuario`) por cada buzón que revoca, igual que `DELETE /buzones/{id}` | `mail-ingest` consume ese evento para dejar de leer los buzones | ADR-0030; `eventos-de-dominio.yaml` |
| `ProveedorOidcSimulado` mapea `codigo` (`oidc:<correo>:<region>`) a `usuario_identidad` y firma sesiones JWT (`HS256`) y vales ABAC (`TTL 60 s`) con `TROTAMUNDOS_JWT_SECRETO` y `TROTAMUNDOS_VALE_SECRETO` (al azar si no se fijan). `ConsultorDeDesignados` y `ConsultorDeRecursos` arrancan *fail-closed* hasta conectar `sharing` | Permite probar sesiones, OTP de invitados y vales ABAC en el paso 7 sin depender de un IdP externo ni de `sharing` (paso 13) | ADR-0007; ADR-0028; ADR-0036 |
| En `identity-access`, `POST /privacidad/exportaciones` guarda el paquete firmado (identidad, buzones y auditoría del servicio) en `exportacion_privacidad`, y `DELETE /privacidad/cuenta` ejecuta la fase 1 local (destrucción de `DEK_u`, secretos, buzones, exportaciones, identidad R1 y `mapa_seudonimo_usuario`) y publica `CuentaSuprimida` en `P3` (`SobreSinUsuario`) | La purga coordinada sobre `itinerary`/`sharing`/`preferences` y la fase 2 en `analytics-store` llegan con `event-pipeline` en el paso 14 | ADR-0030 (`QA-14`); `eventos-de-dominio.yaml` |
| `registro_auditoria` de `identity-access` es una sola cadena `SHA-256`: cada escritura toma un candado de la base para encadenarse a la anterior, así que las escrituras auditadas del servicio se hacen de a una | Alcanza para el prototipo. Con la carga de QA-04 haría falta una cadena por partición (por ejemplo, por *bucket* de usuario), que es una decisión a tomar si se mide un cuello de botella | ADR-0030; QA-04 |
| `identity-access` corre su trabajo periódico cada `TROTAMUNDOS_INTERVALO_TAREAS` segundos: purga la bandeja de entrada, las claves de idempotencia y los códigos de invitado vencidos | El mismo mecanismo que `itinerary` | ADR-0014; ADR-0028 |
| Paso 9: un extractor puro de plantilla sintética `Reserva aérea simulada v1`, del remitente `reservas@aerolinea.example`; campos `Localizador`, `Aerolinea`, `Numero`, `Origen`, `Destino`, `Salida`, `Llegada`, `Emitido` | Plantilla determinista para el corpus sintético. Aeropuertos AEP/EZE/MDZ/MAD y localizador de seis caracteres alfanuméricos; la fecha de fuente viene de `Emitido`, no de la recepción | ADR-0006, ADR-0015; `plugins/extractor.yaml` |
| Paso 9: confianza por campo 0,99 con rótulo exacto; `Localizador tentativo` 0,75 y `Localizador dudoso` 0,50; faltantes 0, sin completar valores | Permite demostrar las tres bandas con datos sintéticos. El anfitrión calcula el mínimo de todos los campos obligatorios y valida la estructura antes de puntuar. Los umbrales siguen siendo 0,90/0,60 | ADR-0015, ADR-0035; corpus en `tests/booking_extraction/corpus/` |
| Paso 9: disyuntor local configurable por constructor (`Calidad`): ventana de 20 resultados, mínimo 20, más de 50 % de bandas bajas; queda en solo confirmación hasta reiniciar la réplica | El corpus degradado demuestra la apertura con estos parámetros iniciales. Si un remitente registrado cambia su plantilla, sus mensajes desconocidos también cuentan como banda baja. Contadores por banda y huella en memoria, sin correos ni datos personales; no se presenta como monitoreo de producción | ADR-0015, ADR-0035 |
| Paso 9: `idDeFuente` es SHA-256 de la pareja buzón/mensaje serializada; deduplicación por evento y pareja buzón/mensaje, con retención de 14 días | La inbox, la marca de mensaje y las salidas se confirman juntas; un rollback también revierte los contadores locales. No se guarda el cuerpo en `booking-extraction`, ni en rechazos o logs del consumidor | ADR-0014, ADR-0035 |
| Paso 9: huella de la estructura disponible en `MensajeNormalizado` (partes texto/HTML, etiquetas sin atributos ni texto, clases MIME y nombres de cabeceras normalizados); métricas solo por dominio y hash | El normalizador del paso 8 no entrega la jerarquía MIME original. La garantía de no persistir cuerpos corresponde al nuevo servicio: la outbox de `mail-ingest` y el broker conservan su retención existente | ADR-0035; `MensajeNormalizado` |
| Paso 10: `provider-sync` mantiene el índice de `seguimiento` (`reserva_seguida`) consumiendo `ReservaActualizada` y `ReservaCancelada` del *broker* (AsyncAPI 1.5.1), además de permitir registrar seguimientos explícitos | Permite resolver cada `referencia` del proveedor a `(usuarioId, reservaId)` y conocer el inicio del próximo tramo para elegir el carril (`P1` si está `EnCurso` o sale en `< 48 h`, `P2` en otro caso) y expandir `DisrupcionDetectada` a todos los viajeros afectados | Iteración 2 §5.5 y §5.10 (ajuste 4); ADR-0020; `eventos-de-dominio.yaml` 1.5.1 |
| Paso 10: `AdaptadorAerolineaSimulada` (`adaptador-aerolinea-simulada` v1.0.0) se registra en `catalogo_adaptadores.yaml` para el emisor `aerolinea:AR`, traduce notificaciones NDC simuladas en `application/json` y `application/xml` firmadas con `TROTAMUNDOS_SECRETO_WEBHOOK_PROVEEDOR` (HMAC-SHA256 en `X-Firma`), admite `sondear` y `obtenerReserva`, y detecta disrupciones correlacionadas por `idDeCausa` | Cubre `provider-sync-webhooks.yaml`, el contrato `plugins/adaptador.yaml` y la suite de conformidad con grabaciones (ADR-0017) sin depender de un proveedor externo real | ADR-0006; ADR-0017; ADR-0027; `plugins/adaptador.yaml`; `provider-sync-webhooks.yaml` |
| Paso 14: `event-pipeline` ejecuta directamente `contratos/analitica/modelo-dimensional.sql` en el esquema separado `analytics_store`, retiene los eventos en `evento_crudo` reemplazando `usuarioId` por un `seudonimo_analitico` determinista (`SHA-256`) y pobla `dim_tipo_segmento` desde `RegistroDeTipos` | El contrato SQL es la única fuente del esquema en estrella, ninguna columna analítica guarda `usuario_id` operacional, `reconstruir()` regenera los hechos desde `evento_crudo` y `CuentaSuprimida` excluye al instante al usuario de `v_hecho_cambio_reserva` y `v_hecho_viaje` | ADR-0003; ADR-0016; ADR-0030; `contratos/analitica/modelo-dimensional.sql`; QA-09; QA-15 |

## Cómo correrlo

Requisitos: Python 3.12, Docker con Compose.

```bash
cd prototipo
make instalar        # crea .venv e instala dependencias
make infra-arriba    # levanta PostgreSQL (puerto 55432) y el broker (puerto 19092)
make pruebas         # corre las pruebas (las de PostgreSQL se saltean si no está arriba)
make servicios-arriba # además construye la imagen y levanta los servicios
                      # con los servicios arriba, make pruebas también recorre los escenarios
                      # de QA-01 y QA-04 (tests/escenarios); sin ellos, se saltean
make infra-abajo
```

**Integración continua.** En cada cambio de `prototipo/` o `contratos/`,
[`.github/workflows/pruebas.yml`](../.github/workflows/pruebas.yml) levanta PostgreSQL y Redpanda
con el mismo `docker-compose.yml` y corre todas las pruebas. Ahí se define
`TROTAMUNDOS_EXIGIR_INFRA=1`: sin base o sin broker, las pruebas fallan en lugar de saltearse. En
paralelo, el trabajo `servicios` construye la imagen y levanta todo el compose (`make
servicios-arriba`): si algún servicio no arranca, falla aunque sus pruebas estén en verde, y muestra
los registros de los contenedores.

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
| `bff-web` | 18108 | Operaciones públicas para `app-web` ([`bff-web.yaml`](../contratos/openapi/bff-web.yaml)): panel y viajes con `ETag`/`304` y `Cache-Control`, comandos con `X-Version-Usuario`, catálogo público de tipos y conversaciones con `virtual-assistant` |
| `provider-sync` | 18109 | Webhooks de proveedores de viaje (`/webhooks/proveedor` de [`provider-sync-webhooks.yaml`](../contratos/openapi/provider-sync-webhooks.yaml)) y sondeo periódico por adaptadores cargados como complementos ([`plugins/adaptador.yaml`](../contratos/plugins/adaptador.yaml)). Consume `ReservaActualizada` y `ReservaCancelada` para el seguimiento y publica `ReservaObservada` y `DisrupcionDetectada` |
| `event-pipeline` | 18110 | Consumidor de eventos de dominio hacia el esquema analítico separado `analytics_store` ([`analitica/modelo-dimensional.sql`](../contratos/analitica/modelo-dimensional.sql), ADR-0003, ADR-0016, ADR-0030). Retiene eventos crudos con seudónimo y materializa dimensiones, hechos y `lista_supresion_analitica` |

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
`escritura`.

## Estado de las decisiones de arquitectura

Qué ADR implementa el prototipo hasta ahora, cuál se implementa en un paso posterior y cuál queda
fuera del alcance que fija [ADR-0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md)
(una tajada vertical por los 5 ASR, no el sistema completo). Se actualiza al cerrar cada paso.

Los pasos 13 (`sharing`) y 16 (multirregión) quedaron fuera del [recorte para la
entrega](#recorte-para-la-entrega): las filas que los nombran describen lo que se haría si se
completa el 100 % del contenido. Lo que al congelar quede sin construir se lista en [Diseñado y no
construido](#diseñado-y-no-construido).

✅ implementado · 🟨 parcial · ⏳ en un paso posterior · ➖ fuera de alcance

| ADR | Estado | Dónde está o cuándo llega |
|---|---|---|
| [0001](../docs/03-adr/ADR-0001-estilo-arquitectonico.md) Microservicios orientados a eventos | ✅ | Todos los servicios del recorte (`itinerary`, `identity-access`, `mail-ingest`, `booking-extraction`, `provider-sync`, `bff-web`, `support-liaison`, `virtual-assistant`, `event-pipeline`) y lo compartido en `comun`; ningún servicio importa a otro (prueba de arquitectura) |
| [0002](../docs/03-adr/ADR-0002-despliegue-multirregion.md) Activo-activo en tres regiones | ⏳ | Paso 16, como multirregión simulada: dos regiones con región primaria por usuario (ver ADR-0018). Las tres regiones reales ➖ |
| [0003](../docs/03-adr/ADR-0003-separacion-planos.md) Plano operacional y analítico separados | ✅ | Paso 14 (`QA-09`): `event-pipeline` escribe únicamente en el esquema separado `analytics_store`, sin llamadas HTTP ni dependencias hacia servicios operacionales (regla R6 probada) y con prueba de aislamiento concurrente frente a `GET /panel` |
| [0004](../docs/03-adr/ADR-0004-obtencion-de-correo.md) Correo por *push* con reconciliación | 🟨 | Paso 8: suscripciones con renovación y detección de caídas, aviso firmado, reconciliación escalonada por `buzon_id` y los dos caminos convergiendo en una cola, con la misma entrega publicada una sola vez (probado). Los intervalos son los «en reposo» de ADR-0024: el ajuste por viaje y los cortacircuitos/cuotas quedan fuera del recorte (ver «Para completar el 100 %») |
| [0005](../docs/03-adr/ADR-0005-capa-de-clientes-bff.md) Un BFF por tipo de cliente | 🟨 | Paso 11: `bff-web` sin lógica de dominio (regla R4 probada), componiendo `itinerary-lectura`, `itinerary-escritura` y `virtual-assistant` en una sola ida y vuelta para el panel. `bff-mobile` queda fuera del recorte |
| [0006](../docs/03-adr/ADR-0006-capa-de-anticorrupcion.md) Capa de anticorrupción con complementos | ✅ | Complementos de proveedor de correo (paso 8), extractor puro por manifiesto y corpus (paso 9), adaptadores de proveedor de viaje por configuración con `QA-10` probado (paso 10) y adaptador de agencia (paso 12), cada uno detrás de su interfaz y sin filtrar tipos externos (reglas R2 y R3) |
| [0007](../docs/03-adr/ADR-0007-identidad-y-comparticion.md) OIDC, delegación OAuth y designados | 🟨 | Sesiones OIDC y ciclo de vida de buzones en `identity-access` (paso 7). Designados y compartición, paso 13 |
| [0008](../docs/03-adr/ADR-0008-alcance-disponibilidad.md) Alcance y medición de la disponibilidad | ➖ | Medir disponibilidad real no tiene sentido en una notebook; lo crítico se ejercita con QA-05 |
| [0009](../docs/03-adr/ADR-0009-contratos-spec-driven.md) Contratos como artefactos de primera clase | 🟨 | Todo cuerpo, respuesta y evento se valida contra `contratos/` en ejecución, y la integración continua corre todas las pruebas en cada cambio. La detección de cambios incompatibles entre versiones, paso 17 |
| [0010](../docs/03-adr/ADR-0010-modelo-canonico-reserva-segmento-viaje.md) Agregados `Reserva` y `Viaje` | ✅ | Pasos 3 a 5: ninguna transacción escribe los dos (probado) y se coordinan por eventos internos |
| [0011](../docs/03-adr/ADR-0011-extensibilidad-del-tipo-de-segmento.md) Registro de tipos de segmento | ✅ | Pasos 2 a 5 (regla I4 probada). Paso 15: un viaje con tren recorre `itinerary` y el asistente con solo su descriptor, y un tipo que el código no conoce (`barco`) hace lo mismo agregando su descriptor (QA-15, [guía de extensión](../docs/02-proceso-add/iteracion-4/guias-de-extension.md)) |
| [0012](../docs/03-adr/ADR-0012-persistencia-del-plano-operacional.md) Persistencia relacional por `usuario_id` | ✅ | Las diez tablas de §5.8, con las unicidades impuestas por la base y la *outbox*. La compactación, ver ADR-0023 |
| [0013](../docs/03-adr/ADR-0013-deduplicacion-y-conflictos.md) Identidad, precedencia y conflictos | ✅ | Paso 3: una prueba por regla, más pruebas de propiedades. Paso 14: `ConflictoDeFuentesDetectado` se retiene en `evento_crudo` y actualiza el contador `conflictos` en `hecho_viaje` |
| [0014](../docs/03-adr/ADR-0014-idempotencia-de-la-ingesta.md) Bandeja de entrada y fusión determinista | ✅ | Pasos 3 a 6: bandeja de entrada, `Idempotency-Key`, entrega repetida sin doble efecto y reversión 10:00 → 10:30 → 10:00 (probados). La de `mail-ingest`, paso 8 |
| [0015](../docs/03-adr/ADR-0015-politica-de-confianza-de-extraccion.md) Tres bandas de confianza | 🟨 | Paso 9: extractor, validación estructural, tres bandas, corpus sintético y disyuntor por bandas bajas; `itinerary` conserva `PorConfirmar`. Modo sombra, correcciones y monitoreo completo quedan fuera del recorte |
| [0016](../docs/03-adr/ADR-0016-modelo-dimensional-analitico.md) Esquema en estrella desde eventos | 🟨 | Paso 14: capa de aterrizaje `evento_crudo` sin `usuario_id`, instalación de `contratos/analitica/modelo-dimensional.sql`, alta automática de tipos en `dim_tipo_segmento` (`QA-15`), `hecho_cambio_reserva`, `hecho_viaje` y reconstrucción desde eventos crudos. El historial SCD tipo 2 de `dim_proveedor` queda fuera del recorte |
| [0017](../docs/03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md) Pruebas derivadas de la especificación | 🟨 | Propiedades de la fusión y validación contra contratos, en la integración continua (`.github/workflows/pruebas.yml`). Conformidad y corpus del extractor (paso 9); suite de conformidad y grabaciones de adaptadores de proveedor con prueba de `QA-10` (paso 10). Escenarios de QA-01 y QA-04 de punta a punta contra los contenedores, en el trabajo `servicios` (paso 17). Schemathesis y compatibilidad, en «Para completar el 100 %» |
| [0018](../docs/03-adr/ADR-0018-consistencia-datos-multirregion.md) Región primaria, testigo y lectura causal | 🟨 | `versionUsuario` y escrituras serializadas por usuario. Región primaria, testigo transregional síncrono para los comandos manuales y conmutación, paso 16 (QA-05) |
| [0019](../docs/03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) Caché multinivel y arranque móvil | 🟨 | El panel se lee en un acceso (`proyeccion_panel`) y `bff-web` aplica `Cache-Control: private, no-cache` con `ETag` / `304 Not Modified` en datos del usuario y `Cache-Control: public, max-age=300, stale-while-revalidate=3600` en `GET /tipos-de-segmento` (paso 11). El clúster regional en memoria y `bff-mobile` quedan fuera del recorte |
| [0020](../docs/03-adr/ADR-0020-contrapresion-y-sobrecarga.md) Contrapresión, carriles y degradación | 🟨 | Carriles P1/P2/P3 (paso 6). Plazo propagado y límite de tasa quedan en «Para completar el 100 %» (recorte del paso 11); modos de degradación, paso 17. Paso 17: una ráfaga de correo y de avisos del proveedor sin pérdidas, con el panel respondiendo (QA-04, a escala de prototipo) |
| [0021](../docs/03-adr/ADR-0021-estrategia-autoescalado.md) Autoescalado y lectura/escritura separadas | 🟨 | `itinerary-lectura` e `itinerary-escritura` como modos del mismo código (`TROTAMUNDOS_MODO`). El autoescalado es de la plataforma de producción ➖ |
| [0022](../docs/03-adr/ADR-0022-despliegue-progresivo-y-reversion.md) Entrega canaria y *expand/contract* | ➖ | Requiere varias regiones y tráfico real |
| [0023](../docs/03-adr/ADR-0023-particionamiento-y-crecimiento.md) Particionamiento, compactación y archivo frío | 🟨 | La clave de partición `usuario_id` está en toda tabla y en el *broker*. Los 64 *buckets*, la compactación y el archivo frío ➖ (volumen de producción); la consolidación ya es indiferente a la compactación (probado) |
| [0024](../docs/03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md) Cortacircuitos, cola persistente y cuotas | 🟨 | Espera de `5 s × 2^n` con tope de 15 min en la cola de `mail-ingest` (paso 8) y en la derivación a la agencia durante 24 h (paso 12). Cortacircuitos, mamparos y cuotas de `provider-sync` quedan fuera del recorte del paso 10 (ver «Para completar el 100 %») |
| [0025](../docs/03-adr/ADR-0025-observabilidad-sli-slo-presupuesto-error.md) Observabilidad y presupuesto de error | 🟨 | `traceparent` e `idDeCorrelacion` se propagan en HTTP y eventos. OpenTelemetry y SLO ➖: no están en el plan |
| [0026](../docs/03-adr/ADR-0026-modelo-costo-y-camino-escalonado.md) Modelo de costo | ➖ | Es una decisión de operación, no de código |
| [0027](../docs/03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) Evolución compatible de contratos | 🟨 | Los contratos evolucionan con SemVer y cambios compatibles (`itinerary.yaml` 1.1.0, `bff-web.yaml` 1.1.0, `identity-access.yaml` 1.2.0, `mail-ingest-filtros.yaml` 1.1.0, `support-liaison.yaml` 1.1.0, `virtual-assistant.yaml` 1.0.0, AsyncAPI 1.5.1), el cargador de `booking-extraction` y `provider-sync` verifica `apiContrato` (`1.x`) y `version` SemVer en el arranque, y la API pública sirve `application/vnd.trotamundos.v1+json` (paso 11) |
| [0028](../docs/03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md) ABAC, vales firmados y designados | 🟨 | El mismo 404 para «no existe» y «no es tuyo» (incluso en `bff-web`, paso 11); motor ABAC, vale JWS de 60 s y OTP de invitados en `identity-access` (paso 7). Verificación del vale interno en `itinerary` y `sharing`, fuera del recorte (paso 13) |
| [0029](../docs/03-adr/ADR-0029-cifrado-custodia-y-rotacion-de-claves.md) Cifrado por sobres y custodia | ✅ | Paso 7 (`QA-13`): `KEK_region`/`DEK_u` con `AES-256-GCM`, regla `R5-estricto` probada, rotación sin corte, tokens efímeros ≤ 15 min, detector de anomalías de 60 s y revocación regional en bloque |
| [0030](../docs/03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md) Auditoría y supresión de datos | 🟨 | Los errores no filtran datos internos; bitácora encadenada `SHA-256`, exportación y fase 1 local con `CuentaSuprimida` en `identity-access` (paso 7). En el paso 14, `event-pipeline` consume `CuentaSuprimida` e inserta el seudónimo en `lista_supresion_analitica`, excluyéndolo al instante en `v_hecho_cambio_reserva` y `v_hecho_viaje`. El trabajo quincenal de compactación Parquet y la purga coordinada del resto del plano operacional quedan fuera del recorte |
| [0031](../docs/03-adr/ADR-0031-residencia-de-datos-por-region.md) Residencia de datos por región | ➖ | La multirregión del paso 16 se simula en una sola jurisdicción; las clases de residencia no aplican |
| [0032](../docs/03-adr/ADR-0032-internacionalizacion-y-localizacion.md) Internacionalización | 🟨 | Instantes en UTC con zona IANA aparte y dominio/BFF neutrales al idioma (`bff-web` paso 11, catálogos externalizados del asistente en paso 19). El formateo local en `app-web`, paso 20 |
| [0033](../docs/03-adr/ADR-0033-capacidades-nativas-gps-y-degradacion.md) GPS en el móvil | ➖ | No hay cliente móvil nativo en el prototipo |
| [0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) Módulo avanzado y recorte del prototipo | 🟨 | El recorte guía este plan. La Opción B, diseñada en la [iteración 5](../docs/02-proceso-add/iteracion-5/README.md) (paso 18) y construida en `virtual-assistant` (paso 19) sin interfaces nuevas en el núcleo (CON-06); ADR-0040 precisa su punto sobre `CuentaSuprimida` |
| [0035](../docs/03-adr/ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) Buzones sin OAuth y formatos desconocidos | 🟨 | Alias de reenvío e `imapDelegado` con credencial delegada cifrada en `identity-access` (paso 7). Receptor de reenvío con DKIM/SPF/ARC y titular verificados, con rechazos auditados (paso 8). Paso 9: formato desconocido, banda baja o estructura inválida emiten `ExtraccionNoReconocida`, con huella sin contenido y sin reserva; aviso/formulario de usuario y telemetría externa quedan fuera del recorte |
| [0036](../docs/03-adr/ADR-0036-tecnologia-del-prototipo.md) Tecnología del prototipo | ✅ | Python 3.12, FastAPI, PostgreSQL, Redpanda y Docker Compose. Schemathesis, paso 17 |
| [0037](../docs/03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md) Intérprete de intenciones intercambiable | 🟨 | Paso 19: puerto `InterpreteDeIntenciones` con reglas, umbral 0,6 y catálogos de patrones y mensajes en español. El adaptador de modelo de lenguaje con redacción de datos personales queda diseñado y no construido |
| [0038](../docs/03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md) Consultas y corrección confirmada | ✅ | Paso 19: consultas, corrección en dos pasos con vencimiento de 10 min y `409` releído, problemas menores y cambios ante el proveedor derivados |
| [0039](../docs/03-adr/ADR-0039-politica-de-derivacion-a-la-agencia.md) Derivación a la agencia | ✅ | Los cuatro disparadores, la síntesis y el caso idempotente por la acción (paso 19), sobre `POST /casos` (paso 12) |
| [0040](../docs/03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) Sesión conversacional y privacidad | 🟨 | Paso 19: sesiones por `usuario_id`, retención de 30 días y `DisrupcionDetectada` con bandeja de entrada. La supresión de fase 1 por `usuario_id`, con la del resto del plano operacional (paso 14); la degradación ante `Disrupción masiva`, diseñada y no construida |
| [0041](../docs/03-adr/ADR-0041-alias-de-reenvio-generado-por-identity-access.md) Alias de reenvío generado por `identity-access` | ✅ | Pasos 7 (alta del buzón) y 8 (`mail-ingest` lo recibe por `EstadoDeBuzonCambiado`) |

Además de los ADR: `preferences` se construye como servicio mínimo en el paso 12, porque su evento
`PreferenciasActualizadas` lo consumen `itinerary` (la gracia de archivado de cada usuario) y la
Opción B (ADR-0034).

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
| 9 | `booking-extraction`: extractores, bandas de confianza, formato desconocido | QA-11, ADR-0015 | Sí o sí | ✅ recorte | Juan Pardo |
| 10 | `provider-sync`: adaptador simulado, cortacircuitos, disrupciones | QA-10, ADR-0024 | Si sobra (reducido) | ✅ reducido: adaptador simulado, `ReservaObservada` y `DisrupcionDetectada` | Ivo Iriarte |
| 11 | BFF y `api-gateway`: panel, límite de tasa, plazos | QA-02, ADR-0020 | Debería (reducido) | ✅ reducido: solo `bff-web` | Ivo Iriarte |
| 12 | `notification`, `support-liaison` y `preferences` mínimo | UC-5, UC-7, ADR-0034 | Sí o sí (reducido) | ✅ reducido: solo `support-liaison` | Francisco Lozano |
| 13 | `sharing`: compartición y `ResumenPublicable` | QA-12, ADR-0028 | Completar al 100 % | ⬜ |  |
| 14 | `event-pipeline` y plano analítico | QA-09, ADR-0016 | Si sobra (reducido) | ✅ reducido: consumidor a esquema analítico aparte y aislamiento QA-09 | Ivo Iriarte |
| 15 | Tipo `tren` sin tocar código de dominio | QA-15 | Debería | ✅ | Francisco Lozano |
| 16 | Multirregión simulada: región primaria por usuario, testigo transregional y conmutación | QA-05, ADR-0018 | Completar al 100 % | ⬜ |  |
| 17 | Pruebas de contrato y de escenarios (QA-01, QA-04, QA-05) | ADR-0017 | Debería (reducido) | ✅ reducido: escenarios de QA-01 y QA-04 contra los contenedores | Francisco Lozano |
| 18 | Iteración 5 de ADD: diseño de la Opción B (ADRs y contrato) | CON-06 | Sí o sí | ✅ | Francisco Lozano |
| 19 | `virtual-assistant`: intenciones y derivación a la agencia | RF-B1, RF-B2 | Sí o sí | ✅ | Francisco Lozano |
| 20 | Interfaz web mínima de demostración | RF-09 | Debería (reducido) | ⬜ |  |
| 21 | Matriz código ↔ ADR, guion de demostración y README final | QA-16 | Sí o sí | ⬜ |  |

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
el **domingo 22 a las 23:00**, 24 h antes de la entrega: desde ahí no se empieza ningún paso nuevo,
aunque sobren horas. El lunes 23, hasta la entrega, queda para el cierre (paso 21) y el ensayo de la
defensa. Lo que al congelar no esté terminado se registra abajo como diseñado y no construido.

La iteración 5 (paso 18) va primero: sin sus ADR y su contrato, el asistente (paso 19) no puede
empezar sin inventar decisiones.

### Para completar el 100 % del contenido

Si la tajada queda terminada antes del congelamiento, se completa lo que el recorte dejó afuera,
en este orden (primero lo que termina algo ya empezado, después lo nuevo):

| Orden | Paso | Qué falta respecto de la versión reducida |
|---|---|---|
| 1 | 10 | Cortacircuitos, reintentos y cuotas (ADR-0024) |
| 2 | 14 | El modelo dimensional completo (ADR-0016) y la supresión en fase 2 (ADR-0030) |
| 3 | 12 | `notification` y `preferences` |
| 4 | 11 | `bff-mobile` y `api-gateway`, con límite de tasa y plazos (ADR-0020) |
| 5 | 17 | Pruebas de contrato con Schemathesis y el escenario de QA-05 |
| 6 | 13 | `sharing`: compartición con designados y en redes (ADR-0028) |
| 7 | 16 | Multirregión: región primaria, testigo transregional y conmutación (ADR-0018). Una versión mínima (dos bases y una conmutación) alcanza para sostener ASR-3 |
| 8 | 20 | Más pantallas que el panel y el chat |

### Matriz código ↔ ADR

Qué código implementa cada decisión y qué prueba lo verifica (QA-16). La completa quien cierra cada
paso; el paso 21 la revisa entera. Las rutas son relativas a `prototipo/`.

| Código | Implementa | Lo verifica |
|---|---|---|
| `trotamundos/comun/contratos.py`, `tipos_de_segmento.py` | ADR-0009, ADR-0011, ADR-0027; todo `contratos/` | `tests/test_contratos.py`, `tests/test_tipos_de_segmento.py` |
| `trotamundos/comun/modelo.py` | ADR-0010 (modelo canónico), ADR-0032 (instantes UTC con zona) | `tests/test_modelo.py` |
| `trotamundos/comun/eventos.py` | AsyncAPI (sobre y carga); ADR-0014, ADR-0025 | `tests/test_eventos.py` |
| `trotamundos/comun/persistencia.py` | ADR-0012 (*outbox*), ADR-0014 (bandeja de entrada, `Idempotency-Key`) | `tests/test_persistencia.py` |
| `trotamundos/comun/publicador.py`, `consumidor.py`, `carriles.py` | ADR-0012, ADR-0014, ADR-0020 (carriles P1–P3) | `tests/test_publicador.py`, `tests/test_consumidor.py`, `tests/test_carriles.py` |
| `trotamundos/comun/errores.py` | `Problema` de `comun.yaml`; ADR-0028 (mismo 404), ADR-0030 (sin datos internos) | `tests/test_errores.py` |
| `trotamundos/comun/sesion.py` | ADR-0007 (sesión OIDC) | `tests/mail_ingest/test_mail_ingest.py` (filtros) |
| Ningún servicio importa a otro; módulos según las vistas N2 | ADR-0001, vista de módulos N1 y N2, regla R5 | `tests/test_arquitectura.py` |
| `requirements.txt` igual a `pyproject.toml` | ADR-0036 | `tests/test_dependencias.py` |
| `servicios/itinerary/reservas/`, `fusion/` | ADR-0010, ADR-0013 (identidad, precedencia, conflictos), ADR-0015 (bandas) | `tests/itinerary/test_reservas.py`, `test_consolidacion.py`, `test_identidad.py`, `test_propiedades_fusion.py`, `test_repositorio.py` |
| `servicios/itinerary/viajes/` | ADR-0010, RF-07 (agrupación), RF-08 (ciclo de vida) | `tests/itinerary/test_viajes.py`, `test_repositorio_viajes.py` |
| `servicios/itinerary/gestion_manual.py` | RF-06, ADR-0013 (fijados) | `tests/itinerary/test_gestion_manual.py` |
| `servicios/itinerary/ingesta.py`, `publicacion.py`, `servicio.py` | ADR-0012, ADR-0014, ADR-0020, ADR-0018 (`versionUsuario`) | `tests/itinerary/test_servicio.py`, `test_publicacion.py`, `test_broker_itinerary.py` |
| `servicios/itinerary/api.py`, `proyeccion_panel.py` | `openapi/itinerary.yaml`; ADR-0021 (lectura y escritura) | `tests/itinerary/test_api.py`, `test_servicio.py` |
| `servicios/identity_access/custodia_boveda.py`, `consentimiento_buzones.py` | ADR-0029 (sobres, R5, rotación, revocación), ADR-0035, QA-13 | `tests/identity_access/test_boveda_y_auditoria.py`, `test_api_identity_access.py` |
| `servicios/identity_access/auditoria_y_revocacion.py` | ADR-0029 (detector), ADR-0030 (bitácora encadenada) | `tests/identity_access/test_boveda_y_auditoria.py` |
| `servicios/identity_access/autenticacion_oidc.py`, `motor_autorizacion_abac.py` | ADR-0007, ADR-0028 (OTP, ABAC, vales) | `tests/identity_access/test_api_identity_access.py` |
| `servicios/identity_access/servicio.py`, `api.py` | `openapi/identity-access.yaml`; ADR-0030 (exportación y supresión) | `tests/identity_access/test_api_identity_access.py`, `test_arranque_identity_access.py` |
| `servicios/mail_ingest/suscripciones.py`, `receptor.py`, `reconciliador.py`, `cola.py` | ADR-0004 (*push* y reconciliación), ADR-0020, ADR-0024 (espera) | `tests/mail_ingest/test_mail_ingest.py`, `test_modulos.py` |
| `servicios/mail_ingest/filtros.py`, `api.py` | RF-04; `openapi/mail-ingest-filtros.yaml`, `mail-ingest-webhooks.yaml` | `tests/mail_ingest/test_mail_ingest.py`, `test_modulos.py` |
| `servicios/mail_ingest/descargador.py`, `normalizador.py`, `deduplicador.py`, `publicacion.py` | ADR-0029 (token efímero), ADR-0014; AsyncAPI `MensajeDeViajeRecibido` | `tests/mail_ingest/test_mail_ingest.py`, `test_arranque_mail_ingest.py` |
| `servicios/mail_ingest/receptor_reenvio.py` | ADR-0035 (reenvío verificado) | `tests/mail_ingest/test_mail_ingest.py` |
| `servicios/support_liaison/casos.py`, `servicio.py`, `api.py` | `support-liaison.yaml`; RF-12, UC-7 (instantánea, estados, idempotencia, `422` sin agencia); ADR-0014; ADR-0024 (espera) | `tests/support_liaison/test_support_liaison.py`, `test_arranque_support_liaison.py` |
| `servicios/support_liaison/interfaz_de_agencia.py`, `complementos/` | ADR-0006 (agencia como complemento) | `tests/support_liaison/test_support_liaison.py` |
| `servicios/support_liaison/preferencias.py`, `instantanea.py`, `publicacion.py` | UC-7 (copia local de la agencia, viaje leído en nombre del viajero); ADR-0028 (mismo `404`); AsyncAPI `CasoDerivado` | `tests/support_liaison/test_support_liaison.py`, `test_arranque_support_liaison.py` |
| `servicios/virtual_assistant/interprete.py`, `catalogo.py`, `catalogos/es/` | ADR-0037 (puerto, reglas, umbral 0,6, fechas relativas en la zona del tramo, catálogos por idioma); ADR-0032 | `tests/virtual_assistant/test_interprete.py`, `tests/test_arquitectura.py` |
| `servicios/virtual_assistant/dialogo.py`, `acciones.py` | ADR-0038 (consultas, corrección en dos pasos, `409` releído, problemas menores); RF-B1; ADR-0013 (la corrección entra como edición manual) | `tests/virtual_assistant/test_virtual_assistant.py` |
| `servicios/virtual_assistant/derivacion.py` | ADR-0039 (cuatro disparadores, síntesis, idempotencia por la acción, `422`); RF-B2; `support-liaison.yaml` | `tests/virtual_assistant/test_virtual_assistant.py` |
| `servicios/virtual_assistant/sesiones.py`, `contexto.py`, `servicio.py`, `api.py` | ADR-0040 (sesión por `usuario_id`, `404` ajeno, retención, `DisrupcionDetectada` con bandeja de entrada); `virtual-assistant.yaml`; ADR-0014 | `tests/virtual_assistant/test_virtual_assistant.py`, `test_arranque_virtual_assistant.py` |
| `contratos/tipos-de-segmento/tren.v1.yaml` (el único artefacto propio del tren); `comun/tipos_de_segmento.py`; `servicios/itinerary/` y `servicios/virtual_assistant/` sin cambios por el tipo (la corrección de la fusión del paso 15 no es por el tipo: ver «Decisiones de implementación») | QA-15 (≤ 2 elementos tocados, 0 servicios de dominio; datos históricos consultables con una versión nueva del tipo); ADR-0011; ADR-0027 | `tests/escenarios/test_qa15_nuevo_transporte.py`, `tests/test_arquitectura.py` (ningún módulo nombra un tipo) |
| `servicios/booking_extraction/complementos/`, `interfaz_de_extractor.py`, `registro_de_extractores.py` | ADR-0006, ADR-0011, ADR-0017, ADR-0027; `plugins/extractor.yaml`; un extractor puro cargado por manifiesto | `tests/booking_extraction/test_extraccion.py`, `tests/test_arquitectura.py` |
| `servicios/booking_extraction/validador_canonico.py`, `evaluador_de_confianza.py`, `observabilidad_de_calidad.py` | ADR-0015, ADR-0035; mínimo de confianza, bandas, disyuntor y huella sin contenido (QA-11) | `tests/booking_extraction/test_extraccion.py` (corpus y degradados) |
| `servicios/booking_extraction/servicio.py`, `publicacion.py`; `comun/consumidor.py`; `docker-compose.yml` | ADR-0012, ADR-0014, ADR-0020, ADR-0035; AsyncAPI `MensajeDeViajeRecibido`, `ReservaExtraida`, `ExtraccionNoReconocida` | `tests/booking_extraction/test_servicio.py`, `test_arranque_booking_extraction.py`, `tests/test_consumidor.py`; humo `tests/booking_extraction/humo_contenedores.py` (QA-01/QA-11) |
| `comun/catalogo_extractores.py`, `catalogo_extractores.yaml`; `servicios/mail_ingest/servicio.py` | RF-04, ADR-0006; catálogo del manifiesto, sin importar otro servicio | `tests/mail_ingest/test_mail_ingest.py` (catálogo y bloqueo antes de descargar) |
| `servicios/bff_web/clientes.py`, `api.py`, `servicio.py` | `bff-web.yaml` 1.1.0; ADR-0005 (composición sin lógica de dominio, regla R4); ADR-0018 (`X-Min-Version`, `X-Version-Usuario`); ADR-0019 (`ETag`, `304 Not Modified`, `Cache-Control` privado y público); ADR-0027 (`application/vnd.trotamundos.v1+json`); ADR-0028 (`404` opaco); ADR-0034 (asistente expuesto por el BFF) | `tests/bff_web/test_bff_web.py`, `test_arranque_bff_web.py`, `tests/test_arquitectura.py` |
| `servicios/provider_sync/interfaz_de_adaptador.py`, `complementos/aerolinea_simulada.py`, `catalogo_adaptadores.yaml`, `registro_de_adaptadores.py` | ADR-0006, ADR-0011, ADR-0017, ADR-0027; `plugins/adaptador.yaml`; adaptador NDC simulado cargado por configuración (JSON y XML) y suite de conformidad con grabaciones (QA-10: 0 elementos existentes modificados) | `tests/provider_sync/test_conformidad_adaptadores.py`, `tests/test_arquitectura.py` |
| `servicios/provider_sync/seguimiento.py`, `receptor_de_notificaciones.py`, `programador.py`, `detector_de_disrupciones.py`, `publicacion.py`, `api.py`, `servicio.py`; `docker-compose.yml` | ADR-0012, ADR-0014, ADR-0020; `provider-sync-webhooks.yaml` (`POST /webhooks/proveedor` con `X-Firma` HMAC-SHA256); AsyncAPI 1.5.1 (`ReservaObservada` en `P1`/`P2`, `DisrupcionDetectada` en `P1` expandida con `seguimiento` y correlacionada por `idDeCausa`, consumo de `ReservaActualizada`/`ReservaCancelada`) | `tests/provider_sync/test_provider_sync.py`, `test_arranque_provider_sync.py`, `tests/test_arquitectura.py` |
| `servicios/event_pipeline/aterrizaje.py`, `modelo_dimensional.py`, `servicio.py`; `contratos/analitica/modelo-dimensional.sql` | ADR-0003 (separación de planos y regla R6, QA-09); ADR-0016 (capa de aterrizaje `evento_crudo`, esquema en estrella, reconstrucción y alta automática en `dim_tipo_segmento` para QA-15); ADR-0030 (`seudonimo_analitico` sin PII y exclusión inmediata en `lista_supresion_analitica` / vistas filtradas ante `CuentaSuprimida`) | `tests/event_pipeline/test_event_pipeline.py`, `test_arranque_event_pipeline.py`, `tests/test_arquitectura.py` |
| `tests/escenarios/contenedores.py` (el sistema de punta a punta: `identity-access`, `mail-ingest`, `booking-extraction`, `provider-sync`, `itinerary` y `bff-web`, cada uno en su contenedor) | QA-01 / ASR-1 (≤ 5 min p95, ≤ 8 min p99 y presupuesto por tramo); QA-04 / ASR-2 (cero actualizaciones perdidas, p95 de lectura ≤ 1.500 ms en ráfaga); ADR-0013, ADR-0014, ADR-0017, ADR-0020 | `tests/escenarios/test_qa01_frescura.py`, `tests/escenarios/test_qa04_rafaga.py` (trabajo `servicios` de la integración continua) |

### Diseñado y no construido

Lo que el prototipo no construye queda resuelto en la documentación de la 1ra entrega; este
apartado lo dice explícitamente para que no se lea como un faltante. Se completa al congelar.

| Qué | Dónde está diseñado | Por qué no se construye |
|---|---|---|
| Compartir itinerarios con designados y en redes sociales (paso 13) | [ADR-0028](../docs/03-adr/ADR-0028-autorizacion-comparticion-y-publicacion.md), `contratos/openapi/sharing.yaml` | No es un ASR ni lo necesita la Opción B (recorte de ADR-0034) |
| Escalado en ≤ 3 min y 9.000 peticiones/s sostenidas 30 min, con 450 correos/s (QA-04) | [ADR-0020](../docs/03-adr/ADR-0020-contrapresion-y-sobrecarga.md), [ADR-0021](../docs/03-adr/ADR-0021-estrategia-autoescalado.md), [vista de despliegue N2](../docs/04-vistas/vista-despliegue-nivel-2.md) | Docker Compose no escala réplicas solo y las cifras de producción no se buscan (ADR-0034). El paso 17 demuestra el mecanismo a escala de prototipo: ráfaga sin pérdidas y panel respondiendo |
| Los tramos de QA-01 que no son del sistema: la fuente avisa a Trotamundos (60 s) y la notificación al viajero (parte de los 60 s finales) | [Presupuesto de frescura](../docs/01-analisis-inicial/07-supuestos-y-carga-derivada.md#presupuesto-de-frescura-5-minutos) | El primero depende del proveedor; `notification` está en «Para completar el 100 %». El escenario mide hasta que el cambio se ve en el panel de `bff-web` |
| Extractor de boletos de tren (guía de extensión de QA-15, paso 4) | [Guía de extensión](../docs/02-proceso-add/iteracion-4/guias-de-extension.md), [ADR-0006](../docs/03-adr/ADR-0006-capa-de-anticorrupcion.md) | El recorte del paso 9 construye un único extractor simulado de vuelo; un segundo extractor queda para completar el contenido, sin tocar el dominio |
| Adaptador de proveedor ferroviario (guía de extensión de QA-15, paso 3) | [Guía de extensión](../docs/02-proceso-add/iteracion-4/guias-de-extension.md), [ADR-0006](../docs/03-adr/ADR-0006-capa-de-anticorrupcion.md) | El recorte del paso 10 construye el adaptador de aerolínea simulada; un adaptador ferroviario es otro complemento en `provider_sync/complementos/` sin tocar servicios de dominio |
| Ícono y etiquetas del tren en los clientes (guía de extensión de QA-15, paso 2) y aviso por `camposRelevantes` (andén) | [Guía de extensión](../docs/02-proceso-add/iteracion-4/guias-de-extension.md), [ADR-0032](../docs/03-adr/ADR-0032-internacionalizacion-y-localizacion.md) | No hay clientes ni `notification` en el prototipo; `GET /tipos-de-segmento` ya entrega la `presentacion` y los `camposRelevantes` del descriptor |
| Adaptador de modelo de lenguaje del asistente, con redacción de datos personales y vuelta a las reglas | [ADR-0037](../docs/03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md), [vista de módulos del asistente](../docs/04-vistas/vista-modulos-asistente.md) (`complementos/`) | Lo decidió así ADR-0037: el prototipo es determinista y no necesita secretos ni costo por mensaje. Es un complemento detrás del mismo puerto |
| Catálogos del asistente en otros idiomas | [ADR-0032](../docs/03-adr/ADR-0032-internacionalizacion-y-localizacion.md), ADR-0037 | El prototipo trae solo español (ADR-0037); otro idioma es otro par de archivos en `catalogos/` |
| Degradación del asistente ante `Disrupción masiva` | [ADR-0040](../docs/03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) §6, [ADR-0020](../docs/03-adr/ADR-0020-contrapresion-y-sobrecarga.md) | Los modos de degradación de ADR-0020 son de los pasos 11 y 17; cuando estén, el asistente se suma como carga de prioridad 2/3 |
| Multirregión y conmutación ante la pérdida de una región (paso 16) | [ADR-0002](../docs/03-adr/ADR-0002-despliegue-multirregion.md), [ADR-0018](../docs/03-adr/ADR-0018-consistencia-datos-multirregion.md), [vista de despliegue N2](../docs/04-vistas/vista-despliegue-nivel-2.md) | Es el paso más caro del plan. ASR-3 (QA-05) queda demostrado solo en el diseño |
| Modo sombra, métricas de correcciones de banda alta, panel/alarma y exportación OpenTelemetry de calidad | ADR-0015, ADR-0035 | El paso 9 recortado demuestra un extractor, bandas y degradación con corpus; conserva contadores y huellas locales, sin agregar una plataforma de observabilidad |
| Aviso al viajero y formulario de carga asistida para `ExtraccionNoReconocida` | ADR-0035; `notification` y clientes | El paso 9 publica el evento seguro con borrador cuando hay candidatos válidos estructuralmente; `notification` no entra en el recorte del paso 12 y no se construye un cliente extra |
| `bff-mobile`, `api-gateway`, límite de tasa (cubeta de fichas 60 req/min) y presupuesto de plazo propagado (`X-Deadline-Ms`) (paso 11) | [ADR-0005](../docs/03-adr/ADR-0005-capa-de-clientes-bff.md), [ADR-0019](../docs/03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md), [ADR-0020](../docs/03-adr/ADR-0020-contrapresion-y-sobrecarga.md), `contratos/openapi/bff-mobile.yaml`, `contratos/openapi/api-gateway.yaml` | Recorte del paso 11: para la demostración web y la Opción B alcanza con `bff-web` (ver «Para completar el 100 %») |
| Módulo `proteccion` de `provider-sync`: mamparo de 50 conexiones, cortacircuitos de ventana deslizante (`≤ 25 s`), `cola_pendientes` persistente de 24 h y limitador de cuota al 80 % (paso 10) | [ADR-0024](../docs/03-adr/ADR-0024-cortacircuitos-reintentos-y-cuotas.md), [vista de adaptadores](../docs/04-vistas/vista-modulos-adaptadores.md) | Recorte del paso 10: el paso reducido construye el anfitrión `provider-sync`, el adaptador simulado, la suite de conformidad (`QA-10`) y la publicación de `ReservaObservada` y `DisrupcionDetectada` (ver «Para completar el 100 %») |
| Historial SCD tipo 2 de `dim_proveedor` y trabajo quincenal de compactación física Parquet de fase 2 (paso 14) | [ADR-0016](../docs/03-adr/ADR-0016-modelo-dimensional-analitico.md), [ADR-0030](../docs/03-adr/ADR-0030-auditoria-y-supresion-datos-personales.md), `contratos/analitica/modelo-dimensional.sql` | Recorte del paso 14: `event-pipeline` instala `modelo-dimensional.sql`, retiene eventos crudos con seudónimo, materializa hechos/dimensiones, excluye al instante en `lista_supresion_analitica` y verifica el aislamiento de `QA-09` (ver «Para completar el 100 %») |

### Verificación del paso 9

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
docker compose rm -sf itinerary-escritura itinerary-lectura identity-access mail-ingest support-liaison virtual-assistant booking-extraction
```
