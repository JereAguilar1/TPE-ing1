---
estado: aceptado
fecha: 2026-11-17
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: 5 (precisión de ADR-0035)
drivers: CON-08, RF-01, QA-13, CON-04, CON-06
---

# ADR-0041: El alias de reenvío lo genera `identity-access` al conectar el buzón, y `mail-ingest` lo recibe por `EstadoDeBuzonCambiado`

## Contexto y planteo del problema

[ADR-0035](ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md) decidió la vía de reenvío para los
buzones sin OAuth: cada viajero tiene un alias `viajes+<token>@ingesta.trotamundos.app` y el
receptor de `mail-ingest` verifica DKIM, SPF o ARC y que quien reenvía sea el titular. En su texto
dice que «`mail-ingest` asigna» el alias.

El contrato publicado dice otra cosa: en `identity-access.yaml`, `POST /buzones` con `via: reenvio`
devuelve el `aliasReenvio` en la misma respuesta con que se conecta el buzón. Si lo asignara
`mail-ingest`, `identity-access` no podría devolverlo en esa respuesta sin una llamada sincrónica
nueva. El prototipo se construyó según el contrato (paso 7), y `mail-ingest` recibe el alias por
`EstadoDeBuzonCambiado` (AsyncAPI 1.4.0, paso 8).

AGENTS.md dice que cuando un contrato y el código no coinciden, el error está en el código; acá el
código coincide con el contrato, y es el texto del ADR el que no. Un ADR aceptado no se edita: esta
decisión lo precisa.

## Drivers de decisión

* **CON-08 / RF-01** — conectar un buzón sin OAuth de forma segura y autorizada.
* **QA-13** — `identity-access` es el único custodio de lo que identifica un buzón.
* **CON-04** — el contrato publicado manda sobre el código y los textos.
* **CON-06** — sin interfaces nuevas.

## Opciones consideradas

* **N1** — Lo genera `mail-ingest`, como dice ADR-0035: `identity-access` le pide el alias con una
  llamada sincrónica nueva al conectar el buzón.
* **N2** — Lo genera `mail-ingest` de forma asincrónica: `POST /buzones` no devuelve el alias, y el
  viajero lo ve recién cuando `mail-ingest` lo publica.
* **N3** — Lo genera `identity-access` al conectar el buzón, lo devuelve en `POST /buzones` y lo
  publica en `EstadoDeBuzonCambiado` al pasar a `Activo`.

## Resultado de la decisión

Se adopta **N3**, que es lo que dicen los contratos y lo que está construido:

1. `identity-access` genera el alias con un token aleatorio al conectar un buzón por `reenvio`, lo
   guarda con el buzón y lo devuelve en la respuesta de `POST /buzones`.
2. Al pasar el buzón a `Activo`, lo publica en `EstadoDeBuzonCambiado` (`aliasReenvio`), junto con el
   correo del titular que el receptor necesita para verificar quién reenvía.
3. `mail-ingest` mantiene su copia para resolver el alias de cada mensaje entrante; la verificación
   de ADR-0035 (DKIM, SPF o ARC y titular) no cambia.
4. **Precisa a ADR-0035** solo en quién genera el alias. El resto de esa decisión sigue vigente.

### Consecuencias

* **Bueno,** porque el viajero recibe el alias en el mismo momento en que conecta el buzón.
* **Bueno,** porque no agrega una llamada sincrónica entre servicios (CON-06).
* **Bueno,** porque el alias queda con el resto de los datos del buzón, en el custodio que ADR-0029 ya
  definió.
* **Neutro,** porque `mail-ingest` guarda una copia del alias, que llega por un evento existente.

### Confirmación

* `tests/identity_access/test_api_identity_access.py`: el alta por `reenvio` devuelve el alias y el
  evento `Activo` lo publica.
* `tests/mail_ingest/test_mail_ingest.py`: el receptor resuelve el buzón por su alias.

## Pros y contras de las opciones

### N1 — Lo genera `mail-ingest`, con una llamada sincrónica

* Bueno, porque sigue el texto de ADR-0035.
* Malo, porque agrega una interfaz y acopla el alta del buzón a la disponibilidad de `mail-ingest`.

### N2 — Lo genera `mail-ingest`, asincrónico

* Bueno, porque no agrega llamadas sincrónicas.
* Malo, porque el viajero no ve su alias al conectar el buzón y contradice el contrato publicado.

### N3 — Lo genera `identity-access`

* Bueno, porque coincide con el contrato y con lo construido, sin interfaces nuevas.
* Malo, porque contradice el texto de ADR-0035, y por eso se registra esta precisión.

## Más información

* Iteración: [iteración 5, paso 4, D41](../02-proceso-add/iteracion-5/paso-4-alternativas.md#d41--quién-genera-el-alias-de-reenvío-con-08-precisión-de-adr-0035)
* Contratos: [`identity-access.yaml`](../../contratos/openapi/identity-access.yaml) (`POST /buzones`), [`eventos-de-dominio.yaml`](../../contratos/asyncapi/eventos-de-dominio.yaml) (`EstadoDeBuzonCambiado`)
* Relacionados: [ADR-0029](ADR-0029-cifrado-custodia-y-rotacion-de-claves.md), [ADR-0035](ADR-0035-buzones-sin-oauth-y-formatos-desconocidos.md)
