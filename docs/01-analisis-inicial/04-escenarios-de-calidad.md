# 1.4 Escenarios de atributos de calidad

Los siete atributos de calidad del enunciado están expresados como objetivos narrativos
(«debe ser accesible en todo momento», «es imperativa una integración fluida»). Narrados así no
son verificables y no sirven como drivers de ADD. Esta página los refina a **18 escenarios
concretos en el formato de 6 partes del SEI**: fuente de estímulo, estímulo, ambiente, artefacto,
respuesta y medida de respuesta.

Cada escenario tiene una **medida de respuesta numérica**. Donde el enunciado no daba el número,
se derivó y el supuesto está etiquetado (ver [1.7 Supuestos y carga
derivada](07-supuestos-y-carga-derivada.md)).

| | Atributo | Escenarios |
|---|---|---|
| 1 | Rendimiento y latencia | [QA-01](#qa-01--propagación-de-una-actualización-de-viaje) · [QA-02](#qa-02--tiempo-de-respuesta-del-panel-web) · [QA-03](#qa-03--primer-despliegue-de-contenido-en-móvil) · [QA-04](#qa-04--pico-de-carga-por-disrupción-masiva) |
| 2 | Disponibilidad | [QA-05](#qa-05--pérdida-de-una-región-completa) · [QA-06](#qa-06--indisponibilidad-de-un-proveedor-externo) · [QA-07](#qa-07--despliegue-de-una-nueva-versión) |
| 3 | Escalabilidad | [QA-08](#qa-08--crecimiento-de-la-base-de-cuentas) · [QA-09](#qa-09--aislamiento-de-la-carga-analítica) |
| 4 | Interoperabilidad | [QA-10](#qa-10--integración-de-un-proveedor-de-viaje-nuevo) · [QA-11](#qa-11--formato-de-correo-desconocido) |
| 5 | Seguridad y privacidad | [QA-12](#qa-12--compartición-de-un-itinerario-con-personas-designadas) · [QA-13](#qa-13--intento-de-acceso-a-las-credenciales-de-correo) · [QA-14](#qa-14--auditoría-de-acceso-a-datos-personales) |
| 6 | Evolucionabilidad y mantenibilidad | [QA-15](#qa-15--incorporar-un-nuevo-medio-de-transporte) · [QA-16](#qa-16--trazabilidad-de-una-decisión-al-código) |
| 7 | Usabilidad e internacionalización | [QA-17](#qa-17--contexto-de-ubicación-en-el-dispositivo-móvil) · [QA-18](#qa-18--incorporación-de-una-región-nueva) |

---

## 1. Rendimiento y latencia

### QA-01 — Propagación de una actualización de viaje

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un proveedor de viaje externo (aerolínea, hotel, rentadora) o el proveedor de correo del usuario |
| **Estímulo** | Se genera un cambio en una reserva existente del usuario: cambio de horario, cambio de puerta, cancelación o confirmación |
| **Ambiente** | Operación normal, en día de carga pico (domingo-lunes o jueves-viernes) |
| **Artefacto** | La cadena completa de ingesta y propagación: adaptador de proveedor → normalización → itinerario → panel del cliente |
| **Respuesta** | El sistema detecta el cambio, lo normaliza al modelo canónico, lo asocia al viaje correspondiente y lo refleja en el panel del usuario, emitiendo la notificación correspondiente |
| **Medida de respuesta** | Tiempo desde la generación del cambio en la fuente hasta su visibilidad en la aplicación ≤ **5 minutos** en el percentil 95; ≤ 8 minutos en el p99. Presupuesto por tramo en [1.7](07-supuestos-y-carga-derivada.md#presupuesto-de-frescura-5-minutos) |

> *En prosa:* cuando una aerolínea cambia el horario de un vuelo del usuario durante un día de
> carga pico, el sistema debe normalizar el cambio y mostrarlo en el panel del viajero en menos de
> 5 minutos (p95) desde que la fuente lo generó.

### QA-02 — Tiempo de respuesta del panel web

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un viajero autenticado desde el navegador web |
| **Estímulo** | Solicita la carga de su panel de viajes agrupado |
| **Ambiente** | Carga pico: 3.000 peticiones por segundo sostenidas (derivada en [S-01…S-05](07-supuestos-y-carga-derivada.md#derivación-del-tráfico-de-lectura)) |
| **Artefacto** | El camino de lectura del panel: borde → *gateway* → BFF web → servicio de itinerario → almacén de lectura |
| **Respuesta** | El sistema devuelve el panel completo con los viajes activos del usuario y sus reservas agrupadas |
| **Medida de respuesta** | Tiempo de respuesta extremo a extremo de la petición HTTP medido en el borde ≤ **800 ms** en el p95 y ≤ 1.500 ms en el p99, con tasa de error < 0,1 % |

> *En prosa:* bajo carga pico de 3.000 req/s, la carga del panel de viajes debe responder en menos
> de 800 ms en el percentil 95, medido en el borde de la red.

### QA-03 — Primer despliegue de contenido en móvil

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un viajero abriendo la aplicación móvil |
| **Estímulo** | Arranque en frío de la aplicación y solicitud de la pantalla principal del panel |
| **Ambiente** | Red móvil 4G (RTT de 150 ms, 1,6 Mbps de bajada) sobre un dispositivo de gama media ([S-10](07-supuestos-y-carga-derivada.md#supuestos-de-carga)) |
| **Artefacto** | La aplicación móvil y el BFF móvil |
| **Respuesta** | La aplicación pinta el primer contenido significativo del panel (los viajes próximos), aunque los detalles secundarios sigan cargando |
| **Medida de respuesta** | *First Contentful Paint* ≤ **1,4 segundos** en el p75 de las sesiones reales de usuario |

> *En prosa:* en un arranque en frío sobre 4G y dispositivo de gama media, la app móvil debe
> pintar los viajes próximos en menos de 1,4 segundos (p75).

### QA-04 — Pico de carga por disrupción masiva

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un evento disruptivo masivo externo (tormenta que cancela los vuelos de un *hub*, huelga de una aerolínea) |
| **Estímulo** | Llegada simultánea de una ráfaga de actualizaciones de proveedores **y** de un pico de usuarios consultando su panel |
| **Ambiente** | Operación degradada por sobrecarga, sin aviso previo, con el pico alcanzando el triple del pico normal ([S-06](07-supuestos-y-carga-derivada.md#supuestos-de-carga)) |
| **Artefacto** | Todo el sistema: plano de ingesta y plano de lectura simultáneamente |
| **Respuesta** | El sistema absorbe la ráfaga sin pérdida de actualizaciones, escala los elementos afectados y, si no alcanza, degrada funcionalidad secundaria (analítica, recomendaciones, publicación en redes) antes que el panel y las notificaciones |
| **Medida de respuesta** | Hasta **9.000 peticiones por segundo** (3× el pico normal de 3.000) sostenidas durante 30 minutos, más **450 eventos de correo por segundo**: cero actualizaciones perdidas, p95 de lectura del panel ≤ 1.500 ms (degradación aceptada frente a los 800 ms), tiempo de escalado ≤ 3 minutos |

> *En prosa:* ante una disrupción climática que triplica el tráfico sin aviso, el sistema debe
> absorber hasta 9.000 req/s durante 30 minutos sin perder ninguna actualización, degradando
> primero la analítica y sosteniendo el panel por debajo de 1,5 s en el p95.

---

## 2. Disponibilidad

### QA-05 — Pérdida de una región completa

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Falla de infraestructura del proveedor de nube: caída de una región completa |
| **Estímulo** | Falla por omisión (*crash*): la región deja de responder a las peticiones y de replicar datos |
| **Ambiente** | Operación normal, en horario de pico de la región afectada |
| **Artefacto** | Todo el sistema desplegado en esa región |
| **Respuesta** | El enrutamiento del borde detecta la región caída, redirige el tráfico a las regiones sanas, que continúan atendiendo con los datos replicados; se alerta al operador |
| **Medida de respuesta** | Tiempo de detección ≤ 30 s; tiempo hasta que el tráfico queda redirigido ≤ 60 s; pérdida de datos confirmados = **0**; consumo del presupuesto mensual de inactividad ≤ **1,5 de los 5 minutos** disponibles |

> *En prosa:* si una región de nube completa cae en su horario de pico, el borde debe detectarlo
> en menos de 30 segundos y redirigir todo el tráfico a las regiones sanas en menos de 60, sin
> perder datos confirmados y consumiendo a lo sumo 1,5 minutos del presupuesto mensual de 5.

### QA-06 — Indisponibilidad de un proveedor externo

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un sistema externo: la API de un proveedor de viaje o de un proveedor de correo |
| **Estímulo** | El proveedor deja de responder, responde con errores o excede el tiempo de espera de forma sostenida durante 15 minutos |
| **Ambiente** | Operación normal; el resto del sistema está sano |
| **Artefacto** | El adaptador de ese proveedor dentro de la capa de anticorrupción |
| **Respuesta** | El adaptador abre su cortacircuitos, deja de propagar la falla al resto del sistema, encola los trabajos pendientes para reintento con retroceso exponencial, el panel sigue sirviendo el último dato conocido con su marca de frescura, y se alerta al operador |
| **Medida de respuesta** | **Cero** peticiones de lectura del panel fallidas por causa del proveedor caído; cero actualizaciones perdidas (se recuperan al restablecerse el proveedor, con una cola de hasta 24 h); apertura del cortacircuitos ≤ 30 s desde el inicio de la falla; **este evento no consume presupuesto de inactividad** (ver [ADR-0008](../03-adr/ADR-0008-alcance-disponibilidad.md)) |

> *En prosa:* si la API de una aerolínea se cae durante 15 minutos, ninguna consulta al panel debe
> fallar por esa causa: el adaptador aísla la falla, el panel muestra el último dato conocido con
> su marca de frescura, y las actualizaciones pendientes se recuperan cuando el proveedor vuelve.

### QA-07 — Despliegue de una nueva versión

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un integrante del equipo de desarrollo |
| **Estímulo** | Despliega una versión nueva de un servicio a producción |
| **Ambiente** | Operación normal, en cualquier momento del día, sin ventana de mantenimiento |
| **Artefacto** | El servicio desplegado y el mecanismo de despliegue |
| **Respuesta** | El despliegue se hace progresivamente sobre un subconjunto del tráfico; el sistema compara los indicadores de salud del subconjunto contra la versión anterior y revierte automáticamente si se degradan |
| **Medida de respuesta** | Inactividad atribuible al despliegue = **0 segundos**; tiempo de reversión automática ≤ 2 minutos desde la detección de la degradación; porcentaje de tráfico afectado por una versión defectuosa ≤ 5 % |

> *En prosa:* desplegar una versión nueva en pleno horario productivo no debe generar ni un
> segundo de inactividad, y una versión defectuosa debe revertirse automáticamente afectando a lo
> sumo al 5 % del tráfico.

---

## 3. Escalabilidad

### QA-08 — Crecimiento de la base de cuentas

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | El crecimiento del negocio (campaña de marketing, acuerdo con una aerolínea) |
| **Estímulo** | La base de cuentas crece de 15 a 30 millones y los usuarios activos semanales de 2 a 4 millones en un plazo de 12 meses |
| **Ambiente** | Operación normal, crecimiento gradual y previsible |
| **Artefacto** | Todo el sistema, en particular el plano de datos operacional |
| **Respuesta** | El sistema absorbe el crecimiento agregando capacidad horizontal, sin cambios en la estructura de la arquitectura ni migraciones que requieran detener el servicio |
| **Medida de respuesta** | Las medidas de QA-01 a QA-04 se mantienen con el doble de carga; el crecimiento se absorbe **sin modificar ningún contrato entre elementos** y sin inactividad planificada; el costo de infraestructura crece a lo sumo de forma lineal con los usuarios activos |

> *En prosa:* duplicar la base de usuarios en un año debe resolverse agregando capacidad
> horizontal, sin tocar contratos entre servicios ni detener el servicio, y con un costo que no
> crezca más que linealmente.

### QA-09 — Aislamiento de la carga analítica

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un analista del equipo de datos |
| **Estímulo** | Ejecuta una consulta analítica pesada: tendencias de destinos y tasas de cancelación sobre 3 años de historia y el total de las cuentas |
| **Ambiente** | Carga pico del plano operacional, simultánea con la consulta |
| **Artefacto** | El plano analítico y, por lo que debe *no* ocurrir, el plano operacional |
| **Respuesta** | La consulta se ejecuta íntegramente contra el almacén analítico, sin tocar las bases operacionales ni competir por sus recursos |
| **Medida de respuesta** | Degradación medible del p95 de latencia operacional < **5 %** durante la consulta; latencia de la consulta analítica ≤ 30 s en el p95; frescura de los datos analíticos ≤ 1 hora respecto del plano operacional |

> *En prosa:* una consulta analítica sobre tres años de historia ejecutada en pleno pico
> operacional no debe degradar la latencia del panel más de un 5 %, debe responder en menos de
> 30 segundos y sus datos no pueden tener más de una hora de atraso.

---

## 4. Interoperabilidad

### QA-10 — Integración de un proveedor de viaje nuevo

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un integrante del equipo de desarrollo, ante un acuerdo comercial con una aerolínea u hotelera nueva |
| **Estímulo** | Pedido de integrar un proveedor nuevo que expone una API estándar del dominio (IATA NDC, OTA/HTNG) para obtener detalles, actualizaciones y cancelaciones |
| **Ambiente** | Tiempo de diseño y desarrollo; el sistema en producción no se detiene |
| **Artefacto** | La capa de anticorrupción y el contrato canónico de proveedor |
| **Respuesta** | Se desarrolla y despliega un adaptador nuevo que implementa el contrato canónico, **sin modificar** ningún servicio de dominio ni ningún otro adaptador |
| **Medida de respuesta** | Cantidad de elementos existentes modificados = **0** (solo se agrega el adaptador y su registro de configuración); esfuerzo ≤ **40 horas-persona**; el adaptador se despliega sin inactividad; ≥ 99 % de los mensajes del proveedor se traducen correctamente al modelo canónico en la primera semana |

> *En prosa:* integrar una aerolínea nueva que expone NDC debe resolverse escribiendo únicamente
> un adaptador —sin tocar ningún servicio de dominio ni otro adaptador— en menos de 40
> horas-persona.

### QA-11 — Formato de correo desconocido

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un proveedor de correo entregando un mensaje de un remitente de viaje |
| **Estímulo** | Llega un correo de confirmación de reserva cuyo formato el sistema no sabe interpretar, o cuyo formato cambió respecto del conocido |
| **Ambiente** | Operación normal, flujo de ingesta continuo |
| **Artefacto** | El servicio de extracción de reservas y su registro de extractores |
| **Respuesta** | El sistema reconoce que no pudo extraer la reserva con confianza suficiente, **no inventa datos ni corrompe el itinerario**, registra el caso con la huella del formato para su análisis, y ofrece al usuario completar la reserva manualmente |
| **Medida de respuesta** | Tasa de extracción incorrecta silenciosa (datos erróneos insertados sin aviso) = **0 %**; ≥ 95 % de los correos de los 20 remitentes de viaje más frecuentes se extraen correctamente; un extractor nuevo para un formato detectado se agrega en ≤ 16 horas-persona sin modificar los existentes |

> *En prosa:* si llega un correo de reserva en un formato desconocido, el sistema nunca debe
> insertar datos erróneos en el itinerario: registra el formato para análisis y le ofrece al
> usuario la carga manual, y agregar el extractor faltante debe costar menos de 16 horas-persona.

---

## 5. Seguridad y privacidad

### QA-12 — Compartición de un itinerario con personas designadas

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Una persona **no designada** que obtuvo el enlace de un itinerario compartido (por reenvío, por captura de pantalla o por fuerza bruta sobre el identificador) |
| **Estímulo** | Intento de visualizar un itinerario para el cual no está en la lista de designados |
| **Ambiente** | Sistema en línea, expuesto a la red pública |
| **Artefacto** | El servicio de compartición y la autorización del itinerario |
| **Respuesta** | El sistema exige autenticación, verifica que la identidad autenticada esté en la lista de designados del itinerario, deniega el acceso, registra el intento y no revela si el itinerario existe |
| **Medida de respuesta** | **100 %** de los accesos de no designados denegados y registrados; 0 fugas de datos del itinerario en la respuesta de error; los enlaces caducan a los 30 días o al revocarse, con efecto en ≤ 60 s |

> *En prosa:* quien obtiene el enlace de un itinerario compartido pero no está en la lista de
> designados debe recibir un rechazo del 100 % de las veces, sin que la respuesta revele si el
> itinerario existe, y el registro del intento debe quedar asentado.

### QA-13 — Intento de acceso a las credenciales de correo

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un atacante externo que logró ejecutar código en un servicio del sistema, o un atacante interno con acceso a la infraestructura |
| **Estímulo** | Intento de leer en masa los tokens OAuth con que el sistema accede a los 9 millones de buzones conectados ([S-07](07-supuestos-y-carga-derivada.md#supuestos-de-carga)) |
| **Ambiente** | Sistema en producción, en línea |
| **Artefacto** | El almacén de tokens de acceso delegado a proveedores de correo |
| **Respuesta** | Los tokens están cifrados en reposo con claves que el servicio comprometido no posee; el acceso al almacén de secretos requiere una identidad de carga de trabajo distinta por servicio y queda auditado; un patrón de acceso anómalo dispara alerta y permite revocar en masa |
| **Medida de respuesta** | Ningún servicio, salvo el de identidad y acceso, puede descifrar un token (verificable por revisión de políticas de acceso); **100 %** de los accesos al almacén de secretos auditados; detección de un patrón de extracción masiva ≤ **5 minutos**; capacidad de revocar el 100 % de los tokens de una región en ≤ 15 minutos |

> *En prosa:* si un atacante compromete un servicio e intenta extraer en masa los tokens de
> acceso a los correos, no debe poder descifrarlos, el intento debe detectarse en menos de 5
> minutos y el sistema debe poder revocar todos los tokens de una región en menos de 15.

### QA-14 — Auditoría de acceso a datos personales

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un usuario ejerciendo su derecho de acceso o de supresión, o un auditor de cumplimiento |
| **Estímulo** | Solicitud de saber qué datos personales tiene el sistema sobre el usuario, quién los accedió, o pedido de eliminarlos |
| **Ambiente** | Operación normal; aplica el marco normativo de la región del usuario (CON-10) |
| **Artefacto** | El registro de auditoría y los almacenes que contienen datos personales, incluido el plano analítico |
| **Respuesta** | El sistema produce el inventario de datos personales del usuario y el historial de accesos, y ante un pedido de supresión los elimina de todos los almacenes, incluido el analítico, dejando constancia |
| **Medida de respuesta** | Inventario y historial producidos en ≤ **72 horas**; supresión completada y verificable en ≤ **30 días** en el 100 % de los almacenes; cobertura del registro de auditoría sobre accesos a datos personales = 100 % |

> *En prosa:* un usuario que pide saber qué datos tiene el sistema sobre él debe recibir el
> inventario y el historial de accesos en 72 horas, y si pide la supresión, sus datos deben
> desaparecer de todos los almacenes —el analítico incluido— en 30 días de forma verificable.

---

## 6. Evolucionabilidad y mantenibilidad

### QA-15 — Incorporar un nuevo medio de transporte

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | El equipo de producto, ante la decisión de soportar trenes (y más adelante autobuses y *ferries*) |
| **Estímulo** | Pedido de incorporar un medio de transporte nuevo, con su propio tipo de segmento, sus propios proveedores y sus propias reglas de presentación en el panel |
| **Ambiente** | Tiempo de diseño y desarrollo, para el siguiente *release* |
| **Artefacto** | El modelo canónico de reserva/segmento, la capa de anticorrupción, el panel y el plano analítico |
| **Respuesta** | El medio nuevo se incorpora como una extensión del modelo canónico y un adaptador nuevo, sin modificar los tipos de segmento existentes ni los servicios de dominio |
| **Medida de respuesta** | Elementos existentes modificados ≤ **2** (el registro de tipos de segmento y la presentación del panel), **ninguno** de ellos un servicio de dominio; esfuerzo ≤ **80 horas-persona**; cero cambios incompatibles en los contratos publicados; los datos históricos previos siguen siendo consultables |

> *En prosa:* agregar trenes al sistema debe tocar a lo sumo dos elementos existentes —y ninguno
> de ellos un servicio de dominio— con un esfuerzo menor a 80 horas-persona y sin romper ningún
> contrato publicado.

### QA-16 — Trazabilidad de una decisión al código

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un integrante nuevo del equipo, o un evaluador externo de la arquitectura |
| **Estímulo** | Pregunta por qué un elemento del sistema está construido de una determinada manera, y qué driver lo justifica |
| **Ambiente** | Revisión de la documentación y del código, sin acceso a los autores originales |
| **Artefacto** | El conjunto de ADRs, las vistas, los contratos y el código del prototipo |
| **Respuesta** | La persona puede recorrer la cadena completa: driver → decisión → ADR → vista → contrato → código, en ambos sentidos |
| **Medida de respuesta** | **100 %** de los drivers del análisis inicial referenciados por al menos un ADR; 100 % de los ADRs referenciando los drivers que atienden y las alternativas descartadas; tiempo para responder «por qué este elemento existe» ≤ **10 minutos** usando solo la wiki |

> *En prosa:* alguien que llega nuevo al proyecto debe poder explicar por qué existe cualquier
> elemento del sistema en menos de 10 minutos, recorriendo la wiki desde el driver hasta el código.

---

## 7. Usabilidad e internacionalización

### QA-17 — Contexto de ubicación en el dispositivo móvil

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | Un viajero en tránsito, usando la aplicación móvil |
| **Estímulo** | Abre la aplicación durante un viaje en curso, estando físicamente cerca de uno de los puntos de su itinerario (aeropuerto, hotel) |
| **Ambiente** | Uso habitual, en movimiento, con conectividad intermitente y permiso de ubicación otorgado |
| **Artefacto** | La aplicación móvil y el servicio de itinerario |
| **Respuesta** | La aplicación usa el GPS del dispositivo para destacar el segmento del viaje pertinente al lugar y momento, sin que el usuario tenga que buscarlo, y funciona de forma degradada pero útil si el permiso está denegado o no hay señal |
| **Medida de respuesta** | El segmento pertinente queda visible sin interacción adicional en ≥ **90 %** de los casos; tasa de finalización de la tarea «ver mi próximo segmento» ≥ 95 %; la aplicación muestra el itinerario completo aunque el permiso de ubicación esté denegado (verificable sí/no) |

> *En prosa:* al abrir la app cerca del aeropuerto durante un viaje en curso, el segmento
> pertinente debe quedar visible sin que el usuario busque nada en el 90 % de los casos, y la app
> debe seguir siendo usable si se deniega el permiso de ubicación.

### QA-18 — Incorporación de una región nueva

| Parte | Valor |
|---|---|
| **Fuente de estímulo** | El equipo de producto, al abrir el mercado de una región nueva |
| **Estímulo** | Pedido de operar en una región geográfica nueva, con su idioma, sus formatos locales, su zona horaria, su moneda y su marco normativo de datos personales |
| **Ambiente** | Tiempo de diseño y despliegue; el sistema en producción sigue operando |
| **Artefacto** | Los recursos de localización, el enrutamiento del borde y la política de residencia de datos |
| **Respuesta** | La región se incorpora agregando recursos de localización y una instancia de despliegue regional, sin modificar la lógica de los servicios y respetando la residencia de datos exigida localmente |
| **Medida de respuesta** | Cero cadenas de texto embebidas en código (verificable por análisis estático); elementos de lógica de negocio modificados = **0**; esfuerzo de incorporación ≤ **120 horas-persona**, de las cuales la traducción es la mayor parte; el sistema sostiene las medidas de QA-02 y QA-05 en la región nueva |

> *En prosa:* abrir una región nueva debe consistir en agregar traducciones y una instancia de
> despliegue regional, sin modificar ni una línea de lógica de negocio, en menos de 120
> horas-persona.

---

## Tensiones entre escenarios

Los escenarios no son independientes. Estas tensiones son las que las decisiones arquitectónicas
tienen que arbitrar, y por eso se registran acá:

| Tensión | Escenarios en conflicto | Cómo se arbitra |
|---|---|---|
| Frescura del dato vs. cuotas de los proveedores de correo | QA-01 ↔ QA-11 | [ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md): notificación por *push* en lugar de sondeo uniforme |
| Carga analítica vs. latencia operacional | QA-09 ↔ QA-02 | [ADR-0003](../03-adr/ADR-0003-separacion-planos.md): planos de datos separados |
| Disponibilidad extrema vs. costo de infraestructura | QA-05 ↔ CRN-08 | [ADR-0002](../03-adr/ADR-0002-despliegue-multirregion.md): activo-activo acotado a tres regiones |
| Compartición en redes sociales vs. acceso solo para designados | RF-13 ↔ QA-12 | [AMB-10](07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución): dos mecanismos distintos, no uno |
| Escaneo del correo vs. minimización de datos personales | RF-02 ↔ QA-14 | [AMB-09](07-supuestos-y-carga-derivada.md#ambigüedades-del-enunciado-y-su-resolución): se persisten campos de reserva, nunca el cuerpo del mensaje |
| Consistencia de datos entre regiones vs. latencia de escritura | QA-05 ↔ QA-02 | Diferido a la [iteración 3](../02-proceso-add/iteracion-3-plan.md) |
