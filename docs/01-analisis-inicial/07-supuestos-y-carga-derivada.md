# 1.7 Supuestos, ambigüedades y carga derivada

Esta es la página central del **refinado de la especificación**. El enunciado da una narrativa y
unos pocos números; para diseñar hace falta bastante más. Acá está todo lo que hubo que resolver,
etiquetado para que se pueda auditar: qué se interpretó, qué se supuso y qué se dejó deliberadamente
para una decisión arquitectónica.

Regla que se siguió: **ningún número aparece en un escenario de calidad sin estar acá derivado o
supuesto**. Si una medida de respuesta no se puede rastrear a esta página o al texto literal del
enunciado, es un error.

---

## Ambigüedades del enunciado y su resolución

| ID | Lo que dice el enunciado | Por qué no alcanza | Resolución adoptada | Tipo |
|---|---|---|---|---|
| **AMB-01** | «El tiempo de respuesta desde la web debe ser de 800ms» | No dice de qué operación, ni en qué percentil, ni en qué punto se mide, ni bajo qué carga. Un promedio de 800 ms y un p99 de 800 ms son objetivos arquitectónicos completamente distintos | Se refina a: **carga del panel de viajes, p95 ≤ 800 ms y p99 ≤ 1.500 ms, medido extremo a extremo en el borde, bajo la carga pico derivada en S-05**. Ver [QA-02](04-escenarios-de-calidad.md#qa-02--tiempo-de-respuesta-del-panel-web) y el [presupuesto de latencia](#presupuesto-de-latencia-web-800-ms-p95) | Interpretación |
| **AMB-02** | «debe ser accesible en todo momento, tolerando un máximo de 5 minutos por mes de tiempo de inactividad no planificada» | No dice qué servicios entran en la medición. Si entraran las integraciones con terceros, el objetivo sería **imposible por construcción**: ningún proveedor de correo o de viaje ofrece un SLA compatible con 99,9884 % | Se acota la medición a las **funciones propias del sistema** (lectura del panel, alta manual, autenticación). La indisponibilidad de un tercero se trata como **degradación funcional** y no como inactividad, y tiene su propio escenario ([QA-06](04-escenarios-de-calidad.md#qa-06--indisponibilidad-de-un-proveedor-externo)). Formalizado en [ADR-0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | Decisión |
| **AMB-03** | «El sistema debe **sondear** y escanear el correo electrónico de los usuarios» + «las actualizaciones deben presentarse dentro de los 5 minutos» | Sondear 9 millones de buzones cada 5 minutos son **30.000 sondeos por segundo** sostenidos contra APIs de terceros (ver [cálculo](#por-qué-el-sondeo-uniforme-es-inviable)). Excede en órdenes de magnitud las cuotas publicadas de las APIs de correo y tiene costo prohibitivo | Se interpreta «sondear» como *obtener de forma continua*, sin prescribir el mecanismo. El mecanismo es una decisión arquitectónica: [ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md) adopta notificación por *push* del proveedor, con sondeo de reconciliación escalonado para los buzones que no lo soportan | Decisión |
| **AMB-04** | «2 millones de usuarios activos por semana, con un total de 15 millones de cuentas» | No da perfil de uso: sesiones por usuario, peticiones por sesión, ni distribución horaria. Sin eso no se puede dimensionar nada | Se derivan en los [supuestos de carga](#supuestos-de-carga) S-01 a S-06 | Supuesto |
| **AMB-05** | «el primer despliegue de contenido debe ocurrir en menos de 1.4 segundos» | No dice en qué red, en qué dispositivo ni en qué percentil. En fibra y en un dispositivo tope de gama es trivial; en 3G y gama baja es imposible | Se fija: **p75 de las sesiones reales, en 4G (RTT 150 ms, 1,6 Mbps) y dispositivo de gama media** (S-12) | Supuesto |
| **AMB-06** | «debe estar preparado arquitectónicamente para operar en el mercado internacional (multirregión)» | No dice cuántas regiones ni cuáles | Se fijan **tres regiones iniciales**: América, Europa y Asia-Pacífico. Es el mínimo que permite cubrir las tres franjas horarias principales y sostener el objetivo de disponibilidad ante la pérdida de una ([ADR-0002](../03-adr/ADR-0002-despliegue-multirregion.md)) | Supuesto |
| **AMB-07** | «la ejecución de consultas analíticas pesadas» para monetización | No da objetivo de latencia ni de frescura, ni dice si puede impactar en la operación | Se fija: **p95 ≤ 30 s de latencia de consulta, frescura ≤ 1 h, y degradación del p95 operacional < 5 %** ([QA-09](04-escenarios-de-calidad.md#qa-09--aislamiento-de-la-carga-analítica)) | Supuesto |
| **AMB-08** | «una vez que el viaje se completa, deben **archivarse o eliminarse** automáticamente de la vista principal» | «Archivar o eliminar» son cosas distintas con consecuencias de privacidad opuestas: una conserva el dato, la otra lo destruye | Se adopta **archivar por omisión** con retención de 36 meses (el dato histórico es insumo de RF-14), y **eliminar solo a pedido explícito del usuario**. La elección queda configurable por usuario (RF-15) | Decisión |
| **AMB-09** | «sondear y escanear el correo electrónico» vs. el atributo de seguridad y privacidad | Escanear correo es la mayor superficie de riesgo de privacidad del sistema, y el enunciado no dice qué se guarda del mensaje | Se adopta **minimización**: se extraen y persisten únicamente los campos de la reserva; **el cuerpo del mensaje nunca se persiste**. Para deduplicación se guarda un resumen criptográfico del mensaje, no el mensaje | Decisión |
| **AMB-10** | «interoperar […] con redes sociales para compartir itinerarios» vs. «asegurando que **solo personas específicas designadas** puedan visualizarlos» | Son dos requisitos contradictorios si se los lee como un único mecanismo: publicar en una red social es, por definición, no restringir a designados | Se separan en **dos mecanismos con modelos de confianza distintos**: (1) compartición con designados, que exige autenticación y verificación contra una lista de autorizados ([QA-12](04-escenarios-de-calidad.md#qa-12--compartición-de-un-itinerario-con-personas-designadas)); (2) publicación voluntaria a redes de un **resumen sin datos sensibles** —sin códigos de reserva, sin números de documento, sin domicilios— que el usuario confirma explícitamente | Decisión |

---

## Supuestos de carga

Partiendo únicamente de los dos datos que da el enunciado (15 M de cuentas, 2 M de usuarios activos
por semana) más el patrón de picos descrito (domingo-lunes, jueves-viernes, y eventos disruptivos).

| ID | Supuesto | Valor | Fundamento |
|---|---|---|---|
| **S-01** | Sesiones por usuario activo por semana | 5 | Un panel de viajes se consulta antes de viajar, durante el viaje y al recibir una notificación; 5 es un valor intermedio para una aplicación de uso episódico |
| **S-02** | Concentración del tráfico semanal en los 4 días pico | 70 % | El enunciado identifica domingo-lunes y jueves-viernes como picos marcados |
| **S-03** | Peticiones de API por sesión | 25 | Carga del panel, detalle de dos o tres reservas, y refrescos |
| **S-04** | Concentración del tráfico diario en las 3 horas de mayor uso | 40 % | Uso concentrado en la mañana temprano y la noche |
| **S-05** | Factor de ráfaga dentro de la hora pico | 1,8× | Las peticiones no se distribuyen uniformemente dentro de la hora |
| **S-06** | Multiplicador de un evento disruptivo masivo sobre el pico normal | 3× | El enunciado habla de «dramáticos picos de tráfico ante eventos disruptivos masivos» |
| **S-07** | Cuentas que conectan al menos un buzón de correo | 60 % | No todos los usuarios otorgan permiso de lectura de correo; el resto usa alta manual y sincronización con proveedores |
| **S-08** | Correos de viaje relevantes por buzón conectado por semana | 3 | Confirmaciones, cambios y recordatorios |
| **S-09** | Multiplicador de eventos de correo durante una disrupción | 10× | Una cancelación masiva genera una avalancha de correos simultáneos |
| **S-10** | Reservas históricas promedio por cuenta | 20 | Acumuladas a lo largo de la vida de la cuenta |
| **S-11** | Eventos de cambio por reserva, a lo largo de su vida | 10 | Confirmación, cambios de horario, recordatorios, *check-in*, cierre |
| **S-12** | Condiciones de referencia para la medición en móvil | 4G: RTT 150 ms, 1,6 Mbps de bajada; dispositivo de gama media | Representa al usuario mediano en movimiento, que es el caso de uso del enunciado |

### Derivación del tráfico de lectura

| Paso | Cálculo | Resultado |
|---|---|---|
| Sesiones por semana | 2.000.000 usuarios activos × 5 sesiones (S-01) | 10.000.000 sesiones/semana |
| Sesiones en el día pico | 10.000.000 × 70 % (S-02) ÷ 4 días | **1.750.000 sesiones/día pico** |
| Peticiones en el día pico | 1.750.000 × 25 (S-03) | 43.750.000 peticiones/día |
| Peticiones en la hora pico | 43.750.000 × 40 % (S-04) ÷ 3 horas ÷ 3.600 s | 1.620 peticiones/s |
| Pico instantáneo | 1.620 × 1,8 (S-05) | ≈ 2.900 peticiones/s |
| **Objetivo de dimensionamiento normal** | Redondeo con margen | **3.000 peticiones/s sostenidas** |
| **Objetivo ante disrupción masiva** | 3.000 × 3 (S-06) | **9.000 peticiones/s sostenidas** |

Estos son los números que usan [QA-02](04-escenarios-de-calidad.md#qa-02--tiempo-de-respuesta-del-panel-web)
y [QA-04](04-escenarios-de-calidad.md#qa-04--pico-de-carga-por-disrupción-masiva).

### Derivación del tráfico de ingesta de correo

| Paso | Cálculo | Resultado |
|---|---|---|
| Buzones conectados | 15.000.000 cuentas × 60 % (S-07) | **9.000.000 buzones** |
| Correos de viaje por semana | 9.000.000 × 3 (S-08) | 27.000.000 correos/semana |
| Eventos de correo, promedio | 27.000.000 ÷ 604.800 s | ≈ 45 eventos/s |
| Eventos de correo en pico de disrupción | 45 × 10 (S-09) | **≈ 450 eventos/s** |

### Por qué el sondeo uniforme es inviable

Este cálculo es el que justifica [ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md), y es el
hallazgo más importante del refinado:

| Enfoque | Cálculo | Carga resultante |
|---|---|---|
| Sondeo uniforme cada 5 min (lectura literal del enunciado) | 9.000.000 buzones ÷ 300 s | **30.000 sondeos/s sostenidos, 24 × 7** |
| | × 2 llamadas de API por sondeo | **60.000 llamadas/s** ≈ 5.180 millones de llamadas por día |
| Notificación por *push* del proveedor | Solo los buzones con actividad relevante | **45 eventos/s** de promedio, 450 en pico |

La diferencia es de **tres órdenes de magnitud**. El sondeo uniforme excede ampliamente las cuotas
publicadas de las APIs de correo y su costo es prohibitivo para una *startup*; además, el 99,99 %
de esos sondeos devolvería «nada nuevo».

### Derivación del volumen de datos

| Concepto | Cálculo | Resultado |
|---|---|---|
| Reservas en el plano operacional | 15.000.000 cuentas × 20 (S-10) | 300.000.000 reservas |
| Datos netos | 300.000.000 × 4 KB por reserva normalizada | ≈ 1,2 TB |
| Con índices y estructuras auxiliares | × 3,3 | ≈ 4 TB por región |
| Almacenamiento provisionado total | × 3 regiones (AMB-06) | **≈ 12 TB** |
| Registros en el plano analítico | 300.000.000 × 11 eventos (S-11, incluida el alta) | **≈ 3.300 millones de registros** |
| Crecimiento anual del plano analítico | 15.000.000 cuentas × 6 reservas nuevas/año × 11 eventos | ≈ 1.000 millones de registros/año |

---

## Presupuestos derivados

Un objetivo numérico global sin presupuesto por tramo no es verificable durante el diseño: no
permite saber, al tomar una decisión, si deja margen o si ya lo consumió. Estos tres presupuestos
se usan como criterio de aceptación en las iteraciones 1 y 3.

### Presupuesto de latencia web (800 ms p95)

| Tramo | Presupuesto | Nota |
|---|---|---|
| DNS, TLS y red del cliente hasta el borde | 120 ms | Mitigado acercando el borde al usuario (AMB-06: tres regiones) |
| Borde y *gateway*: enrutamiento, autenticación y autorización | 60 ms | Validación local del token, sin ida al proveedor de identidad |
| BFF web: composición de la respuesta | 70 ms | |
| Servicio de itinerario | 120 ms | |
| Almacén de lectura, con 90 % de aciertos de caché | 80 ms | El 10 % de fallos de caché consume el margen de reserva |
| Serialización y red de vuelta al cliente | 150 ms | |
| **Reserva** | **200 ms** | 25 % del total, para fallos de caché y variabilidad de red |
| **Total** | **800 ms** | |

### Presupuesto de frescura (5 minutos)

| Tramo | Presupuesto |
|---|---|
| La fuente genera el cambio → la notificación llega a Trotamundos | 60 s |
| Validación, encolado y despacho | 15 s |
| Obtención del detalle en el proveedor, o descarga del mensaje de correo | 45 s |
| Extracción, normalización y deduplicación | 45 s |
| Persistencia e invalidación de caché | 15 s |
| Emisión de la notificación y actualización del cliente | 60 s |
| **Reserva** | **60 s** |
| **Total** | **300 s (5 min)** |

### Presupuesto de error de disponibilidad

El objetivo del enunciado, convertido a porcentaje:

| Período | Inactividad tolerada | Disponibilidad equivalente |
|---|---|---|
| Mes (30 días = 43.200 min) | 5 min | **99,9884 %** |
| Año | 60 min | 99,9886 % |

Reparto del presupuesto mensual entre planos, para poder atribuir el consumo:

| Plano | Presupuesto | Escenario asociado |
|---|---|---|
| Borde, DNS y enrutamiento global | 1,0 min | — |
| Plano de aplicación (servicios y BFF) | 2,0 min | QA-07 (despliegues) |
| Plano de datos (almacenes y replicación) | 2,0 min | QA-05 (pérdida de región, tope 1,5 min) |
| **Total** | **5,0 min** | |

Consecuencia directa: con 5 minutos al mes **no existe ventana de mantenimiento posible**. Esto no
es un detalle de operación, es un driver estructural, y es el origen de CRN-04 y de
[QA-07](04-escenarios-de-calidad.md#qa-07--despliegue-de-una-nueva-versión).
