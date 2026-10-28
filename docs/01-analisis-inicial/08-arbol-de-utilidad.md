# 1.8 Árbol de utilidad

El árbol de utilidad organiza los escenarios de calidad en una jerarquía
`Utilidad → Atributo → Refinamiento → Escenario` y puntúa cada hoja con el par
**(valor de negocio, riesgo técnico)** en escala Alto / Medio / Bajo. Su función es decidir
**qué escenarios atacar primero**: los que están altos en los dos ejes son los que pueden forzar
cambios estructurales si se descubren tarde.

- **Valor de negocio:** A = imprescindible; M = importante pero no crítico; B = deseable.
- **Riesgo técnico:** A = nos quita el sueño lograrlo; M = preocupa; B = confianza alta.

## Árbol

```
Utilidad
├── Rendimiento y latencia
│   ├── Frescura del dato de viaje
│   │   └── QA-01 Propagación de una actualización de viaje ............. (A, A)
│   ├── Tiempo de respuesta interactivo
│   │   ├── QA-02 Tiempo de respuesta del panel web .................... (A, M)
│   │   └── QA-03 Primer despliegue de contenido en móvil ............... (M, M)
│   └── Comportamiento bajo ráfaga
│       └── QA-04 Pico de carga por disrupción masiva ................... (A, A)
├── Disponibilidad
│   ├── Tolerancia a falla de infraestructura
│   │   └── QA-05 Pérdida de una región completa ........................ (A, A)
│   ├── Tolerancia a falla de terceros
│   │   └── QA-06 Indisponibilidad de un proveedor externo .............. (A, M)
│   └── Continuidad durante el cambio
│       └── QA-07 Despliegue de una nueva versión ....................... (M, M)
├── Escalabilidad
│   ├── Crecimiento de la demanda
│   │   └── QA-08 Crecimiento de la base de cuentas ..................... (M, M)
│   └── Convivencia de cargas heterogéneas
│       └── QA-09 Aislamiento de la carga analítica ..................... (A, M)
├── Interoperabilidad
│   ├── Incorporación de proveedores de viaje
│   │   └── QA-10 Integración de un proveedor de viaje nuevo ............ (A, M)
│   └── Heterogeneidad del correo
│       └── QA-11 Formato de correo desconocido ......................... (A, A)
├── Seguridad y privacidad
│   ├── Control de acceso a itinerarios compartidos
│   │   └── QA-12 Compartición con personas designadas ................. (A, M)
│   ├── Custodia de credenciales delegadas
│   │   └── QA-13 Intento de acceso a las credenciales de correo ........ (A, A)
│   └── Cumplimiento y rendición de cuentas
│       └── QA-14 Auditoría de acceso a datos personales ............... (M, B)
├── Evolucionabilidad y mantenibilidad
│   ├── Extensión del dominio
│   │   └── QA-15 Incorporar un nuevo medio de transporte .............. (A, M)
│   └── Comprensibilidad del diseño
│       └── QA-16 Trazabilidad de una decisión al código ............... (M, B)
└── Usabilidad e internacionalización
    ├── Riqueza de la interfaz móvil
    │   └── QA-17 Contexto de ubicación en el dispositivo móvil ........ (B, B)
    └── Preparación para operar en varios mercados
        └── QA-18 Incorporación de una región nueva .................... (M, M)
```

## Tabla con justificación de puntajes

Un puntaje sin justificación es una adivinanza, así que cada uno lleva la suya.

