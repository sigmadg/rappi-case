# Contenedor único (Django + monitor + puente n8n)

Un solo proceso de orquestación (`docker/entrypoint.sh`, con **tini** como PID 1) levanta:

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| Django | **8000** | Dashboard (`/`, `/monitor/`, …) |
| Puente FastAPI | **8090** | `POST /tick` para n8n (mismo pipeline que el monitor) |
| `monitor_loop.py` | — | Ciclo periódico M2+M3 (por defecto **dry-run**, sin alerta larga a Telegram) |

## Monitor continuo (`monitor_loop.py`)

En la imagen ya está el mismo comando que en local; el **entrypoint** lo lanza en segundo plano si `ENABLE_MONITOR=1` (default).

**Local (raíz del repo, con venv):**

```bash
.venv/bin/python modulo3_agente_telegram/monitor_loop.py
```

Opciones útiles: `--once` (un solo ciclo), `--interval-sec N` (si no usas `MONITOR_INTERVAL_SEC` en `.env`). Telegram y pings: variables en **`caso_tecnico/.env`** (`TELEGRAM_*`, `TELEGRAM_MONITOR_PING`, `MONITOR_INTERVAL_SEC`); el script hace `load_dotenv` de `/app/.env` en Docker o `../.env` desde el módulo.

**Docker:** monta **`./.env:/app/.env:ro`** para credenciales. El arranque en **bash** no hace `source` del `.env`; para quitar `--dry-run` del monitor y permitir **envío real** a Telegram, define **`MONITOR_DRY_RUN=0`** en el `.env` del host (Compose inyecta `MONITOR_DRY_RUN` y `MONITOR_INTERVAL_SEC` al contenedor; ver `docker-compose.yml`). Ejemplo manual:

```bash
docker run --rm -p 8000:8000 -p 8090:8090 \
  -v "$(pwd)/data:/app/data:ro" \
  -v "$(pwd)/.env:/app/.env:ro" \
  -e MONITOR_DRY_RUN=0 \
  -e MONITOR_INTERVAL_SEC=300 \
  caso-tecnico
```

## Requisitos en el host

- **Excel del caso:** monta **`data/`** con `rappi_delivery_case_data.xlsx` (típico: volumen `-v "$(pwd)/data:/app/data:ro"`).
- **Telegram / OpenAI:** monta un **archivo** **`.env`** en `/app/.env` solo si los necesitas (no se copia en la imagen). Sin `.env` el stack puede arrancar igual (monitor en dry-run, sin credenciales).

## Build

Desde la raíz `caso_tecnico/`:

```bash
docker build -t caso-tecnico .
```

## Sin plugin Compose (recomendado si falla `docker compose`)

Si al ejecutar `docker compose up --build` obtienes **`unknown flag: --build`** o **`'compose' is not a docker command`**, tu `docker` **no incluye el subcomando `compose`**. No hace falta Compose para levantar el stack: usa el script (build + run en un paso):

```bash
./scripts/docker_up.sh
```

Equivale a `docker build` + `docker run` con volumen `data/`. Si **8000 u 8090** del host están ocupados, el script **busca el siguiente par libre** (p. ej. 8001 y 8091) e imprime las URLs. Puedes forzar el inicio del rango con `CASO_DOCKER_PORT` y `CASO_DOCKER_PORT_BRIDGE`. Si existe un **archivo** `.env` en la raíz, lo monta en solo lectura.

## Compose (opcional)

En la raíz hay **`docker-compose.yml`**. Solo funciona con el **plugin Compose v2**. Comprueba: `docker compose version`.

```bash
docker compose up --build
```

### Puerto 8000 u 8090 ya en uso en el host

Si ves `Bind for 0.0.0.0:8000 failed: port is already allocated`, otro proceso (u otro contenedor) usa ese puerto. **No cambies el contenedor:** cambia solo el **mapeo** en el host, por ejemplo:

```bash
CASO_HOST_HTTP=8001 CASO_HOST_BRIDGE=8091 docker compose up --build
```

→ Dashboard en `http://127.0.0.1:8001/` y puente en `http://127.0.0.1:8091/tick`.

También puedes exportar las variables en tu shell o ponerlas en un archivo `.env` al lado de `docker-compose.yml` (Compose las lee automáticamente). Alternativa sin Compose: **`./scripts/docker_up.sh`** elige puertos libres solo.

### Si `apt` no encuentra `docker-compose-plugin` (Ubuntu 25.04 Plucky, Docker Snap, etc.)

Eso pasa cuando **no** tienes el repositorio oficial de Docker Engine en APT, o usas **Docker vía Snap** (el plugin no viene en los repos de Ubuntu igual que en Docker Desktop).

**Recomendado para este repo:** no necesitas Compose. Usa **`./scripts/docker_up.sh`** o **`docker build` + `docker run`** (secciones de arriba).

**Si quieres `docker compose` igualmente**, elige una opción:

1. **Instalar Docker Engine desde la documentación oficial** (añade el repo `apt` de Docker) y luego:  
   `sudo apt install docker-compose-plugin`  
   Guía: [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

2. **Plugin manual (binario)** — sin copiar/pegar largo, desde la raíz del repo:

   ```bash
   ./scripts/install_docker_compose_plugin.sh
   ```

   Descarga Compose v2 a `~/.docker/cli-plugins/docker-compose` y ejecuta `docker compose version`.  
   Versión concreta: `COMPOSE_VER=v2.29.7 ./scripts/install_docker_compose_plugin.sh`

   Si **`docker compose version`** sigue fallando, mira `which docker`: el **Snap** a menudo **no** carga plugins en el home. Entonces usa **`./scripts/docker_up.sh`** o instala **Docker Engine** con el paso 1.

## Run (`docker run`)

Necesitas la imagen `caso-tecnico` (sección **Build**). Un solo `docker run` arranca Django, el puente y el monitor.

```bash
cd /ruta/a/caso_tecnico

docker run --rm --name caso-tecnico \
  -p 8000:8000 \
  -p 8090:8090 \
  -v "$(pwd)/data:/app/data:ro" \
  -v "$(pwd)/.env:/app/.env:ro" \
  caso-tecnico
```

- **Excel:** en el host debe existir `data/rappi_delivery_case_data.xlsx` (carpeta `data/` montada solo lectura).
- **`.env`:** debe ser un **archivo** en el host (`cp .env.example .env` y edita). Si montas una ruta que no existe, Docker puede crear un **directorio** llamado `.env` y romper la carga de variables; si no usas secretos aún, **no montes** `.env` y omite esa línea.
- UI: <http://127.0.0.1:8000/>
- Puente: `POST http://127.0.0.1:8090/tick?dry_run=true` (desde el host; desde otro contenedor n8n usa `host.docker.internal:8090`).

**Solo dashboard (sin `.env`):**

```bash
docker run --rm -p 8000:8000 -p 8090:8090 \
  -v "$(pwd)/data:/app/data:ro" \
  caso-tecnico
```

### Variables de entorno opcionales

| Variable | Default | Efecto |
|----------|---------|--------|
| `ENABLE_N8N_BRIDGE` | `1` | `0` desactiva uvicorn en 8090 |
| `ENABLE_MONITOR` | `1` | `0` solo Django (+ puente si aplica) |
| `MONITOR_DRY_RUN` | `1` | `0` quita `--dry-run` del monitor y permite alerta larga a Telegram si `.env` tiene `TELEGRAM_*` |
| `MONITOR_INTERVAL_SEC` | `600` | Intervalo entre ciclos del monitor (Compose lo pasa al contenedor) |
| `TELEGRAM_MONITOR_PING`, etc. | — | Van en el archivo **`.env`** montado; Python los lee al ejecutar el monitor |
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
