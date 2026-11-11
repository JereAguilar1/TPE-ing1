# TPE — Diseño de Sistemas de Software

Trabajo Práctico Especial: diseño de la arquitectura del sistema **Trotamundos** aplicando
el método **ADD (Attribute-Driven Design)**, con documentación de decisiones en **ADR / formato MADR**.

## Integrantes

- Jeremias Aguilar
- Francisco Lozano
- Juan Emilio Pardo
- Ivo Iriarte

## Documentación

Toda la documentación del trabajo vive en [`docs/`](docs/Home.md) con formato de wiki.
Punto de entrada: **[docs/Home.md](docs/Home.md)**.

| Sección | Contenido |
|---|---|
| [Gestión](docs/00-gestion/) | Equipo, bitácora de evolución, plan de iteraciones |
| [Análisis inicial](docs/01-analisis-inicial/) | Alcance, contexto, requisitos, escenarios de calidad, árbol de utilidad |
| [Proceso ADD](docs/02-proceso-add/) | Las 4 iteraciones de diseño completas, paso por paso |
| [ADRs](docs/03-adr/) | Decisiones arquitectónicas en formato MADR (`ADR-0001` a `ADR-0036`) |
| [Vistas](docs/04-vistas/) | Vistas de contexto, módulos (N1/N2), C&C, secuencias de los casos de uso, despliegue (N1/N2) y seguridad/datos |
| [Prototipo](prototipo/README.md) | Implementación de la 2da entrega: alcance, cómo correrlo y plan de construcción |
| [Contratos](contratos/README.md) | OpenAPI, AsyncAPI, contratos de complementos, descriptores de tipo de segmento y modelo dimensional (Spec-driven) |
| [Trazabilidad](docs/05-trazabilidad/) | Matriz completa (100 %) driver → decisión → vista → ADR |

## Estado

| Entrega | Alcance | Estado |
|---|---|---|
| 1ra entrega | Análisis inicial + 4 iteraciones de ADD documentadas | ✅ Completa (iteraciones 1, 2, 3 y 4 cerradas; 58/58 drivers trazados) |
| 2da entrega | Módulo avanzado (Opción B: asistente virtual) + prototipo trazable | En curso *(ver [plan de construcción](prototipo/README.md#plan-de-construcción))* |
