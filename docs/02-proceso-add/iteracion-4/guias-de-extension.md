# Guías de extensión — Verificación documental de `QA-15`, `QA-10` y `QA-18`

> **Iteración:** 4 · **Drivers verificados:** `QA-15`, `QA-10`, `QA-18`, `CON-04`, `CON-07`, `CON-A3`, `CRN-14`
> **ADRs aplicados:** [ADR-0006](../../03-adr/ADR-0006-capa-de-anticorrupcion.md) · [ADR-0009](../../03-adr/ADR-0009-contratos-spec-driven.md) · [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md) · [ADR-0031](../../03-adr/ADR-0031-residencia-de-datos-por-region.md) · [ADR-0032](../../03-adr/ADR-0032-internacionalizacion-y-localizacion.md)

En ADD, los escenarios de evolucionabilidad e interoperabilidad no se dan por cumplidos declarando
«usamos complementos»: se verifican recorriendo paso a paso el cambio sobre la arquitectura diseñada
y contabilizando **qué elementos existentes se tocan**, **qué contratos cambian** y **cuántas
horas-persona demanda**. Este documento ejecuta esa verificación formal para los tres escenarios de
extensión del enunciado.

---

## 1. Guía: Cómo agregar un nuevo medio de transporte (verificación de `QA-15` con `tren`)

### Escenario y criterio de aceptación (`QA-15`)

* **Estímulo:** el equipo de producto decide incorporar **trenes** (y análogamente autobuses o
  *ferries*), con su propio esquema de segmento, sus propios proveedores/formatos de correo y sus
  reglas de visualización y aviso.
