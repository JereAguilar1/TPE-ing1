---
estado: aceptado
fecha: 2026-10-29
decisores: Ivo Iriarte, Jeremias Aguilar
consultados: Francisco Lozano, Juan Emilio Pardo
informados: equipo completo
iteracion: 3
drivers: CRN-03, QA-05, QA-06, QA-07, QA-09, CON-09
---

# ADR-0025: Observabilidad con OpenTelemetry, correlación extremo a extremo y gobierno por presupuesto de error

## Contexto y planteo del problema

En una arquitectura de 13 servicios operacionales distribuidos en tres regiones activas y conectados
por colas de eventos ([ADR-0001](ADR-0001-estilo-arquitectonico.md), [ADR-0002](ADR-0002-despliegue-multirregion.md)),
una falla rara vez se presenta como «un servidor apagado»: aparece como degradación parcial de cola,
un proveedor que responde lento o un problema de DNS regional invisible para las métricas internas de
CPU. Al mismo tiempo:

* **[ADR-0008](ADR-0008-alcance-disponibilidad.md)** exige medir los **`5,0 minutos/mes`** de
  presupuesto de error **desde la perspectiva del cliente**, no solo dentro del centro de datos.
* **`QA-05`** requiere detectar la caída de una región en **`≤ 30 segundos`** incluso de madrugada.
* **`CON-09`** limita el equipo a **cuatro personas**: un esquema de alertas ruidoso por umbrales
  estáticos de máquina produce fatiga operativa inmediata, mientras que almacenar el `100 %` de las
  trazas de `3.000 req/s` dispara innecesariamente el gasto mensual (`CRN-08`).

## Drivers de decisión

* **CRN-03** — trazabilidad distribuida de una operación a través de servicios y colas, SLIs/SLOs por
  función crítica y presupuesto de error accionable.
* **QA-05 / AMB-02 ([ADR-0008](ADR-0008-alcance-disponibilidad.md))** — medición centrada en el usuario y detección de caída regional en `≤ 30 s`.
* **QA-07** — señales en tiempo real cada `30 s` para gobernar la reversión automática canaria.
* **CON-09 / CRN-08** — mínima carga operativa para 4 integrantes y costo acotado de telemetría.

## Opciones consideradas

* **Y1** — Monitoreo clásico centrado en recursos de infraestructura (CPU, memoria, disco) por nodo.
* **Y2** — Métricas internas de aplicación (RED) sin propagación en el *broker* ni sondas externas.
* **Y3** — Telemetría unificada OpenTelemetry con `correlation_id` propagado en HTTP y AsyncAPI,
  muestreo de cola en trazas, monitoreo sintético cada `15 s` + RUM agregado y alertas por tasa de
  consumo (*multi-window burn rate*) con freno automático de despliegues.

## Resultado de la decisión

Se adopta **Y3**:

1. **Tres señales correlacionadas con `correlation_id` obligatorio.** `edge` valida o genera el
   identificador W3C `traceparent` / `correlation_id` en toda petición entrante y cada productor lo
   copia al campo `idDeCorrelacion` del sobre de eventos (`ADR-0009`). Todos los servicios emiten
   mediante OpenTelemetry:
   * **Registros estructurados JSON** con esquema uniforme (`timestamp`, `servicio`, `region`,
     `correlation_id`, `severidad`, `codigo_evento`) y **prohibición estricta de volcar PII, cuerpos
     de correo o tokens** (`QA-14`).
   * **Métricas de nivel de servicio** (latencia por histogramas nativos, tasa de errores, edad de
     cola por carril, estado de cortacircuitos y consumo de cuota externa).
   * **Trazas distribuidas con muestreo de cola (*tail-based sampling*):** el colector regional retiene
     el **`1 %`** de las trazas exitosas rápidas y el **`100 %`** de cualquier traza con error, con
     duración `> 800 ms` (`> 180 s` en ingesta) o ejecutada en modo degradado.
2. **Medición externa de la experiencia real (`ADR-0008` §3).** Se combinan dos fuentes fuera de los
   clústeres regionales:
   * **Sondas sintéticas activas cada `15 s`** desde `6` ubicaciones globales independientes contra
     las rutas de salud semántica y lectura sintética de las tres regiones. Dos fallos consecutivos
     desde mayoría de sondas (`≤ 30 s`) declaran la región degradada ante el DNS global (`QA-05`).
   * **Telemetría real de cliente (RUM) agregada y sin identificadores personales** en `app-web` y
     `app-movil` para medir `QA-02` (`800 ms`), `QA-03` (`FCP ≤ 1,4 s` en 4G) y errores de red que no
     llegan al *backend*.
