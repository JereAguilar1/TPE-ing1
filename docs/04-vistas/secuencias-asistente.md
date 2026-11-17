# Secuencias del asistente virtual (Opción B)

**Tipo:** comportamiento (refinamiento dinámico de la [vista C&C del asistente](vista-cyc-asistente.md)).
Los participantes son componentes en ejecución.
**Responde:** ¿qué recorrido sigue una consulta, una corrección confirmada del itinerario y una
derivación a la agencia? ¿Por qué interfaces pasa cada una?
**Para quién:** quien construya el asistente y quien evalúe que `RF-B1` y `RF-B2` tienen un recorrido
completo, sin pasos «por definir».

Producida en la [iteración 5](../02-proceso-add/iteracion-5/README.md#paso-5--instanciar-elementos-asignar-responsabilidades-y-definir-interfaces)
(2da entrega). Completa las [secuencias de los casos primarios](secuencias-casos-primarios.md) de la
1ra entrega y usa los módulos de la [vista de módulos del asistente](vista-modulos-asistente.md).

---

**Leyenda de los diagramas de secuencia** (la misma notación que las
[secuencias de la 1ra entrega](secuencias-casos-primarios.md)):

| Notación | Significado |
|---|---|
| Caja superior | **Participante**: componente en ejecución (sus instancias); el alias corto se define en cada diagrama |
| Muñeco (*actor*) | Persona que inicia la interacción (el viajero) |
| Línea vertical | Línea de vida del participante |
| `->>` flecha continua | **Llamada sincrónica** (HTTP) o acción interna del propio participante |
| `-->>` flecha punteada | **Respuesta** a una llamada |
| `-)` flecha abierta | **Evento asíncrono** entregado por el *broker* |
| Recuadro `alt` / `else` | Caminos alternativos excluyentes, según la condición rotulada |

| Secuencia | Requisito | Decisiones que ejercita |
|---|---|---|
| Consulta de estado | RF-B1 | [ADR-0037](../03-adr/ADR-0037-interpretacion-de-intenciones-del-asistente.md), [ADR-0038](../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md), [ADR-0040](../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) |
| Corrección confirmada del itinerario | RF-B1, RF-06 | [ADR-0038](../03-adr/ADR-0038-alcance-y-confirmacion-de-las-acciones-del-asistente.md), [ADR-0013](../03-adr/ADR-0013-deduplicacion-y-conflictos.md) |
| Derivación por disrupción | RF-B2, RF-12 | [ADR-0039](../03-adr/ADR-0039-politica-de-derivacion-a-la-agencia.md), [ADR-0040](../03-adr/ADR-0040-sesion-conversacional-y-privacidad.md) |

**Consulta de estado (RF-B1).** El viajero pregunta y el asistente responde con lo que lee en
`itinerary`; si la reserva tiene una disrupción conocida, la menciona.

```mermaid
sequenceDiagram
    actor V as Viajero
    participant B as bff-web
    participant A as virtual-assistant
    participant I as itinerary-lectura
    V->>B: «¿a qué hora sale mi vuelo?»
    B->>A: POST /asistente/sesiones/{sid}/mensajes (sesión del viajero)
    A->>A: interprete → proximoTramo (confianza ≥ 0,6)
    A->>I: GET /viajes/{id}
    I-->>A: viaje con sus reservas
    A->>A: contexto: ¿disrupción conocida sobre ese tramo?
    A-->>B: Respuesta (intencion, mensajes)
    B-->>V: «Tu vuelo AR1402 sale el jueves 3/12 a las 10:00 (hora de Buenos Aires)»
```

**Corrección confirmada del itinerario (RF-B1).** Nada cambia hasta que el viajero confirma; si la
reserva cambió en el medio, se vuelve a proponer.

```mermaid
sequenceDiagram
    actor V as Viajero
    participant A as virtual-assistant
    participant IR as itinerary-lectura
    participant IW as itinerary-escritura
    V->>A: «me pasaron el vuelo AR1402 al sábado a las 18:30»
    A->>IR: GET /viajes/{id}
    A->>A: arma la edición (inicio y fin corridos igual)
    A-->>V: accionPropuesta (corregirReserva, vence en 10 min): «¿Confirmás?»
    V->>A: confirmacion { accionId, confirmar }
    A->>IW: PUT /reservas/{id} (version leída)
    alt la reserva cambió en el medio
        IW-->>A: 409
        A->>IR: GET /viajes/{id}
        A-->>V: nueva accionPropuesta con la versión actual
    else
        IW-->>A: 200 (el cambio queda fijado, ADR-0013)
        A-->>V: accionRealizada (corregirReserva)
    end
```

**Derivación por disrupción (RF-B2).** Una cancelación del proveedor no se arregla corrigiendo el
itinerario: el asistente propone derivar, con el `disrupcionId` como causa.

```mermaid
sequenceDiagram
    participant P as provider-sync
    participant A as virtual-assistant
    actor V as Viajero
    participant S as support-liaison
    P-)A: DisrupcionDetectada (severidad alta, reservas afectadas)
    A->>A: contexto: guarda la disrupción del viajero (bandeja de entrada)
    V->>A: «¿qué pasa con mi vuelo?»
    A-->>V: «Tu vuelo fue cancelado por el proveedor.» + accionPropuesta (derivarALaAgencia)
    V->>A: confirmacion { accionId, confirmar }
    A->>S: POST /casos (Idempotency-Key de la acción, motivo otro, descripción e idDeCausa)
    S-->>A: 201 Caso (agencia, estado Derivado)
    A-->>V: accionRealizada (derivarALaAgencia, casoId, agencia)
```
