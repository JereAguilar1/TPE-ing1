# Instrucciones para trabajar en este repositorio

Valen para cualquier integrante del grupo y para cualquier asistente de IA que trabaje acá.
Proyecto: TPE de Ingeniería de Software I (UNICEN), grupo 15, **Trotamundos**. La 1ra entrega
(documentación con el método ADD) ya se presentó; la 2da entrega es el prototipo en `prototipo/`.

## Lo que no se toca

- **No modificar nada** en `docs/01-analisis-inicial`, `docs/02-proceso-add`, `docs/04-vistas` ni
  `docs/05-trazabilidad`: es la 1ra entrega, ya presentada. Si encontrás una inconsistencia ahí,
  informala; no la corrijas.
- **`docs/00-gestion`** (equipo, bitácora, plan): consultar al grupo antes de cambiar cualquier cosa.
- **`docs/03-adr`**: se pueden agregar ADR nuevos, pero un ADR aceptado no se edita; se escribe otro
  que lo reemplace.

## Cómo se decide

- El prototipo se basa **solo** en lo que ya está decidido: los ADR de `docs/03-adr`, las vistas,
  los contratos de `contratos/` y `prototipo/README.md`. Cuando un contrato y el código no
  coinciden, el error está en el código.
- **Si algo no está decidido en la documentación, preguntar antes de inventarlo.** Las decisiones
  menores que se tomen se registran en «Decisiones de implementación» de `prototipo/README.md`.
- El plan de pasos y el estado de cada ADR están en `prototipo/README.md`. Al empezar un paso, leer
  los ADR de su fila; al terminarlo, marcarlo como hecho y actualizar la tabla «Estado de las
  decisiones de arquitectura».

## Código

- Un subpaquete por servicio en `prototipo/trotamundos/servicios/`. **Ningún servicio importa a
  otro**: solo pueden compartir `trotamundos/comun` (lo verifica `tests/test_arquitectura.py`).
- Reusar lo de `comun`: validación contra contratos, errores `Problema`, persistencia con *outbox* y
  bandeja de entrada, carriles del *broker*. `servicios/itinerary` sirve de ejemplo.
- Ningún módulo de dominio nombra un tipo de segmento concreto (`vuelo`, `tren`…), salvo los
  complementos en carpetas `complementos/`.
- Sin credenciales ni contraseñas en el código: la de la base local está en `prototipo/.env`, que
  genera `make infra-arriba` y git ignora.
- Código, comentarios, pruebas y documentación en español rioplatense, como el resto del proyecto.

## Entorno y pruebas

Desde `prototipo/`: `make instalar`, `make infra-arriba` y `make pruebas`, que tiene que quedar todo en
verde. Si la base local se creó con una versión anterior del compose:
`docker compose down -v && make infra-arriba`.

## Commits

- Formato `tipo(ámbito): descripción corta`, por ejemplo `prototipo(identity-access): sesiones y
  buzones`, `contratos: ...`, `fix: ...`, `docs: ...`. Mensajes cortos.
- Entre 2 y 3 commits por paso, y **cada commit con todas las pruebas en verde**.
- Cada integrante commitea con **su propia cuenta de git**, para que quede registrado su trabajo.
- Después del *push*, los dos checks de GitHub (pruebas del prototipo y SonarCloud) tienen que
  quedar en verde.
