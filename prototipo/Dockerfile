# Imagen de los servicios del prototipo (ADR-0036): un solo paquete Python y un proceso por
# servicio; el comando de cada uno lo fija docker-compose.yml.
# Se construye desde la raíz del repositorio, para incluir contratos/ (los servicios validan
# contra esos archivos en ejecución). Lo que entra al contexto lo limita Dockerfile.dockerignore.
FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/prototipo \
    TROTAMUNDOS_CONTRATOS=/app/contratos

WORKDIR /app
# Dependencias con versión exacta (archivo de bloqueo) y solo como binarios ya compilados: la
# instalación no ejecuta scripts de terceros. El código propio corre desde el fuente.
COPY prototipo/requirements.txt prototipo/requirements.txt
RUN pip install --no-cache-dir --only-binary :all: --no-deps -r prototipo/requirements.txt
COPY prototipo/trotamundos prototipo/trotamundos
COPY contratos contratos

RUN useradd --system --no-create-home trotamundos
USER trotamundos
