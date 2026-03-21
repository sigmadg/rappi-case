# Contenedor único (Django + monitor + puente n8n)

Un solo proceso de orquestación (`docker/entrypoint.sh`, con **tini** como PID 1) levanta:

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| Django | **8000** | Dashboard (`/`, `/monitor/`, …) |
| Puente FastAPI | **8090** | `POST /tick` para n8n (mismo pipeline que el monitor) |
| `monitor_loop.py` | — | Ciclo periódico M2+M3 (por defecto **dry-run**, sin Telegram) |

## Requisitos en el host

- El Excel del caso: monta **`data/`** con `rappi_delivery_case_data.xlsx` dentro (o copia el archivo antes del build si lo añades al contexto).
- Telegram / OpenAI: monta **`.env`** (no se copia en la imagen por seguridad).

## Build

Desde la raíz `caso_tecnico/`:

```bash
docker build -t caso-tecnico .
```

## Run (un solo `docker run`)

```bash
cd /ruta/a/caso_tecnico

docker run --rm --name caso-tecnico \
  -p 8000:8000 \
  -p 8090:8090 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/data:/app/data:ro" \
  caso-tecnico
```

- UI: <http://127.0.0.1:8000/>
- Puente: `POST http://127.0.0.1:8090/tick?dry_run=true` (desde el host; desde otro contenedor n8n usa `host.docker.internal:8090`).

### Variables de entorno opcionales

| Variable | Default | Efecto |
|----------|---------|--------|
| `ENABLE_N8N_BRIDGE` | `1` | `0` desactiva uvicorn en 8090 |
| `ENABLE_MONITOR` | `1` | `0` solo Django (+ puente si aplica) |
| `MONITOR_DRY_RUN` | `1` | `0` permite envío real a Telegram si `.env` está bien |
| `MONITOR_INTERVAL_SEC` | `600` | Intervalo del monitor |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,testserver` | P.ej. `*` si accedes por IP de la LAN |

Ejemplo solo dashboard (sin monitor ni puente):

```bash
docker run --rm -p 8000:8000 \
  -v "$(pwd)/data:/app/data:ro" \
  -e ENABLE_MONITOR=0 -e ENABLE_N8N_BRIDGE=0 \
  caso-tecnico
```

## Notas

- **No** incluye n8n UI; si usas n8n en otro contenedor, apunta el nodo HTTP a `http://host.docker.internal:8090/tick` y deja el puente activo.
- Estado SQLite y JSONL del monitor puede montarse en volumen si quieres persistencia entre reinicios (p. ej. `-v caso_state:/app/django_viz` y rutas bajo `modulo2_motor_alertas/`).
