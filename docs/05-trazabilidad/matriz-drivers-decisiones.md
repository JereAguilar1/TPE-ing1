# 5. Matriz de trazabilidad: driver → decisión → vista

Esta matriz es el artefacto que hace verificable a
[QA-16](../01-analisis-inicial/04-escenarios-de-calidad.md#qa-16--trazabilidad-de-una-decisión-al-código)
(«100 % de los drivers referenciados por al menos un ADR») y a CRN-07. Se recorre en los dos
sentidos: desde un driver, para saber qué decisión lo atiende; y desde un elemento del sistema,
para saber por qué existe.

**Estado al cierre de la iteración 1:** 38 de 53 drivers están referenciados por al menos un ADR
(72 %). Los 15 restantes son los que las iteraciones 2 a 4 tienen asignados, y están listados en
[huecos de trazabilidad](#huecos-de-trazabilidad).

---

## Driver → decisión

### Requisitos funcionales

| Driver | ADR que lo atiende | Elemento responsable | Estado |
|---|---|---|---|
| RF-01 Conectar cuenta de correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | `identity-access` | 🟨 |
| RF-02 Obtener mensajes de viaje | [0004](../03-adr/ADR-0004-obtencion-de-correo.md) | `mail-ingest` | 🟨 |
| RF-03 Extraer y normalizar reservas | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | `booking-extraction` | 🟨 |
| RF-04 Filtros y whitelists | — *(iteración 2)* | `mail-ingest` | ⬜ |
| RF-05 Sincronizar con proveedores | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | `provider-sync` | 🟨 |
| RF-06 Gestión manual de reservas | — *(iteración 2)* | `itinerary` | ⬜ |
| RF-07 Agrupar reservas en viajes | — *(iteración 2)* | `itinerary` | ⬜ |
| RF-08 Ciclo de vida del viaje | — *(iteración 2)* | `itinerary` | ⬜ |
| RF-09 Visualizar el panel | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) | `bff-web`, `bff-mobile` | 🟨 |
| RF-10 Notificar actualizaciones | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) | `notification` | 🟨 |
| RF-11 Compartir con designados | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | `sharing` | 🟨 |
| RF-12 Derivar a la agencia | — *(iteración 2)* | `support-liaison` | ⬜ |
| RF-13 Publicar en redes sociales | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | `sharing` | 🟨 |
| RF-14 Consultas analíticas | [0003](../03-adr/ADR-0003-separacion-planos.md) | `analytics-store` | 🟨 |
| RF-15 Preferencias del usuario | — *(iteración 2)* | `preferences` | ⬜ |

### Escenarios de atributos de calidad

