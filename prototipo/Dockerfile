# Imagen de los servicios del prototipo (ADR-0036): un solo paquete Python y un proceso por
# servicio; el comando de cada uno lo fija docker-compose.yml.
# Se construye desde la raíz del repositorio, para incluir contratos/ (los servicios validan
# contra esos archivos en ejecución). Lo que entra al contexto lo limita Dockerfile.dockerignore.
FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TROTAMUNDOS_CONTRATOS=/app/contratos

WORKDIR /app
COPY prototipo/pyproject.toml prototipo/pyproject.toml
COPY prototipo/trotamundos prototipo/trotamundos
RUN pip install --no-cache-dir ./prototipo
COPY contratos contratos

RUN useradd --system --no-create-home trotamundos
USER trotamundos