3. **Catálogo formal de SLOs y gobierno activo del presupuesto de error.** Los `8` SLOs del
   sistema quedan especificados en
   [pruebas-de-carga-y-slos.md](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md#catálogo-de-indicadores-y-objetivos-de-nivel-de-servicio-slis--slos).
   Las alertas se disparan exclusivamente por **velocidad de consumo del presupuesto (*burn rate*)**:
   * *Crítica (despierta a guardia):* consumo **`≥ 14,4×`** sostenido en ventanas de `5 min` y `1 h`
     (agotaría el presupuesto mensual en `2` días); si hay un canario activo, dispara reversión
     inmediata ([ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md)).
   * *Advertencia (horario laboral):* consumo **`≥ 3×`** sostenido en `30 min` y `6 h`.
   * *Política operativa de bloqueo:* si el consumo acumulado en los últimos `30` días supera el
     **`75 %` (`3,75 min` de `5,0 min`)**, la tubería de CI/CD bloquea automáticamente despliegues
     funcionales no urgentes y solo permite cambios de confiabilidad, corrección de defectos críticos
     o parches de seguridad.

### Consecuencias

* **Bueno,** porque cualquier incidente («¿por qué este cambio de vuelo tardó 4 minutos?») se
  reconstruye de punta a punta con una única consulta por `correlation_id` desde el *webhook* hasta la
  notificación enviada.
* **Bueno,** porque protege la atención de un equipo de 4 personas despertando únicamente ante síntomas
  que comprometen los SLOs del viajero, con costo de almacenamiento de trazas contenido (`~USD 1.700/mes`
  a escala plena).
* **Malo,** porque exige mantener instrumentados los propagadores de contexto en clientes HTTP y
  productores/consumidores del *broker* mediante una biblioteca interna liviana de telemetría (permitida
  por [ADR-0001](ADR-0001-estilo-arquitectonico.md) al no contener lógica de dominio).

### Confirmación

* **Verificación en CI:** prueba de integración que inyecta un `WebhookRecibido` sintético y comprueba
  que el mismo `correlation_id` aparece en las trazas/registros de `mail-ingest`,
  `booking-extraction`, `itinerary-escritura` y `notification`, y que ningún registro contiene
  direcciones de correo ni nombres de pasajeros en texto plano.
* **Simulacro de presupuesto agotado:** verificar en la tubería de despliegue del prototipo que un
  consumo simulado del `80 %` del presupuesto mensual rechaza un *merge/release* funcional normal y
  habilita únicamente un despliegue etiquetado como corrección de emergencia.

## Pros y contras de las opciones

### Y1 — Monitoreo por recursos de máquina

* Bueno, porque viene incluido por defecto en cualquier proveedor de nube.
* **Malo, porque no mide disponibilidad percibida por el usuario ni rastrea colas asíncronas, y genera
  alertas falsas constantes.**

### Y2 — Métricas internas de aplicación sin sondas ni correlación en *broker*

* Bueno, porque mide tasas de petición, error y duración por servicio individual.
* **Malo, porque queda ciego ante cortes de DNS/borde, no detecta caídas regionales en horas sin
  tráfico y pierde el rastro al cruzar un tópico de eventos.**

### Y3 — OpenTelemetry correlacionado + sondas sintéticas/RUM + alertas por *burn rate*

* Bueno, porque alinea observabilidad, conmutación regional (`QA-05`), reversión canaria (`QA-07`) y
  gobierno de confiabilidad (`CRN-03`).
* Malo, porque requiere operar colectores OpenTelemetry regionales en alta disponibilidad.

## Más información

* Análisis comparativo: [iteración 3, paso 4, D25](../02-proceso-add/iteracion-3/paso-4-alternativas.md#d25--observabilidad-catálogo-de-slisslos-y-presupuesto-de-error-crn-03)
* Catálogo de SLIs/SLOs: [pruebas-de-carga-y-slos.md](../02-proceso-add/iteracion-3/pruebas-de-carga-y-slos.md)
* Relacionados: [ADR-0008](ADR-0008-alcance-disponibilidad.md), [ADR-0022](ADR-0022-despliegue-progresivo-y-reversion.md)
