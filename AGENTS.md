# Instrucciones para trabajar en este repositorio

Valen para cualquier integrante del grupo y para cualquier asistente de IA que trabaje acá.
Proyecto: TPE de Ingeniería de Software I (UNICEN), grupo 15, **Trotamundos**. La 1ra entrega
(documentación con el método ADD) ya se presentó; la 2da entrega es el prototipo en `prototipo/`.

## Lo que no se toca

- **No modificar nada** en `docs/01-analisis-inicial`, `docs/02-proceso-add`, `docs/04-vistas` ni
  `docs/05-trazabilidad`: es la 1ra entrega, ya presentada. Si encontrás una inconsistencia ahí,
  informala; no la corrijas. Las únicas excepciones son la iteración de ADD de la Opción B (paso 18),
  que aprobó el profesor: agregar `docs/02-proceso-add/iteracion-5/` y su fila en la tabla de
  iteraciones de `docs/02-proceso-add/README.md`. Las iteraciones 1 a 4 y el resto de ese índice no
  se tocan.
- **`docs/00-gestion`** (equipo, bitácora, plan): consultar al grupo antes de cambiar cualquier cosa,
  salvo las filas de la bitácora al terminar un paso (ver «Alcance de la entrega»).
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

## Alcance de la entrega

- **Entrega: lunes 23 de noviembre de 2026, 23:00.**
- El plan está **recortado** por falta de tiempo: leer «Recorte para la entrega» en
  `prototipo/README.md` antes de elegir qué hacer. Se trabaja por prioridad (sí o sí → debería →
  si sobra), no por número de paso.
- Los pasos 13 (`sharing`) y 16 (multirregión) **no se empiezan** salvo que todo lo prioritario
  esté terminado; en ese caso se sigue el orden de «Para completar el 100 % del contenido».
- **Congelamiento: domingo 22 de noviembre, 23:00** (24 h antes de la entrega). El lunes 23, hasta
  la entrega, es para el cierre (paso 21) y el ensayo de la defensa. Desde el congelamiento:
  - **Se puede:** corregir errores de lo ya construido, arreglar pruebas o checks en rojo y hacer el
    cierre (matriz, README, «Diseñado y no construido», guion de demostración).
  - **No se puede:** empezar pasos nuevos, sumar funcionalidades a pasos terminados ni refactorizar:
    cada cambio en esas horas es un riesgo de romper algo que andaba.
  - **Un paso empezado y sin terminar:** si se puede terminar y dejar probado en pocas horas del
    lunes, se termina; si no, se saca del repositorio (o se deja desactivado) y pasa a «Diseñado y
    no construido», con dónde está diseñado y por qué no se hizo. Nunca queda código a medias ni
    pruebas rotas en la entrega.
- Un paso reducido se construye **solo** con lo que dice su fila del recorte; lo demás va a «Para
  completar el 100 %», no se agrega de paso.
- **Quién hace cada paso** lo acuerda el grupo por WhatsApp, y una sola persona anota todos los
  nombres en la columna «Responsable» del plan (`prototipo/README.md`) en un único commit. No hace
  falta un commit por integrante. Antes de empezar un paso, mirar esa columna: si tiene a otro
  integrante, ese paso no se empieza. Si el reparto cambia, se actualiza la columna junto con el
  próximo commit del paso.
- **Al terminar un paso**, además de marcarlo hecho:
  - agregar sus filas a la «Matriz código ↔ ADR» de `prototipo/README.md` (qué código implementa
    qué ADR o contrato, y qué prueba lo verifica), y a «Diseñado y no construido» lo que haya
    quedado afuera. Así el cierre del lunes no arranca de cero;
  - agregar una fila en `docs/00-gestion/bitacora.md` con la fecha, el hito, lo producido y quien
    lo hizo (el enunciado pide mostrar la evolución y el trabajo de cada integrante). El grupo
    autoriza estas filas sin consulta previa; cualquier otro cambio en `docs/00-gestion` sigue
    necesitando su ok.

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

Las pruebas en verde no alcanzan para dar un paso por terminado. La integración continua además
levanta todos los contenedores (trabajo `servicios`) y falla si alguno no queda sano, pero no
recorre los caminos entre servicios. Antes de cerrar un paso que agrega o cambia un servicio:

- Tiene que haber una prueba que arme el servicio por su fábrica de Uvicorn (`servicio.crear_app()`)
  y otra que lo arranque con el *broker* real, como `tests/mail_ingest/test_arranque_mail_ingest.py`.
- Un servicio nuevo se agrega a `docker-compose.yml`, con su *healthcheck*: así la integración
  continua lo arranca.
- `make servicios-arriba` tiene que dejar **todos** los contenedores sanos, y el camino nuevo se
  prueba al menos una vez contra ellos.
- Después bajar solo los servicios (`docker compose rm -sf <servicios>`), sin borrar la base ni
  los esquemas: pueden tener datos de otros integrantes.

## Commits

- Formato `tipo(ámbito): descripción corta`, por ejemplo `prototipo(identity-access): sesiones y
  buzones`, `contratos: ...`, `fix: ...`, `docs: ...`. Mensajes cortos.
- Entre 2 y 3 commits por paso, y **cada commit con todas las pruebas en verde**.
- Cada integrante commitea con **su propia cuenta de git**, para que quede registrado su trabajo.
- Se trabaja en paralelo: `git pull` antes de empezar y *push* al terminar cada paso (o el día),
  no todo junto al final. Después de cada `git pull`, desde `prototipo/`: `make instalar` si cambió
  `pyproject.toml` (dependencias nuevas) y siempre `make infra-arriba`, que levanta la base y el
  *broker* si no están y agrega al `.env` los secretos nuevos sin tocar los que ya hay. `prototipo/README.md`, `docker-compose.yml` y `tests/test_arquitectura.py`
  los tocan todos: cambios chicos, agregando filas o bloques sin reescribir los de otros.
- Después del *push*, los tres checks de GitHub tienen que quedar en verde: `pruebas` (todas las
  pruebas), `servicios` (todos los contenedores arrancan) y SonarCloud.