* **Medidas exigidas por [QA-15](../../01-analisis-inicial/04-escenarios-de-calidad.md#qa-15--incorporar-un-nuevo-medio-de-transporte):**
  1. Elementos existentes modificados **≤ 2** (registro de tipos y presentación), **ninguno** de
     ellos un servicio de dominio.
  2. Esfuerzo total **≤ 80 horas-persona**.
  3. **Cero** cambios incompatibles en contratos publicados; datos históricos previos 100 %
     consultables.

### Procedimiento paso a paso para incorporar `tren`

| Paso | Acción concreta | Artefacto creado o tocado | ¿Modifica un elemento existente? | Esfuerzo estimado |
|---|---|---|---|---|
| **1. Declarar el descriptor del tipo** | Crear el descriptor declarativo `tren` (`version: 1`, `rolEnViaje: traslado`) especificando `esquemaDeDetalle` (`numeroDeTren`, `coche`, `asiento`, `clase`, `anden`), `camposRelevantes` para avisos críticos (`inicio.instante` ≥ 15 min, `detalle.anden`), `presentacion` (`icono: tren`, `filas: [coche, asiento, clase]`) y `dimension` analítica (`[operador, clase]`) | `contratos/tipos-de-segmento/tren.v1.yaml` + alta en el catálogo de `modelo-canonico` (**Elemento tocado #1: registro declarativo de tipos**) | Sí — **1** (configuración declarativa, no servicio de dominio) | **8 h-p** |
| **2. Registrar ícono y etiquetas localizadas de presentación** | Añadir el glifo vectorial `tren` y las claves de traducción (`segmento.tren.coche`, `segmento.tren.anden`, etc.) en los paquetes `locales/*.json` servidos a `app-web` y `app-movil` (**Elemento tocado #2: recursos de presentación del panel**) | `locales/*.json` e ícono en clientes (`D32`) | Sí — **2** (recursos de presentación, no lógica de dominio) | **8 h-p** |
| **3. Agregar complemento adaptador de proveedor ferroviario** | Implementar un complemento nuevo que cumpla `AdaptadorDeProveedor` (`apiContrato: "1.0"`, `tiposDeSegmento: [tren]`), traduciendo p. ej. OSDM / Rail API a `ObservacionCanonica`, y registrarlo en la configuración de `provider-sync` | Nuevo paquete complemento `adaptador-ferroviario` + entrada en registro | **No (`0`)** — complemento nuevo aislado (`ADR-0006`) | **24 h-p** |
| **4. Agregar complemento extractor de boletos de tren** | Implementar un complemento `Extractor` (`apiContrato: "1.0"`) para confirmaciones por correo/PDF del operador ferroviario con sus umbrales de confianza y registrarlo en `booking-extraction` | Nuevo paquete complemento `extractor-ferroviario` | **No (`0`)** — complemento nuevo aislado; alimenta automáticamente la *whitelist* de catálogo (`RF-04`) | **16 h-p** |
| **5. Ejecutar suite de conformidad y desplegar en canario** | Correr las pruebas contractuales genéricas (`D17`, `D27`), verificar compatibilidad con segmentos históricos y desplegar con entrega progresiva (`5 % → 25 % → 100 %`, `D22`) | Pruebas automatizadas de conformidad | **No (`0`)** | **12 h-p** |
| **Total** | — | — | **2 artefactos existentes tocados · `0` servicios de dominio modificados** | **68 h-p (`≤ 80 h-p`)** |

### Por qué ningún servicio de dominio ni el plano analítico se tocan

| Servicio | Cómo procesa un segmento `tren` sin cambiar una sola línea de código |
|---|---|
| `itinerary` (`reservas`, `fusion`, `viajes`, `proyeccion-panel`) | Valida `Segmento.detalle` contra el JSON Schema leído del descriptor `tren.v1`; agrupa reservas en `Viaje` razonando por `rolEnViaje = traslado` y continuidad de `Lugar`, nunca por `if (tipo == 'vuelo')` (`iteración 2 §5.1`); guarda `detalle` en la columna JSON semiestructurada de `segmento` (`D12`) |
| `notification` | Evalúa si un cambio de `detalle.anden` o `inicio.instante` es **Crítico** leyendo el arreglo `camposRelevantes` del descriptor `tren.v1` |
| `bff-web` y `bff-mobile` | Exponen `GET /tipos-de-segmento` (cacheado en `edge`, `D19`) y entregan el bloque `presentacion` para que los clientes rendericen filas y etiquetas de forma dirigida por datos |
| `event-pipeline` y `analytics-store` | `dim_tipo_segmento` inserta automáticamente **una fila nueva** para `tren` al detectar el descriptor (`iteración 2 §5.9`); `hecho_cambio_reserva` y `hecho_viaje` registran los eventos sin alterar ni una columna SQL |

**Veredicto `QA-15`:** ✅ **Verificado** (`2 ≤ 2` elementos tocados, `0` servicios de dominio, `68 h-p ≤ 80 h-p`, `0` rupturas de contrato).

---

## 2. Guía: Cómo agregar un proveedor de viaje nuevo (verificación de `QA-10`)

### Escenario y criterio de aceptación (`QA-10`)

* **Estímulo:** acuerdo comercial con una nueva aerolínea que expone una API estándar IATA NDC (o una
  cadena hotelera con OTA/HTNG) para consultar reservas, recibir cambios y cancelaciones.
* **Medidas exigidas por [QA-10](../../01-analisis-inicial/04-escenarios-de-calidad.md#qa-10--integración-de-un-proveedor-de-viaje-nuevo):**
  1. Elementos existentes modificados = **`0`** (únicamente se agrega el adaptador nuevo y su
     configuración).
  2. Esfuerzo **≤ 40 horas-persona**.
  3. Despliegue con **`0 s` de inactividad** y **≥ 99 %** de mensajes traducidos válidamente en la
     primera semana.

### Procedimiento paso a paso

| Paso | Qué hace el desarrollador | Mecanismo arquitectónico que evita tocar otros elementos | Esfuerzo estimado |
|---|---|---|---|
| **1. Instanciar plantilla de complemento** | Genera el módulo `adaptador-ndc-<aerolinea>` implementando la interfaz `AdaptadorDeProveedor` (`apiContrato: "1.0"`, [ADR-0027](../../03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md)): `obtenerReserva`, `traducirNotificacion`, `sondear` y `detectarDisrupcion` | El tipo de segmento `vuelo` ya existe; ni `modelo-canonico`, ni `itinerary`, ni ningún otro adaptador se editan | **14 h-p** |
| **2. Declarar manifiesto operativo y de seguridad** | Declara en configuración declarativa su `cuotaPorMinuto` (el anfitrión aplica automáticamente el tope del `80 %` y alerta al `70 %`, `D24`), umbrales de cortacircuitos (`20 s` / `50 %`), mamparo aislado (`50` conexiones) y referencia al secreto de API en `VAULT` | `proteccion` de `provider-sync` envuelve cualquier complemento registrado sin código repetido (`ADR-0024`) | **4 h-p** |
| **3. Pasar pruebas de contrato y conformidad** | Ejecuta la suite de conformidad (`D17`) con cargas reales/grabadas de confirmación, reprogramación, cambio de puerta, cancelación y error `429`/`503` del proveedor contra el validador de `ObservacionCanonica` | Garantiza antes de producción que el `100 %` de las salidas respetan invariantes y que ningún tipo NDC cruza la frontera (`Regla R3`) | **10 h-p** |
| **4. Activar en sombra y rampa canaria** | Registra el complemento en configuración y despliega con rampa progresiva (`5 % → 25 % → 100 %` por región, `D22`), monitoreando tasa de validación canónica en OpenTelemetry (`D25`); ante tasa de rechazo `> 1 %`, el disyuntor del complemento lo aísla sin afectar al resto de `provider-sync` | `0 s` de inactividad (`QA-07`) y cumplimiento verificable del `≥ 99 %` de traducción correcta | **6 h-p** |
| **Total** | — | **`0` elementos existentes modificados** | **34 h-p (`≤ 40 h-p`)** |

*(Nota sobre `QA-11`: incorporar un extractor nuevo `extractor-<remitente>` en `booking-extraction`
sigue exactamente los pasos 1, 3 y 4 sobre la interfaz más simple `Extractor` —solo `reconoce` y
`extrae`, sin llamadas salientes ni cuotas—, demandando **`12–14 h-p ≤ 16 h-p`**).*

**Veredicto `QA-10`:** ✅ **Verificado** (`0` elementos existentes modificados, `34 h-p ≤ 40 h-p`, `0 s` de inactividad).

---

## 3. Guía: Cómo incorporar una región geográfica nueva (verificación de `QA-18`)

### Escenario y criterio de aceptación (`QA-18`)

* **Estímulo:** apertura comercial en una cuarta región o nuevo mercado lingüístico/regulatorio (por
  ejemplo, Japón o Brasil con requisitos específicos de idioma, moneda y marco local de privacidad).
* **Medidas exigidas por [QA-18](../../01-analisis-inicial/04-escenarios-de-calidad.md#qa-18--incorporación-de-una-región-nueva):**
  `0` cadenas embebidas en código, **`0` elementos de lógica de negocio modificados**, esfuerzo
  **≤ 120 horas-persona** (dominado por traducción) y cumplimiento pleno de `QA-02` y `QA-05`.

### Desglose de incorporación

| Paso | Actividad | Elementos de lógica de negocio modificados | Esfuerzo estimado |
|---|---|---|---|
| **1. Localización lingüística y cultural** | Traducción y revisión nativa del catálogo `locales/{idioma}-{pais}.json` (mensajes ICU de interfaz, plantillas de `notification` y nombres de `TipoDeSegmento`) y publicación en el CDN de `edge` (`D32`) | **`0`** (los formatos de fecha, número y moneda se resuelven por CLDR estándar) | **64 h-p** *(traducción y QA lingüístico)* |
| **2. Perfil normativo de residencia** | Alta declarativa de la jurisdicción en `politica_residencia` (`D31`): asignación de región física primaria, par de respaldo permitido para el testigo cifrado y plazos legales locales de atención de derechos | **`0`** | **10 h-p** |
| **3. Instanciación de infraestructura regional (IaC)** | Aplicación del módulo declarativo de región ([vista-despliegue-nivel-2](../../04-vistas/vista-despliegue-nivel-2.md), `D26`): clúster en 3 AZs, `64` *buckets* OLTP, caché regional, bóveda `VAULT` con `KEK` local (`D29`), sondas sintéticas cada `15 s` (`D25`) y alta con peso gradual en el DNS Anycast | **`0`** (se despliegan exactamente las mismas imágenes inmutables de contenedor) | **28 h-p** |
| **4. Validación de humo, latencia y residencia** | Ejecución de sondas de latencia (`QA-02 ≤ 800 ms`), simulacro de desvío regional (`QA-05 ≤ 60 s`) y auditoría de no fuga de datos `Clase R1` fuera de la nueva región | **`0`** | **10 h-p** |
| **Total** | — | **`0` elementos de lógica de negocio modificados** | **112 h-p (`≤ 120 h-p`)** |

**Veredicto `QA-18`:** ✅ **Verificado** (`0` servicios de dominio tocados, `112 h-p ≤ 120 h-p`, la traducción representa el `57 %` del esfuerzo tal como prevé el escenario).
