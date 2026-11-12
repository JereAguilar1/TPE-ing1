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

# PostgreSQL y el broker: lo que necesitan las pruebas.
infra-arriba:
	docker compose up -d --wait postgres broker

# Todo, incluidos los servicios de Trotamundos (construye la imagen).
servicios-arriba:
	docker compose up -d --build --wait

infra-abajo:
	docker compose down