| Atributo | Refinamiento | Escenario | (Valor, Riesgo) | Justificación |
|---|---|---|---|---|
| Rendimiento | Frescura del dato | **QA-01** Propagación de una actualización en ≤ 5 min (p95) | **(A, A)** | A de negocio: la propuesta de valor entera es ser el único punto de verdad, y un punto de verdad desactualizado no sirve (MN-1). A de riesgo: depende de terceros que no controlamos, y el sondeo literal del enunciado es inviable por cuotas |
| Rendimiento | Tiempo de respuesta | **QA-02** Panel web p95 ≤ 800 ms a 3.000 req/s | (A, M) | A de negocio: es el camino que recorre todo usuario en toda sesión. M de riesgo: el presupuesto de latencia cierra con 200 ms de reserva usando caché y réplicas de lectura, que son técnicas conocidas |
| Rendimiento | Tiempo de respuesta | **QA-03** FCP móvil ≤ 1,4 s (p75) en 4G | (M, M) | M de negocio: afecta la primera impresión, pero el usuario ya decidió abrir la app. M de riesgo: alcanzable con renderizado progresivo y carga diferida, pero sensible a la red del usuario |
| Rendimiento | Ráfaga | **QA-04** 9.000 req/s y 450 eventos/s durante 30 min | **(A, A)** | A de negocio: el pico ocurre justo cuando el usuario más necesita el sistema; caerse en una disrupción climática es el peor momento posible (MN-3). A de riesgo: el pico es súbito y simultáneo en los dos planos (ingesta y lectura), y el escalado reactivo puede llegar tarde |
| Disponibilidad | Falla de infraestructura | **QA-05** Pérdida de una región, 0 pérdida de datos, ≤ 1,5 min de presupuesto | **(A, A)** | A de negocio: 5 min/mes es un objetivo contractual del enunciado y la base de la confianza del usuario. A de riesgo: activo-activo exige resolver consistencia entre regiones, que es el problema técnico más difícil del sistema |
| Disponibilidad | Falla de terceros | **QA-06** Aislamiento de un proveedor caído | (A, M) | A de negocio: con 12 integraciones externas, que alguna esté caída es el estado normal, no la excepción. M de riesgo: cortacircuitos y mamparos son patrones maduros y bien entendidos |
| Disponibilidad | Continuidad en el cambio | **QA-07** Despliegue sin inactividad | (M, M) | M de negocio: el usuario no lo ve, pero habilita la velocidad de evolución. M de riesgo: estándar en la industria, pero se complica con cambios de esquema de datos |
| Escalabilidad | Crecimiento | **QA-08** Duplicar usuarios en 12 meses | (M, M) | M de negocio: es crecimiento proyectado, no demanda presente. M de riesgo: el particionamiento por usuario es natural en este dominio, el riesgo real está en el plano analítico |
| Escalabilidad | Cargas heterogéneas | **QA-09** Analítica sin degradar > 5 % la operación | (A, M) | A de negocio: la analítica es una línea de ingresos explícita (MN-4) y no puede costarle la experiencia al usuario. M de riesgo: separar planos es una solución conocida; el riesgo está en la frescura y el costo |
| Interoperabilidad | Proveedores de viaje | **QA-10** Proveedor nuevo sin tocar nada existente, ≤ 40 h-p | (A, M) | A de negocio: cada integración nueva amplía la cobertura del punto de verdad y es un acuerdo comercial. M de riesgo: el patrón de adaptadores resuelve el problema estructural; la variabilidad real está en los datos de cada proveedor |
| Interoperabilidad | Heterogeneidad del correo | **QA-11** Formato desconocido sin corromper el itinerario | **(A, A)** | A de negocio: la ingesta por correo es la vía que no requiere acuerdo comercial con nadie, y un dato erróneo en el itinerario destruye la confianza más que un dato faltante. A de riesgo: los formatos de correo son innumerables, cambian sin aviso y no hay contrato; es el punto más frágil del sistema |
| Seguridad | Itinerarios compartidos | **QA-12** 100 % de no designados denegados | (A, M) | A de negocio: el enunciado lo pide explícitamente y una fuga de itinerarios es un incidente de privacidad. M de riesgo: es control de acceso convencional |
| Seguridad | Credenciales delegadas | **QA-13** Tokens de correo no descifrables por un servicio comprometido | **(A, A)** | A de negocio: el sistema custodia las llaves del correo de 9 millones de personas; una filtración masiva termina con la empresa. A de riesgo: superficie amplia, 10+ servicios, y el modelo de amenaza incluye al atacante que ya está dentro |
| Seguridad | Cumplimiento | **QA-14** Inventario en 72 h, supresión en 30 días | (M, B) | M de negocio: es obligación legal (CON-10) pero no diferencia el producto. B de riesgo: se resuelve con disciplina de catálogo de datos y una decisión temprana sobre identificadores |
| Evolucionabilidad | Extensión del dominio | **QA-15** Nuevo medio de transporte, ≤ 2 elementos tocados | (A, M) | A de negocio: el enunciado lo declara expectativa explícita y es la vía de expansión del producto (MN-7). M de riesgo: depende de acertar el modelo canónico en la iteración 2; si se acierta es barato, si no, caro |
| Evolucionabilidad | Comprensibilidad | **QA-16** Trazabilidad driver → código en ≤ 10 min | (M, B) | M de negocio: habilita la incorporación de gente y las evaluaciones futuras. B de riesgo: es cuestión de disciplina documental, no de dificultad técnica |
| Usabilidad | Interfaz móvil rica | **QA-17** Segmento pertinente visible sin interacción, 90 % | (B, B) | B de negocio: es una mejora de comodidad, no un motivo de adopción. B de riesgo: el GPS es una capacidad estándar de la plataforma móvil |
| Internacionalización | Varios mercados | **QA-18** Región nueva sin tocar lógica de negocio | (M, M) | M de negocio: habilita MN-5, pero no hay mercado comprometido todavía. M de riesgo: barato si se previene desde el inicio, carísimo si se retrofitea; el riesgo es de disciplina, no técnico |

