---
estado: aceptado
fecha: 2026-11-11
decisores: Jeremias Aguilar, Francisco Lozano, Juan Emilio Pardo, Ivo Iriarte
consultados: —
informados: equipo completo
iteracion: prototipo (2da entrega)
drivers: CON-04, CON-05, CON-09, CON-A2, QA-16, CRN-06
---

# ADR-0036: Prototipo en Python 3.12 con FastAPI, PostgreSQL y un broker compatible con Kafka, validado en ejecución contra `contratos/`

## Contexto y planteo del problema

La 2da entrega exige un prototipo que demuestre la viabilidad de la arquitectura y cuyo código sea
«trazable, consistente con la arquitectura documentada» y respete «las especificaciones definidas
contractualmente» (enunciado §5, CON-04). [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)
fijó **qué** se construye: una tajada vertical que demuestra los 5 ASRs, un adaptador y un extractor
de ejemplo, el aislamiento analítico y el módulo avanzado, con simuladores en lugar de terceros.

Ningún ADR anterior fijó **con qué** se construye. Las decisiones previas sí imponen requisitos a la
tecnología:

| Decisión previa | Requisito sobre la tecnología |
|---|---|
| [ADR-0001](ADR-0001-estilo-arquitectonico.md) | Servicios independientes que se comunican por HTTP y por un *broker* de eventos |
| [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md) | Los contratos OpenAPI 3.1 y AsyncAPI 3.0 son la fuente de verdad; las pruebas se derivan de ellos |
| [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md) | Base relacional con restricciones de unicidad, transacciones y campos JSON para el detalle por tipo |
| [ADR-0014](ADR-0014-idempotencia-de-la-ingesta.md) | *Outbox* transaccional y bandeja de entrada por consumidor |
| AsyncAPI (`contratos/asyncapi/`) | Protocolo `kafka`, partición por `usuarioId` |

Y CON-09 limita el esfuerzo: cuatro personas con dedicación parcial construyen alrededor de diez
servicios.

## Drivers de decisión

* **CON-04, QA-16** — el código debe poder verificarse contra los contratos y trazarse a los ADRs.
* **CON-05, CON-09** — el prototipo tiene que ser construible por cuatro personas en el cronograma.
* **CON-A2** — el diseño supone servicios gestionados de nube; el prototipo los sustituye por
  equivalentes locales con la misma interfaz.
* **CRN-06** — las pruebas de contrato tienen que ser automáticas.

## Opciones consideradas

* **T1** — Python 3.12 + FastAPI + Pydantic.
* **T2** — TypeScript + NestJS.
* **T3** — Java 21 + Spring Boot.
* **T4** — Go.

En todas se usa la misma infraestructura: PostgreSQL 16 y un *broker* compatible con la API de Kafka,
levantados con Docker Compose.

## Resultado de la decisión

Se adopta **T1: Python 3.12 + FastAPI**, con estas piezas:

| Pieza | Elección | Por qué |
|---|---|---|
| Servicios HTTP | FastAPI + Uvicorn | Genera y sirve OpenAPI 3.1, el mismo formato de `contratos/` |
| Validación de mensajes | `jsonschema` (Draft 2020-12) leyendo **directamente** los archivos de `contratos/` | Una sola fuente de verdad: el código no redefine los esquemas, los carga |
| Base de datos | PostgreSQL 16 | Restricciones de unicidad, transacciones y `JSONB` para el detalle por tipo (ADR-0012) |
| *Broker* | Redpanda (API de Kafka) | Compatible con el protocolo `kafka` del contrato AsyncAPI y liviano para correr en una notebook |
| Pruebas | `pytest`; Schemathesis para las pruebas derivadas de OpenAPI | Lo que pide ADR-0017 |
| Infraestructura local | Docker Compose | Reemplaza los servicios gestionados de CON-A2 |

Dos reglas forman parte de la decisión:

1. **Un solo paquete Python (`trotamundos`) con un módulo por servicio**, y cada servicio corre como un
   proceso propio. Respeta la separación de [ADR-0001](ADR-0001-estilo-arquitectonico.md) en ejecución
   y evita que cuatro personas mantengan diez proyectos.
2. **Ningún servicio importa código de otro servicio.** Solo pueden compartir `trotamundos.comun`
   (equivalente a `modelo-canonico` y `contratos` de la vista de módulos N1, regla R7). Se comunican
   solo por HTTP y por eventos, como en producción.

**Lo que esta decisión no fija:** cómo se simula la multirregión para QA-05. Se decide al implementar
ese escenario.

### Consecuencias

* **Bueno,** porque los contratos se usan en ejecución: un evento o una respuesta que no cumple su
  contrato falla la prueba, y el código no puede divergir en silencio de `contratos/`.
* **Bueno,** porque Python es el lenguaje más rápido de escribir para el equipo (CON-09).
* **Bueno,** porque Redpanda y PostgreSQL tienen la misma interfaz que los servicios gestionados
  supuestos (CON-A2): el código no cambia al pasar a la nube.
* **Malo,** porque Python no alcanza el rendimiento de producción de QA-02 y QA-04. El prototipo
  demuestra los **mecanismos** (contrapresión, colas, degradación), no las cifras absolutas.
* **Malo,** porque el tipado es más débil que en T2 o T3; se compensa validando contra los contratos.
* **Neutro,** porque un solo paquete obliga a verificar con una prueba que ningún servicio importe a
  otro (regla 2).

### Confirmación

* Una prueba recorre los módulos de `trotamundos/servicios/` y falla si alguno importa otro servicio.
* Las pruebas validan eventos y respuestas contra `contratos/` usando `trotamundos.comun.contratos`.
* `docker compose up` levanta la infraestructura en una notebook del equipo.

## Pros y contras de las opciones

### T1 — Python + FastAPI

* Bueno, porque OpenAPI 3.1 es nativo y hay herramientas maduras para validar JSON Schema y probar
  contra OpenAPI.
* Bueno, porque es el más corto de escribir.
* Malo, por el rendimiento y el tipado.

### T2 — TypeScript + NestJS

* Bueno, por el tipado y el soporte de OpenAPI.
* Malo, porque requiere más configuración por servicio, y la versión de Node disponible en el equipo
  está desactualizada.

### T3 — Java + Spring Boot

* Bueno, por la robustez y el ecosistema empresarial.
* Malo, porque es el que más código requiere por servicio; con alrededor de diez servicios y cuatro
  personas compromete CON-05.

### T4 — Go

* Bueno, por el rendimiento y los binarios livianos.
* Malo, porque el soporte para generar o validar desde OpenAPI 3.1 y AsyncAPI 3.0 es menos maduro.

## Más información

* Alcance del prototipo: [ADR-0034](ADR-0034-punto-de-extension-modulo-avanzado.md)
* Contratos: [contratos/README.md](../../contratos/README.md)
* Código: [prototipo/README.md](../../prototipo/README.md)
* Relacionados: [ADR-0001](ADR-0001-estilo-arquitectonico.md), [ADR-0009](ADR-0009-contratos-spec-driven.md), [ADR-0012](ADR-0012-persistencia-del-plano-operacional.md), [ADR-0017](ADR-0017-estrategia-de-pruebas-y-contratos.md)
