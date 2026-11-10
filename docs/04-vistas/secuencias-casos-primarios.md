# Secuencias de los casos de uso primarios (UC-1 a UC-7)

**Tipo:** comportamiento (refinamiento dinámico de la vista C&C). Los participantes son
componentes en ejecución; los mensajes son llamadas sincrónicas (flecha continua) o eventos
publicados en el *broker* (flecha punteada).
**Responde:** ¿qué recorrido sigue cada caso de uso primario entre los elementos? ¿Por qué
interfaces pasa?
**Para quién:** quien implemente el prototipo y quien evalúe que cada caso de uso tiene un
recorrido completo, sin pasos «por definir».

Producida en la [iteración 2](../02-proceso-add/iteracion-2/README.md#paso-6--bosquejar-vistas-y-registrar-las-decisiones-de-diseño).
Cada diagrama formaliza el recorrido de la tabla del
[paso 7 de la iteración 2](../02-proceso-add/iteracion-2/paso-7-analisis.md#cada-caso-de-uso-tiene-un-recorrido-completo-y-especificado)
y usa los módulos internos de la [vista de módulos N2](vista-modulos-nivel-2.md). Los nombres de los
eventos son los del [catálogo de eventos](../02-proceso-add/iteracion-2/README.md#510-catálogo-de-eventos-actualizado).

**Leyenda de los diagramas de secuencia**

| Notación | Significado |
|---|---|
| Caja superior | **Participante**: componente en ejecución (sus instancias); el alias corto se define en cada diagrama |
| Muñeco (*actor*) | Persona que inicia la interacción (viajero, analista) |
| Línea vertical | Línea de vida del participante |
| `->>` flecha continua | **Llamada sincrónica** (HTTP) o acción interna del propio participante |
| `-->>` flecha punteada | **Respuesta** a una llamada, o **evento asíncrono** publicado o entregado por el *broker* |
| Número en la flecha | Orden del paso (`autonumber`) |
| Recuadro `alt` / `else` | Caminos alternativos excluyentes, según la condición rotulada |
| Recuadro `opt` | Paso que ocurre solo si se cumple la condición |
| Recuadro `par` / `and` | Pasos que ocurren en paralelo |
| Recuadro `loop` | Paso que se repite |
| Nota amarilla | Aclaración que no es un mensaje |

| UC | Caso de uso | RF | Decisiones que ejercita |
|---|---|---|---|
| [UC-1](#uc-1--ingesta-automática-desde-el-correo) | Ingesta automática desde el correo | RF-01…RF-04, RF-07 | [ADR-0004](../03-adr/ADR-0004-obtencion-de-correo.md), [0013](../03-adr/ADR-0013-deduplicacion-y-conflictos.md), [0014](../03-adr/ADR-0014-idempotencia-de-la-ingesta.md), [0015](../03-adr/ADR-0015-politica-de-confianza-de-extraccion.md) |
| [UC-2](#uc-2--actualización-o-cancelación-desde-un-proveedor) | Actualización o cancelación desde un proveedor | RF-05, RF-07, RF-10 | [ADR-0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0013](../03-adr/ADR-0013-deduplicacion-y-conflictos.md) |
| [UC-3](#uc-3--consulta-del-panel) | Consulta del panel | RF-08, RF-09 | [ADR-0005](../03-adr/ADR-0005-capa-de-clientes-bff.md), [0010](../03-adr/ADR-0010-modelo-canonico-reserva-segmento-viaje.md), [0019](../03-adr/ADR-0019-cache-camino-lectura-arranque-movil.md) |
| [UC-4](#uc-4--alta-manual-de-una-reserva) | Alta manual de una reserva | RF-06, RF-07 | [ADR-0013](../03-adr/ADR-0013-deduplicacion-y-conflictos.md), [0014](../03-adr/ADR-0014-idempotencia-de-la-ingesta.md) |
| [UC-5](#uc-5--notificación-de-una-disrupción) | Notificación de una disrupción | RF-10 | [ADR-0020](../03-adr/ADR-0020-contrapresion-y-sobrecarga.md) |
| [UC-6](#uc-6--consulta-analítica) | Consulta analítica | RF-14 | [ADR-0003](../03-adr/ADR-0003-separacion-planos.md), [0016](../03-adr/ADR-0016-modelo-dimensional-analitico.md) |
| [UC-7](#uc-7--derivación-de-un-caso-a-la-agencia-preferida) | Derivación a la agencia preferida | RF-12 | [ADR-0006](../03-adr/ADR-0006-capa-de-anticorrupcion.md), [0014](../03-adr/ADR-0014-idempotencia-de-la-ingesta.md) |

---

## UC-1 — Ingesta automática desde el correo

Camino de frescura de QA-01 (≤ 5 min de punta a punta). La banda de confianza decide si la reserva
entra como `Confirmada`, como `PorConfirmar` o no entra.

```mermaid
sequenceDiagram
    autonumber
    participant PC as Proveedor de correo
    participant MI as mail-ingest
    participant IA as identity-access
    participant BR as broker
    participant BE as booking-extraction
    participant IT as itinerary
    participant NO as notification

    PC->>MI: aviso de cambios en el buzón (o lo origina el reconciliador)
    MI->>MI: encola «buzón con cambios»
    MI->>IA: pide token de uso acotado
    IA-->>MI: token
    MI->>PC: baja metadatos
    MI->>MI: aplica filtros (bloqueadas > permitidas > catálogo)
    MI->>PC: baja el mensaje (solo si pasó los filtros)
    MI->>MI: normaliza y aplica inbox (buzón, idDeMensaje)
    MI-->>BR: MensajeDeViajeRecibido
    BR-->>BE: MensajeDeViajeRecibido
    BE->>BE: elige extractor, extrae, valida y fija la banda
    alt banda alta o media
        BE-->>BR: ReservaExtraida (banda, confianza)
        BR-->>IT: ReservaExtraida
        IT->>IT: inbox, resuelve identidad por identificadores y consolida (fusion)
        IT->>IT: asigna o crea el viaje (viajes)
        IT-->>BR: ReservaActualizada / ViajeArmado
        opt valor distinto sobre un campo fijado
            IT-->>BR: ConflictoDeFuentesDetectado
        end
        BR-->>NO: eventos de reserva
        NO->>NO: aplica reglas de severidad y coalescencia, y emite
    else banda baja o formato no reconocido
        BE-->>BR: ExtraccionNoReconocida
        BR-->>NO: ExtraccionNoReconocida
        NO->>NO: aviso administrativo y oferta de carga manual
    end
```

## UC-2 — Actualización o cancelación desde un proveedor

`provider-sync` publica la observación cruda; solo `itinerary` publica la reserva ya fusionada
(ajuste 1 de la [iteración 2](../02-proceso-add/iteracion-2/paso-7-analisis.md#ajustes-a-la-iteración-1)).

```mermaid
sequenceDiagram
    autonumber
    participant PV as Proveedor de viaje
    participant PS as provider-sync
    participant BR as broker
    participant IT as itinerary
    participant NO as notification

    alt el proveedor notifica
        PV->>PS: webhook (receptor-de-notificaciones)
    else el proveedor no notifica
        PS->>PV: consulta programada (programador)
    end
    PS->>PS: el adaptador traduce a ObservacionCanonica
    PS->>PS: seguimiento identifica reserva y usuario
    PS-->>BR: ReservaObservada (y DisrupcionDetectada si corresponde)
    BR-->>IT: ReservaObservada
    IT->>IT: inbox y consolidación con precedencia del proveedor
    alt choca con un campo fijado por el usuario
        IT-->>BR: ConflictoDeFuentesDetectado
    end
    IT-->>BR: ReservaActualizada o ReservaCancelada
    IT->>IT: proyeccion-panel actualiza panel_usuario
    BR-->>NO: ReservaActualizada / ReservaCancelada
    NO->>NO: correlaciona por idDeCausa y emite un solo aviso
```

## UC-3 — Consulta del panel

Camino crítico de latencia: 800 ms p95 en web y FCP < 1,4 s en móvil (QA-02, QA-03). Una sola ida y
vuelta del cliente al BFF.

```mermaid
sequenceDiagram
    autonumber
    actor U as Viajero
    participant CL as app-web / app-movil
    participant ED as edge
    participant GW as api-gateway
    participant IA as identity-access
    participant BF as bff-web / bff-mobile
    participant IL as itinerary-lectura

    U->>CL: abre el panel
    CL->>ED: GET /panel
    ED->>GW: reenvía
    GW->>IA: valida token y autoriza
    IA-->>GW: identidad y permisos
    GW->>BF: GET /panel
    BF->>IL: lee el panel del usuario
    IL->>IL: lee panel_usuario (viajes activos, por confirmar, conflictos)
    IL-->>BF: proyección
    BF->>BF: completa con la copia local de preferencias y compone
    BF-->>GW: respuesta compuesta
    GW-->>ED: respuesta
    ED-->>CL: respuesta
    CL-->>U: panel agrupado por viaje (los viajes completados no se muestran)
```

## UC-4 — Alta manual de una reserva

El comando es idempotente por `Idempotency-Key`. El sistema nunca fusiona por parecido: si hay
candidatas difusas, las devuelve como sugerencia.

```mermaid
sequenceDiagram
    autonumber
    actor U as Viajero
    participant CL as app-web / app-movil
    participant GW as api-gateway + BFF
    participant IT as itinerary-escritura
    participant BR as broker

    U->>CL: completa la reserva
    CL->>GW: POST /reservas (Idempotency-Key)
    GW->>IT: POST /reservas
    IT->>IT: gestion-manual valida el detalle contra el descriptor del tipo
    IT->>IT: fusion busca por identificadores
    alt coincide con una reserva existente
        IT->>IT: agrega la observación manual a esa reserva
    else no coincide
        IT->>IT: crea la reserva
        opt hay candidatas por coincidencia difusa
            IT->>IT: las prepara como sugerencia
        end
    end
    IT->>IT: viajes asigna o crea el viaje
    IT->>IT: escribe el cambio y el evento en la outbox (misma transacción)
    IT-->>GW: estado resultante (y sugerencias de duplicado)
    GW-->>CL: 201 con el estado resultante
    IT-->>BR: ReservaActualizada / ViajeArmado (publicacion desde la outbox)
```

## UC-5 — Notificación de una disrupción

Escenario de pico (QA-04). El aviso crítico sale de inmediato; la consolidación del cambio sigue en
paralelo el camino de UC-2.

```mermaid
sequenceDiagram
    autonumber
    participant PV as Proveedor de viaje
    participant PS as provider-sync
    participant BR as broker
    participant NO as notification
    participant IT as itinerary
    actor U as Viajeros afectados

    PV->>PS: informa la disrupción
    PS->>PS: detector-de-disrupciones expande a los usuarios afectados (seguimiento)
    PS-->>BR: DisrupcionDetectada (usuarios afectados)
    par aviso inmediato
        BR-->>NO: DisrupcionDetectada
        NO->>U: aviso crítico (push + canal interno, ignora horas de silencio)
        Note over NO,U: el aviso incluye la acción «pedir ayuda», que inicia UC-7
    and consolidación del cambio
        PS-->>BR: ReservaObservada
        BR-->>IT: ReservaObservada
        IT-->>BR: ReservaActualizada / ReservaCancelada
        BR-->>NO: evento de reserva
        NO->>NO: correlaciona por idDeCausa, sin segundo aviso
    end
```

## UC-6 — Consulta analítica

El plano analítico solo consume eventos (regla R6 de la
[vista de módulos N1](vista-modulos-nivel-1.md#reglas-de-dependencia)); la consulta del analista no
toca el plano operacional (QA-09).

```mermaid
sequenceDiagram
    autonumber
    participant OP as itinerary / notification / support-liaison
    participant BR as broker
    participant EP as event-pipeline
    participant AS as analytics-store
    actor AN as Analista de datos

    OP-->>BR: eventos de dominio
    BR-->>EP: eventos de dominio
    EP->>EP: los retiene crudos (capa de aterrizaje)
    loop micro-lotes (frescura ≤ 1 h)
        EP->>EP: transforma en hechos y dimensiones (seudónimo de usuario)
        EP->>AS: carga hecho_cambio_reserva, hecho_viaje y dimensiones
    end
    AN->>AS: consulta SQL sobre el esquema en estrella
    AS-->>AN: resultado (sin datos personales)
```

## UC-7 — Derivación de un caso a la agencia preferida

La creación del caso es idempotente; el caso guarda una instantánea inmutable del viaje.

```mermaid
sequenceDiagram
    autonumber
    actor U as Viajero
    participant GW as api-gateway + BFF
    participant SL as support-liaison
    participant IT as itinerary
    participant AG as Agencia preferida
    participant BR as broker
    participant NO as notification

    U->>GW: pide ayuda (desde el panel o un aviso)
    GW->>SL: POST /casos (Idempotency-Key)
    alt sin agencia preferida configurada
        SL-->>GW: rechazo, indica cómo configurarla
    else con agencia preferida (copia local de preferences)
        SL->>IT: obtiene la instantánea del viaje
        IT-->>SL: instantánea
        SL->>SL: crea el Caso (Abierto)
        SL->>AG: deriva por el adaptador de la agencia
        AG-->>SL: acuse
        SL->>SL: Caso pasa a Derivado
        SL-->>GW: caso creado
        SL-->>BR: CasoDerivado
        BR-->>NO: CasoDerivado
        NO->>U: confirmación al usuario
        alt la agencia ofrece interfaz de estado
            AG-->>SL: actualizaciones (EnGestión, Resuelto)
        else no la ofrece
            U->>SL: marca el caso como resuelto
        end
    end
```

---

## Cobertura

| Criterio de salida de la iteración 2 | Verificación |
|---|---|
| Los 7 casos de uso tienen un recorrido completo, sin pasos «por definir» | Los 7 diagramas anteriores |
| Toda interacción entre elementos pasa por una interfaz declarada | Las llamadas sincrónicas corresponden a operaciones de los BFF, `itinerary`, `identity-access` y `support-liaison`; los eventos, al catálogo de 15 eventos |
| La secuencia de supresión de datos personales (iteración 4) | En la [vista de seguridad y datos, §5](vista-seguridad-y-datos.md#5-secuencia-de-supresión-verificable-en-ambos-planos--30-días--adr-0030) |