## Distribución de los escenarios

| | Riesgo técnico Alto | Riesgo técnico Medio | Riesgo técnico Bajo |
|---|---|---|---|
| **Valor Alto** | **QA-01, QA-04, QA-05, QA-11, QA-13** | QA-02, QA-06, QA-09, QA-10, QA-12, QA-15 | — |
| **Valor Medio** | — | QA-03, QA-07, QA-08, QA-18 | QA-14, QA-16 |
| **Valor Bajo** | — | — | QA-17 |

## Escenarios significativos para la arquitectura (ASRs)

Los cinco escenarios del cuadrante **(Alto, Alto)** son los **ASRs** del sistema, y son los que se
atacan primero:

| ASR | Escenario | Qué puede forzar | Iteración que lo trata |
|---|---|---|---|
| **ASR-1** | QA-01 — propagación en ≤ 5 min | El mecanismo de obtención de datos de las fuentes externas, y por lo tanto todo el plano de ingesta | 1 ([ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md)), refinado en 3 |
| **ASR-2** | QA-04 — pico de disrupción masiva | La elasticidad del sistema y la separación entre lo que puede degradarse y lo que no | 1 ([ADR-0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [ADR-0003](../03-adr/ADR-0003-separacion-planos.md)), refinado en 3 |
| **ASR-3** | QA-05 — pérdida de una región | La topología de despliegue y el modelo de consistencia de datos | 1 ([ADR-0002](../03-adr/ADR-0002-despliegue-multirregion.md)), refinado en 3 |
| **ASR-4** | QA-11 — formato de correo desconocido | La estructura del subsistema de extracción y la política de confianza en el dato | 1 ([ADR-0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md)), refinado en 2 y 4 |
| **ASR-5** | QA-13 — custodia de tokens de correo | La ubicación de los secretos y la segmentación de privilegios entre servicios | 1 ([ADR-0007](../03-adr/ADR-0007-identidad-y-comparticion.md)), refinado en 4 |

**Por qué los cinco se tocan en la iteración 1.** Ninguno se resuelve del todo ahí —eso es lo que
hacen las iteraciones 2 a 4— pero los cinco tienen la propiedad de que **una decisión estructural
equivocada los vuelve inalcanzables después**. Si la iteración 1 eligiera un monolito de región
única con sondeo uniforme, ninguna cantidad de refinamiento posterior salvaría a ASR-1, ASR-2 ni
ASR-3. Por eso la primera iteración se evalúa por si *habilita* los ASRs, no por si los cumple.

Los escenarios de cuadrante (Alto, Medio) son los candidatos a una evaluación de arquitectura
posterior; los de riesgo Bajo no justifican análisis dedicado y se verifican por inspección.
