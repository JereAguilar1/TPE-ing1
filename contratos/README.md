# Contratos de Trotamundos

Contratos de interfaz del sistema. Son artefactos de primera clase
([ADR-0009](../docs/03-adr/ADR-0009-contratos-spec-driven.md)): el prototipo se construye y se
prueba contra ellos ([ADR-0017](../docs/03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md)), y
evolucionan con las reglas de [ADR-0027](../docs/03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md).

Cuando un contrato y el código no coinciden, el error está en el código.

## Contenido

| Interfaz | Contrato | Formato | Origen |
|---|---|---|---|
| Esquemas comunes (modelo canónico, errores, cabeceras) | [openapi/comun.yaml](openapi/comun.yaml) | OpenAPI 3.1 | ADR-0010, ADR-0011, iteración 2 §5.2 |
| API pública completa | [openapi/api-gateway.yaml](openapi/api-gateway.yaml) | OpenAPI 3.1 | ADR-0005; referencia las operaciones de cada servicio |
| `bff-web` | [openapi/bff-web.yaml](openapi/bff-web.yaml) | OpenAPI 3.1 | Iteración 2 §5.7 |
| `bff-mobile` | [openapi/bff-mobile.yaml](openapi/bff-mobile.yaml) | OpenAPI 3.1 | Iteración 2 §5.7, ADR-0019 |
| `identity-access` | [openapi/identity-access.yaml](openapi/identity-access.yaml) | OpenAPI 3.1 | ADR-0007, ADR-0028, ADR-0029, ADR-0030, ADR-0035 |
| `itinerary` (interna) | [openapi/itinerary.yaml](openapi/itinerary.yaml) | OpenAPI 3.1 | Iteración 2 §5.1, ADR-0021 |
| `mail-ingest` (webhooks entrantes) | [openapi/mail-ingest-webhooks.yaml](openapi/mail-ingest-webhooks.yaml) | OpenAPI 3.1 | ADR-0004, ADR-0020, ADR-0035 |
| `mail-ingest` (filtros y whitelists) | [openapi/mail-ingest-filtros.yaml](openapi/mail-ingest-filtros.yaml) | OpenAPI 3.1 | RF-04, iteración 2 §5.4 (ver nota abajo) |
| `provider-sync` (webhooks entrantes) | [openapi/provider-sync-webhooks.yaml](openapi/provider-sync-webhooks.yaml) | OpenAPI 3.1 | ADR-0006, ADR-0020 |
| `support-liaison` | [openapi/support-liaison.yaml](openapi/support-liaison.yaml) | OpenAPI 3.1 | Iteración 2 §5.7 |
| `preferences` | [openapi/preferences.yaml](openapi/preferences.yaml) | OpenAPI 3.1 | Iteración 2 §5.6 |
| `sharing` | [openapi/sharing.yaml](openapi/sharing.yaml) | OpenAPI 3.1 | ADR-0028, iteración 4 §5.4 |
| Eventos de dominio (16) | [asyncapi/eventos-de-dominio.yaml](asyncapi/eventos-de-dominio.yaml) | AsyncAPI 3.0 | Iteración 2 §5.10; `CuentaSuprimida` de ADR-0030 |
| Complemento extractor | [plugins/extractor.yaml](plugins/extractor.yaml) | JSON Schema 2020-12 | ADR-0006, ADR-0015 |
| Complemento adaptador | [plugins/adaptador.yaml](plugins/adaptador.yaml) | JSON Schema 2020-12 | ADR-0006, iteración 2 §5.5 |
| Metaesquema de descriptores | [tipos-de-segmento/descriptor.schema.yaml](tipos-de-segmento/descriptor.schema.yaml) | JSON Schema 2020-12 | ADR-0011 |
| Descriptores de tipo de segmento | [vuelo](tipos-de-segmento/vuelo.v1.yaml), [hotel](tipos-de-segmento/hotel.v1.yaml), [auto](tipos-de-segmento/auto.v1.yaml), [tren](tipos-de-segmento/tren.v1.yaml), [autobús](tipos-de-segmento/autobus.v1.yaml) | YAML | ADR-0011; `tren` y `autobus` declarados sin implementar (CON-A3) |
| `analytics-store` | [analitica/modelo-dimensional.sql](analitica/modelo-dimensional.sql) | SQL ANSI | ADR-0016, ADR-0030 |

