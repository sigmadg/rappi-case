# Imagen única: dashboard Django + monitor M2/M3 + puente HTTP /tick para n8n.
# Build (desde la raíz del repo):  docker build -t caso-tecnico .
# Run: ver docker/README.md
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
COPY n8n_bridge/requirements.txt /tmp/n8n_bridge_requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt -r /tmp/n8n_bridge_requirements.txt

COPY . .
RUN chmod +x docker/entrypoint.sh

EXPOSE 8000 8090

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./docker/entrypoint.sh"]
