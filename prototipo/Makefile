# PYTHON: intérprete 3.12 o posterior con el que se crea el entorno (ADR-0036).
PYTHON ?= python3.12
PY ?= .venv/bin/python

.PHONY: instalar pruebas infra-arriba servicios-arriba infra-abajo FORZAR

instalar:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"

pruebas:
	$(PY) -m pytest -q

# Los secretos locales no están en el código: se generan al azar la primera vez y quedan en .env,
# que git ignora. Docker Compose los lee de ahí, y las pruebas también (comun/config.py). Si a un
# .env viejo le falta alguno, se agrega sin tocar los que ya tiene: cambiar la semilla del KMS o la
# clave de las sesiones dejaría ilegibles los buzones guardados e inválidas las sesiones abiertas.
SECRETOS_LOCALES = POSTGRES_PASSWORD TROTAMUNDOS_KMS_SECRETO TROTAMUNDOS_JWT_SECRETO \
                   TROTAMUNDOS_VALE_SECRETO TROTAMUNDOS_SECRETO_WEBHOOK_CORREO \
                   TROTAMUNDOS_SECRETO_WEBHOOK_PROVEEDOR TROTAMUNDOS_SECRETO_ACTAS

.env: FORZAR
	@python3 -c "import pathlib, secrets, sys; \
	p = pathlib.Path('.env'); t = p.read_text() if p.exists() else ''; \
	t = t if not t or t.endswith(chr(10)) else t + chr(10); \
	faltan = [k for k in sys.argv[1:] if not any(l.startswith(k + '=') for l in t.splitlines())]; \
	p.write_text(t + ''.join(k + '=' + secrets.token_urlsafe(32) + chr(10) for k in faltan)); \
	faltan and print('Se agregaron a .env, al azar: ' + ', '.join(faltan))" $(SECRETOS_LOCALES)

FORZAR:

# PostgreSQL y el broker: lo que necesitan las pruebas.
infra-arriba: .env
	docker compose up -d --wait postgres broker

# Todo, incluidos los servicios de Trotamundos (construye la imagen).
servicios-arriba: .env
	docker compose up -d --build --wait

infra-abajo: .env
	docker compose down
