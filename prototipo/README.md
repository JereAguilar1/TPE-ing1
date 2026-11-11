# Prototipo de Trotamundos (2da entrega)

Implementación prototipo que demuestra la viabilidad de la arquitectura documentada en
[`docs/`](../docs/Home.md). El código se construye contra los contratos de
[`contratos/`](../contratos/README.md) y cada parte remite al ADR que implementa.

## Qué se construye y qué no

El alcance lo fija [ADR-0034](../docs/03-adr/ADR-0034-punto-de-extension-modulo-avanzado.md) (CON-05):
una **tajada vertical** que demuestra las decisiones más riesgosas, no el sistema completo.

| Se construye | Para demostrar |
|---|---|
| Los caminos de los 5 ASRs | QA-01 (frescura ≤ 5 min), QA-04 (pico de disrupción), QA-05 (pérdida de región), QA-11 (formato de correo desconocido), QA-13 (custodia de credenciales) |
| Un adaptador de proveedor y un extractor de correo de ejemplo | QA-10 (proveedor nuevo sin tocar código) y QA-15 (tipo `tren` sin tocar el dominio) |
| El plano analítico separado | QA-09 (la analítica no afecta la operación) |
| El módulo avanzado **Opción B — asistente virtual** | RF-B1, RF-B2 (CON-06) |

Los terceros (proveedores de correo, aerolíneas, agencias, redes) se reemplazan por **simuladores**
que cumplen los mismos contratos. Las cifras de producción (por ejemplo, 9.000 req/s) no se buscan:
se demuestran los **mecanismos** que las sostienen.

## Tecnología

Decidida en [ADR-0036](../docs/03-adr/ADR-0036-tecnologia-del-prototipo.md): Python 3.12 + FastAPI,
PostgreSQL 16, Redpanda (API de Kafka) y Docker Compose.

## Estructura

```
prototipo/
├── trotamundos/
│   ├── comun/                  # lo único compartido (equivale a modelo-canonico + contratos)
│   │   ├── config.py           # configuración por entorno
│   │   ├── contratos.py        # validación en ejecución contra contratos/   (ADR-0009, ADR-0017)
│   │   ├── eventos.py          # sobre, carga y representación en el broker  (AsyncAPI, ADR-0014)
│   │   ├── errores.py          # application/problem+json                    (comun.yaml)
│   │   ├── modelo.py           # modelo-canonico: ObservacionCanonica, Lugar, Extremo (ADR-0010)
│   │   └── tipos_de_segmento.py # registro de descriptores de tipo           (ADR-0011, ADR-0027)
│   └── servicios/              # un subpaquete por servicio; ninguno importa a otro (ADR-0036)
├── tests/
├── docker-compose.yml      # PostgreSQL + broker
└── Makefile
```

### Reglas verificadas por las pruebas

`tests/test_arquitectura.py` comprueba en cada corrida las reglas de las vistas de módulos:

| Regla | Origen |
|---|---|
| Ningún servicio importa a otro; solo comparten `trotamundos.comun` | ADR-0036, ADR-0001 |
| `comun/modelo.py` solo usa la biblioteca estándar | R7, vista de módulos N1 |
| Ningún módulo menciona un tipo de segmento concreto (`vuelo`, `tren`…). Solo pueden hacerlo los complementos (adaptadores y extractores), que van en carpetas `complementos/` | I4, vista de módulos N2; ADR-0011 |

### Decisiones de implementación

Decisiones menores que los documentos de arquitectura no fijan explícitamente. Ninguna contradice
un ADR; si alguna llegara a afectar a un driver, se promueve a un ADR propio.