## Diferencias con la tabla de contratos de la iteración 2

La [tabla de contratos de la iteración 2](../docs/02-proceso-add/iteracion-2/README.md#contratos-declarados-en-el-repositorio)
es la referencia. Estos archivos la cumplen, con tres agregados que se explican aquí para que
nadie los tome por contradicciones:

1. **`openapi/comun.yaml`** no figura en la tabla. Reúne los esquemas que comparten todos los
   contratos, para que el modelo canónico tenga una sola definición.
2. **`openapi/mail-ingest-filtros.yaml`** no figura en la tabla, que solo lista los webhooks de
   `mail-ingest`. RF-04 necesita una interfaz para que el usuario administre sus listas, y la
   iteración 2 ubica los filtros en `mail-ingest` y no en `preferences`.
3. **`sharing.yaml`** está completo: la iteración 2 lo dejó como borrador y la iteración 4 lo
   completó (ADR-0028). El catálogo de eventos tiene **16** eventos y no 15, porque la iteración 4
   agregó `CuentaSuprimida` (ADR-0030), un cambio compatible según ADR-0027.

## Convenciones

| Tema | Regla | ADR |
|---|---|---|
| Versión de representación HTTP | `Accept: application/vnd.trotamundos.v{N}+json`, por omisión `v1`. Un cambio incompatible convive con la versión anterior 90 días o más, con `Deprecation` y `Sunset` | ADR-0027 |
| Versión de eventos | `versionEsquema` (`MAJOR.MINOR`) obligatorio en el sobre; doble emisión 14 días o más ante un cambio mayor | ADR-0027 |
| Versión de complementos | `apiContrato` con SemVer en el manifiesto; el anfitrión lo verifica al cargar | ADR-0027 |
| Versión de descriptores | Entero `version`; los segmentos históricos se validan contra la versión con que se crearon | ADR-0027 |
| Idempotencia | `Idempotency-Key` en los comandos; `idDeEvento` en los eventos | ADR-0014 |
| Lectura causal | La mutación devuelve `X-Version-Usuario`; el cliente lo reenvía en `X-Min-Version` | ADR-0018 |
| Sobrecarga | `429` con `Retry-After`; `503` cuando un modo de degradación apaga la función | ADR-0020 |
| Acceso denegado | `404` idéntico al de recurso inexistente | ADR-0028 |
| Instantes | UTC, con la zona IANA en un campo aparte | ADR-0032 |
| Errores | `application/problem+json` (RFC 9457) | — |
| Nombres | Rutas, campos y eventos en español, como en el resto del diseño | — |

## Cómo se verificaron

Antes de publicarse, todos los archivos pasaron estas verificaciones:

* Los 12 documentos OpenAPI validan contra la especificación 3.1, con las referencias entre
  archivos resueltas.
* El documento AsyncAPI valida con el parser oficial de AsyncAPI.
* Los 5 descriptores validan contra `descriptor.schema.yaml`, y su `esquemaDeDetalle` es un JSON
  Schema 2020-12 válido.
* Los manifiestos de `plugins/` son JSON Schema 2020-12 válidos.
* `modelo-dimensional.sql` se ejecuta sin errores.

En el prototipo, estas mismas verificaciones más las de compatibilidad (`openapi-diff` y el
registro de esquemas AsyncAPI en modo `BACKWARD_TRANSITIVE`) corren en integración continua
([ADR-0017](../docs/03-adr/ADR-0017-estrategia-de-pruebas-y-contratos.md),
[ADR-0027](../docs/03-adr/ADR-0027-versionado-y-evolucion-de-contratos.md)).
