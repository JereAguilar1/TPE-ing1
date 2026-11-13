# PYTHON: intérprete 3.12 o posterior con el que se crea el entorno (ADR-0036).
PYTHON ?= python3.12
PY ?= .venv/bin/python

.PHONY: instalar pruebas infra-arriba servicios-arriba infra-abajo

instalar:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"

pruebas:
	$(PY) -m pytest -q

# La contraseña de la base local no está en el código: se genera al azar la primera vez y queda
# en .env, que git ignora. Docker Compose la lee de ahí, y las pruebas también (comun/config.py).
.env:
	@python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))" > .env
	@echo "Se creó .env con una contraseña al azar para la base local."

# PostgreSQL y el broker: lo que necesitan las pruebas.
infra-arriba: .env
	docker compose up -d --wait postgres broker

# Todo, incluidos los servicios de Trotamundos (construye la imagen).
servicios-arriba: .env
	docker compose up -d --build --wait

infra-abajo: .env
	docker compose down
