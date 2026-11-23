# Estructura del código

Parte de la documentación del [prototipo](../README.md).

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
│   │   ├── bff.py              # lo que comparten bff-web y bff-mobile: clientes, rutas y plazo (ADR-0005, ADR-0020)
│   │   ├── catalogo_extractores.py # catálogo de remitentes y extractores (.yaml), sin importar complementos (ADR-0006, RF-04)
│   │   ├── sesion.py           # sesión OIDC de las operaciones públicas      (ADR-0007)
│   │   ├── seudonimo.py        # seudónimo analítico compartido, con secreto (ADR-0016, ADR-0030)
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
│           ├── testigo.py           # registro testigo transregional de los comandos manuales (paso 16, ADR-0018)
│           ├── api.py               # API interna (openapi/itinerary.yaml)
│           └── servicio.py          # arma los módulos y define las transacciones
│       ├── identity_access/         # identidad, buzones, bóveda, ABAC y auditoría (paso 7)
│           ├── auditoria_y_revocacion.py # bitácora SHA-256 y detector de anomalías (ADR-0029, ADR-0030)
│           ├── autenticacion_oidc.py     # OIDC simulado y OTP para invitados (ADR-0007, ADR-0028)
│           ├── consentimiento_buzones.py # ciclo de vida de buzones y revocación en bloque (RF-01, ADR-0035)
│           ├── custodia_boveda.py        # único módulo con KMS/AES-GCM (regla R5, ADR-0029)
│           ├── motor_autorizacion_abac.py# políticas ABAC y vales JWS de 60 s (ADR-0028)
│           ├── ordenes_de_borrado.py     # órdenes de borrado de la fase 1 a cada servicio (ADR-0042)
│           ├── consultor_sharing.py      # atributos de una compartición, leídos de sharing (fail-closed, ADR-0028)
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
│       │   ├── interfaz_de_extractor.py # puerto Extractor v1.x (plugins/extractor.yaml)
│       │   ├── complementos/        # extractores simulados: vuelos, boletos de tren y reservas de hotel
│       │   ├── registro_de_extractores.py # carga por manifiesto y coordina la extracción
│       │   ├── validador_canonico.py # estructura y descriptor del segmento
│       │   ├── evaluador_de_confianza.py # mínimo de campos obligatorios y bandas
│       │   ├── observabilidad_de_calidad.py # huellas y disyuntor local
│       │   ├── publicacion.py       # outbox: ReservaExtraida y ExtraccionNoReconocida
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
│       ├── preferences/             # preferencias del viajero (paso 12 completo, RF-15)
│       │   ├── almacen.py            # valores por omisión del contrato y la tabla preferencias
│       │   ├── publicacion.py        # outbox: PreferenciasActualizadas
│       │   ├── api.py                # GET/PUT /preferencias (preferences.yaml)
│       │   └── servicio.py           # arma los módulos y define las transacciones
│       ├── notification/            # avisos al viajero (paso 12 completo, RF-10)
│       │   ├── reglas.py             # severidad de cada evento, según el descriptor del tipo
│       │   ├── avisos.py             # canal interno, correlación, coalescencia y horas de silencio
│       │   ├── preferencias.py       # copia local de PreferenciasActualizadas
│       │   ├── canales.py            # puerto de push y correo
│       │   ├── complementos/         # canales simulados
│       │   ├── publicacion.py        # outbox: NotificacionEmitida
│       │   └── servicio.py           # consumo con bandeja de entrada y trabajo periódico
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
│           ├── clientes.py           # adaptador HTTP a virtual-assistant (los de itinerary, en comun/bff.py)
│           ├── api.py                # bff-web.yaml: ETag/304, Cache-Control, v1+json y X-Version-Usuario
│           └── servicio.py           # arma el elemento sin estado propio
│       ├── bff_mobile/              # BFF para app-movil (paso 11 completo, ADR-0005, ADR-0019)
│           ├── resumen.py            # GET /panel/resumen: el panel compacto (≤ 15 KB)
│           ├── api.py                # bff-mobile.yaml
│           └── servicio.py           # arma el elemento sin estado propio
│       ├── sharing/                 # compartir con designados y publicar en redes (paso 13, ADR-0028)
│           ├── comparticiones.py     # la compartición: designados, vencimiento y revocación
│           ├── resumen.py            # ResumenPublicable: lista blanca de cuatro atributos
│           ├── puertos.py            # el viaje (itinerary-lectura), el vale (identity-access) y las redes
│           ├── complementos/         # red social simulada
│           ├── api.py                # sharing.yaml
│           └── servicio.py           # arma los módulos y define las transacciones
│       ├── api_gateway/             # la API pública (paso 11 completo, ADR-0005, ADR-0020, ADR-0027)
│           ├── rutas.py              # qué se publica y a qué servicio va, desde api-gateway.yaml
│           ├── cubeta.py             # cubeta de fichas por usuario (60 por minuto, ráfaga 20)
│           ├── modos.py              # Normal, PicoElevado y DisrupcionMasiva, con histéresis
│           ├── regiones.py           # salud por región y conmutación por usuario (paso 16, ADR-0002, ADR-0018)
│           └── servicio.py           # sesión, versión, plazo, traza, cola acotada y reenvío
│       ├── provider_sync/           # sincronización con proveedores de viaje (paso 10, ADR-0006, QA-10)
│           ├── interfaz_de_adaptador.py      # puerto AdaptadorDeProveedor v1.x (plugins/adaptador.yaml)
│           ├── complementos/                 # adaptadores simulados: aerolínea (NDC, JSON y XML) y ferrocarril (OSDM)
│           ├── catalogo_adaptadores.yaml     # manifiesto declarativo de adaptadores registrados
│           ├── registro_de_adaptadores.py    # carga por configuración, verifica SemVer y valida salidas
│           ├── seguimiento.py                # índice (adaptador, referencia) → (usuarioId, reservaId)
│           ├── receptor_de_notificaciones.py # firma HMAC-SHA256 y decodificación de webhooks
│           ├── programador.py                # sondeo periódico de proveedores con sondeo: true
│           ├── proteccion.py                 # cortacircuitos, mamparo, cuota y cola_pendientes (ADR-0024)
│           ├── detector_de_disrupciones.py   # expande disrupciones a usuarios afectados con seguimiento
│           ├── publicacion.py                # outbox: ReservaObservada (P1/P2) y DisrupcionDetectada (P1)
│           ├── api.py                        # POST /webhooks/proveedor (provider-sync-webhooks.yaml)
│           └── servicio.py                   # arma los módulos, consume ReservaActualizada/Cancelada y publica
│       └── event_pipeline/          # canalización y plano analítico separado (paso 14, ADR-0003, ADR-0016, QA-09)
│           ├── aterrizaje.py                 # capa de aterrizaje evento_crudo con seudónimo (sin PII)
│           ├── compactacion.py               # compactación de fase 2: cubo anónimo y acta firmada (ADR-0030)
│           ├── modelo_dimensional.py         # esquema en estrella (modelo-dimensional.sql), reconstrucción y QA-15
│           └── servicio.py                   # consumidor hacia analytics_store y fábrica de Uvicorn
├── app_web/                # interfaz web (paso 20): página estática y nginx.conf
├── docs/                   # documentación de consulta: estado de los ADR, matriz, decisiones, lo no construido y esta estructura
├── demo/                   # demostración: demo.sh, cargar_viajes.py, apoyo.py y el guion de la defensa
├── tests/
├── Dockerfile              # una imagen para todos los servicios (se construye desde la raíz)
├── docker-compose.yml      # PostgreSQL de las dos regiones, broker y servicios (región EU, paso 16)
└── Makefile
```


## Reglas verificadas por las pruebas

`tests/test_arquitectura.py` comprueba en cada corrida las reglas de las vistas de módulos:

| Regla | Origen |
|---|---|
| Ningún servicio importa a otro; solo comparten `trotamundos.comun` | ADR-0036, ADR-0001 |
| `comun` no importa ningún servicio: si lo hiciera, ese servicio pasaría a ser dependencia de todos | ADR-0036 |
| `comun/modelo.py` solo usa la biblioteca estándar | R7, vista de módulos N1 |
| Ningún módulo menciona un tipo de segmento concreto (`vuelo`, `tren`…). Solo pueden hacerlo los complementos (adaptadores y extractores), que van en carpetas `complementos/` | I4, vista de módulos N2; ADR-0011 |
| Dentro de `itinerary`, cada módulo importa solo los módulos que la vista N2 le permite (`reservas` no conoce a `fusion` ni a `viajes`; `ingesta` solo conoce a `fusion`; `api` solo a `gestion_manual` y `proyeccion_panel`; `proyeccion_panel` y `publicacion` no importan dominio). La excepción declarada es `servicio`, el punto de armado, que ningún módulo importa. Un módulo que no está en la tabla hace fallar la prueba | I1, I3, I5, vista de módulos N2 |
| Dentro de `identity_access`, cada módulo importa solo lo que permite la vista de adaptadores, y **ningún módulo del prototipo fuera de `custodia_boveda` usa `cryptography`** | R5-estricto, vista de módulos de adaptadores §2-4; ADR-0029, QA-13 |
| Dentro de `mail_ingest`, cada módulo hace un paso del flujo de la vista y no conoce al siguiente (lo arma `servicio`); los complementos de proveedor de correo solo conocen `interfaz_de_correo` | Vista de módulos N2 §3; ADR-0004, ADR-0006 |
| Dentro de `booking_extraction`, cada módulo respeta la vista N2, y cada extractor de `complementos/` es puro: no importa otro complemento ni clientes de red | R2, R3, vista de módulos N2 §2; ADR-0006, ADR-0015 |
| Dentro de `support_liaison`, `sharing`, `preferences` y `notification`, cada módulo importa solo lo que permite su tabla en la prueba (los complementos, solo su interfaz) | ADR-0006; vistas de módulos N1 y N2 |
| Dentro de `bff_mobile` y `api_gateway`, ningún módulo tiene persistencia propia ni lógica de dominio: solo componen o reenvían por HTTP | R4, vista de módulos N1; ADR-0005, ADR-0020 |
| Dentro de `virtual_assistant`, cada módulo importa solo lo que permite la vista de módulos del asistente, y solo `contexto`, `acciones` y `derivacion` hablan con otros servicios. Solo `interprete` usa los patrones, los módulos que le responden al viajero no tienen frases en el código y cada clave de mensaje usada existe en el catálogo | ADR-0037; vista de módulos del asistente |
| Dentro de `bff_web`, ningún módulo tiene persistencia propia ni lógica de dominio: solo compone respuestas de `itinerary-lectura`, `itinerary-escritura` y `virtual-assistant` por HTTP | R4, vista de módulos N1; ADR-0005, ADR-0034 |
| Dentro de `provider_sync`, cada módulo respeta las dependencias de la vista de adaptadores y ningún complemento en `complementos/` importa a otro complemento | R2, R3, vista de módulos de adaptadores §1; ADR-0006, QA-10 |
| Dentro de `event_pipeline`, ningún módulo hace llamadas HTTP ni publica eventos al plano operacional: solo consume eventos del *broker* y escribe en su esquema analítico propio (`analytics_store`) | R6, vista de módulos N1; ADR-0003, QA-09 |