| Decisión | Por qué | Respaldo en la documentación |
|---|---|---|
| El registro de tipos de segmento vive en `comun/tipos_de_segmento.py`, no dentro de `itinerary` | Lo usan `itinerary` y también los extractores y adaptadores para validar su salida (QA-10, QA-11); como un servicio no puede importar a otro (ADR-0036), tiene que estar en lo compartido | La vista de módulos de adaptadores muestra los descriptores como «artefacto común transversal» usado por `booking-extraction`. La vista N2 lo ubica en `itinerary`: en el prototipo ese módulo es la exposición de `GET /tipos-de-segmento` |
| `CuentaSuprimida` se particiona por `seudonimoAnalitico` | El contrato prohíbe `usuarioId` en ese evento (ADR-0030); el seudónimo es el único identificador que trae, y mantiene en orden los eventos de supresión de una misma cuenta | Contrato AsyncAPI, `SobreSinUsuario` y carga de `CuentaSuprimida` |
| Los adaptadores y extractores van en carpetas `complementos/`, y son lo único que puede nombrar un tipo de segmento concreto | Traducen un formato externo a un tipo, así que necesitan conocerlo; el resto del código razona por descriptor (regla I4) | Vista de módulos N2 (regla I4) y vista de adaptadores (complementos aislados, reglas R2 y R3) |
| Los eventos y las respuestas se validan en el mismo proceso contra los archivos de `contratos/`, sin un registro de esquemas | Da la misma garantía (nada sale del servicio sin cumplir el contrato) sin agregar otro servidor a la infraestructura local. La compatibilidad entre versiones se comprueba con pruebas (paso 16) | La iteración 4 prevé un registro de esquemas AsyncAPI con compatibilidad `BACKWARD_TRANSITIVE` (ADR-0027); el prototipo lo reemplaza, no lo contradice |
| El campo `type` de los errores es `https://errores.trotamundos.app/{status}` | RFC 9457 pide una URI que identifique el tipo de problema; una por código de estado alcanza para el prototipo | `comun.yaml`, esquema `Problema` (`type` con `format: uri`) |

## Cómo correrlo

Requisitos: Python 3.12, Docker con Compose.

```bash
cd prototipo
make instalar        # crea .venv e instala dependencias
make pruebas         # corre las pruebas
make infra-arriba    # levanta PostgreSQL (puerto 55432) y el broker (puerto 19092)
make infra-abajo
```

Variables de entorno opcionales: `TROTAMUNDOS_CONTRATOS`, `TROTAMUNDOS_DSN`, `TROTAMUNDOS_BROKER`,
`TROTAMUNDOS_REGION`.

## Plan de construcción

Cada paso es un commit. La columna «Trazabilidad» indica qué decisiones implementa.

| # | Paso | Trazabilidad | Estado |
|---|---|---|---|
| 1 | Base: tecnología, infraestructura, validación contra `contratos/` | ADR-0009, ADR-0036 | ✅ |
| 2 | Registro de tipos de segmento y modelos canónicos | ADR-0010, ADR-0011 | ✅ |
| 3 | `itinerary`: agregado `Reserva` y fusión determinista | ADR-0010, ADR-0013 | ⬜ |
| 4 | `itinerary`: persistencia, *outbox*, *inbox* y API interna | ADR-0012, ADR-0014 | ⬜ |
| 5 | `itinerary`: viajes, agrupación, ciclo de vida y proyección del panel | RF-07, RF-08 | ⬜ |
| 6 | *Broker*: publicador de la *outbox*, consumidores y carriles | ADR-0014, ADR-0020 | ⬜ |
| 7 | `identity-access`: sesiones, buzones, bóveda con cifrado por sobres, auditoría | QA-13, ADR-0029 | ⬜ |
| 8 | `mail-ingest`: webhooks, filtros, normalización, deduplicación | RF-02, RF-04 | ⬜ |
| 9 | `booking-extraction`: extractores, bandas de confianza, formato desconocido | QA-11, ADR-0015 | ⬜ |
| 10 | `provider-sync`: adaptador simulado, cortacircuitos, disrupciones | QA-10, ADR-0024 | ⬜ |
| 11 | BFF y `api-gateway`: panel, límite de tasa, plazos | QA-02, ADR-0020 | ⬜ |
| 12 | `notification` y `support-liaison` | UC-5, UC-7 | ⬜ |
| 13 | `sharing`: compartición y `ResumenPublicable` | QA-12, ADR-0028 | ⬜ |
| 14 | `event-pipeline` y plano analítico | QA-09, ADR-0016 | ⬜ |
| 15 | Tipo `tren` sin tocar código de dominio | QA-15 | ⬜ |
| 16 | Pruebas de contrato y de escenarios (QA-01, QA-04, QA-05) | ADR-0017 | ⬜ |
| 17 | Iteración 5 de ADD: diseño de la Opción B (ADRs y contrato) | CON-06 | ⬜ |
| 18 | `virtual-assistant`: intenciones y derivación a la agencia | RF-B1, RF-B2 | ⬜ |
| 19 | Interfaz web mínima de demostración | RF-09 | ⬜ |
| 20 | Matriz código ↔ ADR, guion de demostración y README final | QA-16 | ⬜ |