| Driver | ADR que lo atiende | Vista donde se ve | Estado |
|---|---|---|---|
| QA-01 Propagación ≤ 5 min | [0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) | [C&C: camino de ingesta](../04-vistas/vista-cyc-nivel-1.md#camino-de-ingesta--sostiene-qa-01) | 🟨 |
| QA-02 Panel web ≤ 800 ms | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0003](../03-adr/ADR-0003-separacion-planos.md), [0002](../03-adr/ADR-0002-despliegue-multirregion.md) | [C&C: camino de lectura](../04-vistas/vista-cyc-nivel-1.md#camino-de-lectura--sostiene-qa-02-y-qa-03) | 🟨 |
| QA-03 FCP móvil ≤ 1,4 s | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) | [C&C](../04-vistas/vista-cyc-nivel-1.md) | 🟨 |
| QA-04 Pico de disrupción | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md), [0003](../03-adr/ADR-0003-separacion-planos.md) | [C&C: frontera de degradación](../04-vistas/vista-cyc-nivel-1.md#frontera-de-degradación--sostiene-qa-04) | 🟨 |
| QA-05 Pérdida de una región | [0002](../03-adr/ADR-0002-despliegue-multirregion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | [Despliegue](../04-vistas/vista-despliegue-nivel-1.md#qué-pasa-si-se-cae-una-región) | 🟨 ⚠ R-1 |
| QA-06 Proveedor externo caído | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | [C&C](../04-vistas/vista-cyc-nivel-1.md) | 🟨 |
| QA-07 Despliegue sin inactividad | — *(iteración 3)* | [Despliegue](../04-vistas/vista-despliegue-nivel-1.md) | ⬜ |
| QA-08 Crecimiento de la base | — *(iteración 3)* | [Despliegue](../04-vistas/vista-despliegue-nivel-1.md) | ⬜ |
| QA-09 Aislar la analítica | [0003](../03-adr/ADR-0003-separacion-planos.md) | [Despliegue](../04-vistas/vista-despliegue-nivel-1.md) | 🟩 |
| QA-10 Proveedor de viaje nuevo | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | [Módulos: regla R2](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) | 🟩 |
| QA-11 Formato de correo desconocido | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | [Módulos: regla R3](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) | 🟨 ⚠ R-2 |
| QA-12 Solo personas designadas | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | [Contexto: E-03](../04-vistas/vista-contexto.md) | 🟩 |
| QA-13 Custodia de tokens | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | [Módulos: regla R5](../04-vistas/vista-modulos-nivel-1.md#reglas-de-dependencia) | 🟨 |
| QA-14 Auditoría de datos personales | — *(iteración 4)* | — | ⬜ |
| QA-15 Nuevo medio de transporte | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | [Módulos](../04-vistas/vista-modulos-nivel-1.md) | 🟨 |
| QA-16 Trazabilidad al código | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | esta matriz | 🟨 |
| QA-17 Contexto de ubicación | — *(iteración 4)* | — | ⬜ |
| QA-18 Región nueva | [0002](../03-adr/ADR-0002-despliegue-multirregion.md) *(parcial: topología sí, localización no)* | [Despliegue](../04-vistas/vista-despliegue-nivel-1.md) | ⬜ |

### Restricciones

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CON-01 ADD con ≥ 4 iteraciones | [Plan de iteraciones](../00-gestion/plan-de-iteraciones.md) | 🟨 |
| CON-02 ADRs en MADR | [Plantilla](../03-adr/plantilla-madr.md) y los 9 ADRs | 🟩 |
| CON-03 Wiki con evolución y labor | [Bitácora](../00-gestion/bitacora.md), [convenciones](../00-gestion/equipo.md#convenciones-de-trabajo) | 🟩 |
| CON-04 Spec-driven development | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | 🟨 |
| CON-05 Acotar el prototipo | — *(2da entrega)* | ⬜ |
| CON-06 Alojar el módulo avanzado | [Punto de extensión](../02-proceso-add/iteracion-1/README.md#el-punto-de-extensión-para-la-2da-entrega) | 🟨 |
| CON-07 APIs estándar | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | 🟩 |
| CON-08 Autorización explícita del correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | 🟩 |
| CON-09 Equipo de 4 | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) vía CON-A4 | 🟩 |
| CON-10 Normativa de datos personales | — *(iteración 4)* | ⬜ |

### Inquietudes arquitectónicas

| Driver | ADR / mecanismo | Estado |
|---|---|---|
| CRN-01 Estructura general | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) y toda la iteración 1 | 🟩 |
| CRN-02 Asignar trabajo a 4 personas | [Mapa de responsabilidad](../04-vistas/vista-modulos-nivel-1.md#mapa-de-responsabilidad-por-integrante) | 🟩 |
| CRN-03 Presupuesto de error | [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | 🟨 |
| CRN-04 Despliegue sin inactividad | — *(iteración 3)* | ⬜ |
| CRN-05 Secretos y tokens | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | 🟨 |
| CRN-06 Pruebas y contratos | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | 🟨 |
| CRN-07 Trazabilidad | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) y esta matriz | 🟩 |
| CRN-08 Costo de infraestructura | [0002](../03-adr/ADR-0002-despliegue-multirregion.md) | 🟨 ⚠ R-3 |
| CRN-09 Cuotas de terceros | [0004](../03-adr/ADR-0004-obtencion-de-correo.md) | 🟨 |
| CRN-10 Internacionalización | — *(iteración 4)* | ⬜ |

---

## Decisión → drivers (sentido inverso)

| ADR | Decisión | Drivers que atiende |
|---|---|---|
| [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) | Microservicios orientados a eventos, granularidad acotada | QA-04, QA-05, QA-09, QA-10, QA-15, RF-10, CON-09, CRN-01, CRN-02, CRN-08 |
| [0002](../03-adr/ADR-0002-despliegue-multirregion.md) | Activo-activo en tres regiones | QA-05, QA-02, QA-03, QA-18, CRN-08 |
| [0003](../03-adr/ADR-0003-separacion-planos.md) | Planos operacional y analítico separados | QA-09, QA-02, QA-04, RF-14 |
| [0004](../03-adr/ADR-0004-obtencion-de-correo.md) | *Push* con reconciliación escalonada | QA-01, QA-04, RF-02, CRN-09, CRN-08 |
| [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) | Un BFF por tipo de cliente | QA-02, QA-03, QA-17, RF-09 |
| [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) | Anticorrupción con adaptadores como complementos | QA-10, QA-11, QA-15, QA-06, RF-03, RF-05, CON-07 |
| [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) | OIDC, delegación OAuth, lista de designados | QA-12, QA-13, RF-01, RF-11, RF-13, CON-08, CRN-05 |
| [0008](../03-adr/ADR-0008-alcance-disponibilidad.md) | Alcance de la medición de disponibilidad | QA-05, QA-06, CRN-03 |
| [0009](../03-adr/ADR-0009-contratos-spec-driven.md) | Contratos como artefactos de primera clase | CON-04, CON-02, QA-16, QA-10, CRN-06, CRN-07, CRN-14 |

---

## Elemento → por qué existe

Este es el recorrido que QA-16 mide: «¿por qué existe este elemento?», respondido en menos de 10
minutos.

| Elemento | Existe porque… | ADR |
|---|---|---|
| `edge` | El presupuesto de latencia asigna 120 ms a la red del cliente, y eso exige estar cerca del usuario | [0002](../03-adr/ADR-0002-despliegue-multirregion.md) |
| `api-gateway` | La autenticación y la limitación de tasa tienen que ocurrir antes de llegar al dominio | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) |
| `bff-web` / `bff-mobile` | Los presupuestos de QA-02 y QA-03 son incompatibles con un contrato único | [0005](../03-adr/ADR-0005-capa-de-clientes-bff.md) |
| `itinerary` | El modelo canónico necesita un dueño único; es la frontera donde convergen las tres fuentes de reservas | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) |
| `identity-access` | QA-13 exige que un único elemento pueda descifrar los tokens de correo | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) |
| `mail-ingest` | Es E/S contra terceros con perfil de ráfaga: escala distinto del cómputo de extracción | [0004](../03-adr/ADR-0004-obtencion-de-correo.md) |
| `booking-extraction` | Es cómputo; separarlo de la E/S permite escalarlo por separado y contener la fragilidad de los formatos | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) |
| `provider-sync` | QA-10 exige agregar un proveedor sin modificar nada existente | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) |
| `sharing` | AMB-10 reveló que compartir y publicar son dos mecanismos con dos modelos de confianza | [0007](../03-adr/ADR-0007-identidad-y-comparticion.md) |
| `notification` | QA-01 y QA-04 exigen que la emisión de notificaciones escale por separado del panel | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) |
| `support-liaison` | RF-12 requiere armar el caso con contexto del viaje y hablar con un tercero | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) |
| `preferences` | RF-08, RF-12 y RF-15 necesitan configuración por usuario, consultada en caminos distintos | [0001](../03-adr/ADR-0001-estilo-arquitectonico.md) |
| `event-pipeline` / `analytics-store` | QA-09 exige que la analítica no comparta recursos con la operación | [0003](../03-adr/ADR-0003-separacion-planos.md) |
| `modelo-canonico` | QA-15 exige un punto de extensión del dominio independiente de todo proveedor | [0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md) |
| `contratos` | CON-04 exige especificaciones contractuales verificables | [0009](../03-adr/ADR-0009-contratos-spec-driven.md) |

---

## Huecos de trazabilidad

Los drivers **sin** ADR al cierre de la iteración 1, con su iteración asignada. Esta lista debe
quedar vacía al cerrar la iteración 4 (criterio de salida 1 de la
[iteración 4](../02-proceso-add/iteracion-4-plan.md#criterios-de-salida--y-cierre-de-la-1ra-entrega)).

| Driver | Iteración asignada |
|---|---|
| RF-04, RF-06, RF-07, RF-08, RF-12, RF-15 | 2 |
| QA-07, QA-08 | 3 |
| QA-14, QA-17, QA-18 *(localización)* | 4 |
| CON-10 | 4 |
| CRN-04 | 3 |
| CRN-10 | 4 |
| CON-05 | 2da entrega |
