# Docker: app y stack con Grafana/Prometheus

**Stack completo (app + Prometheus + Grafana):** desde la raíz del repo, **`./scripts/docker_stack.sh`** o **`./scripts/docker_up.sh stack`** (equivale a `docker compose up --build`). **Solo la app** (sin Grafana): **`./scripts/docker_up.sh`** — si usas este último, **Grafana no existe** en ese arranque.

La imagen principal usa un solo proceso de orquestación (`docker/entrypoint.sh`, con **tini** como PID 1). Tras `migrate`, si `ENABLE_RECALIBRATE_ON_START=1` (default), ejecuta **`export_calibration_from_m1.py`** contra el Excel montado en `data/`, y escribe `modulo2_motor_alertas/calibration.json` antes de arrancar el puente, el bucle M2 y el monitor. Luego levanta:

| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| Django | **8000** | Dashboard (`/`, `/monitor/`, …) |
| Puente FastAPI | **8090** | `POST /tick` para n8n; `GET /metrics` (Prometheus, proceso uvicorn) |
| `run_alert_engine.py` (M2) | — | Bucle opcional en Docker (`ENABLE_M2_ENGINE_LOOP=1`): consola + auditoría; debounce en archivo propio (`ALERT_STATE_PATH_M2`) |
| `monitor_loop.py` (M3) | — | Ciclo periódico (encadena motor M2 vía pipeline; por defecto **dry-run**); métricas en **9108** (`/metrics`) |
| Prometheus | **9090** | Solo con `docker compose` (scrape a 8090 y 9108 del servicio `caso-tecnico`) |
| Grafana | **3000** | Solo con `docker compose` / `docker_stack.sh` (datasource Prometheus + dashboard **Rappi — operación** en carpeta *Caso tecnico Rappi*; `admin`/`admin` por defecto) |

## Monitor continuo (`monitor_loop.py`)

En la imagen, el **entrypoint** lanza en segundo plano el **bucle M2** (`modulo2_motor_alertas/run_alert_engine.py`) si `ENABLE_M2_ENGINE_LOOP=1` (default), con estado de debounce separado del monitor para no bloquear alertas del M3. El **monitor M3** (`monitor_loop.py`) corre si `ENABLE_MONITOR=1` (default).

**Local (raíz del repo, con venv):**

```bash
.venv/bin/python modulo3_agente_telegram/monitor_loop.py
```

Opciones útiles: `--once` (un solo ciclo), `--interval-sec N` (si no usas `MONITOR_INTERVAL_SEC` en `.env`). Telegram y pings: variables en **`caso_tecnico/.env`** (`TELEGRAM_*`, `TELEGRAM_MONITOR_PING`, `MONITOR_INTERVAL_SEC`); el script hace `load_dotenv` de `/app/.env` en Docker o `../.env` desde el módulo.

**Docker:** monta **`./.env:/app/.env:ro`** para credenciales. El arranque en **bash** no hace `source` del `.env`; para quitar `--dry-run` del monitor y permitir **envío real** a Telegram, define **`MONITOR_DRY_RUN=0`** en el `.env` del host (Compose inyecta `MONITOR_DRY_RUN` y `MONITOR_INTERVAL_SEC` al contenedor; ver `docker-compose.yml`). Ejemplo manual:

```bash
docker run --rm -p 8000:8000 -p 8090:8090 -p 9108:9108 \
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

Levanta **caso-tecnico**, **Prometheus** y **Grafana**. URLs típicas en el host:

- Grafana: <http://127.0.0.1:3000/> (credenciales por defecto `admin` / `admin`; cambia con `GRAFANA_ADMIN_PASSWORD` en el entorno)
- Prometheus UI: <http://127.0.0.1:9090/>
- Métricas crudas del monitor: <http://127.0.0.1:9108/metrics>
- Métricas del puente (tras un `POST /tick`): <http://127.0.0.1:8090/metrics>

Tras entrar en Grafana (**Dashboards** → carpeta **Caso tecnico Rappi** → **Rappi — operación (ticks monitor y puente)**) deberías ver targets UP y series `rappi_operational_tick_total`. Si **up** sale 0 (DOWN), en Prometheus (**Status → Targets**) revisa errores de conexión a `caso-tecnico:8090` o `:9108` (red Docker o contenedor app caído).

### Grafana “no funciona” o no abre

1. **¿Arrancaste el stack completo?** `./scripts/docker_up.sh` **sin** `stack` no levanta Grafana. Usa `./scripts/docker_up.sh stack`, `./scripts/docker_stack.sh` o `docker compose up --build`.
2. **Puerto 3000 ocupado:** `CASO_HOST_GRAFANA=3001 docker compose up --build` y entra en `http://127.0.0.1:3001/`.
3. **Estado de los contenedores:** `docker compose ps` — Grafana espera a que Prometheus pase el healthcheck (`/-/ready`).

También puedes crear paneles a mano con consultas PromQL, por ejemplo:

- `sum by (status) (rate(rappi_operational_tick_total[5m]))` — tasa de ticks por estado (elige `job` `rappi_monitor` o `rappi_bridge` según qué proceso te interese)
- `histogram_quantile(0.9, sum by (le) (rate(rappi_operational_tick_duration_seconds_bucket{job="rappi_monitor"}[5m])))` — percentil 90 de duración del tick en el monitor

Para desactivar métricas en la app: `PROMETHEUS_METRICS_DISABLE=1` en el contenedor `caso-tecnico`.

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
  -p 9108:9108 \
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
docker run --rm -p 8000:8000 -p 8090:8090 -p 9108:9108 \
  -v "$(pwd)/data:/app/data:ro" \
  caso-tecnico
```

### Variables de entorno opcionales

| Variable | Default | Efecto |
|----------|---------|--------|
| `ENABLE_N8N_BRIDGE` | `1` | `0` desactiva uvicorn en 8090 |
| `ENABLE_RECALIBRATE_ON_START` | `1` | `0` omite la pasada inicial `export_calibration_from_m1.py` (usa el `calibration.json` de la imagen) |
| `ENABLE_M2_ENGINE_LOOP` | `1` | `0` desactiva el bucle `run_alert_engine.py` (sigue el monitor M3 si `ENABLE_MONITOR=1`) |
| `M2_ENGINE_INTERVAL_SEC` | — | Si no se define, usa `MONITOR_INTERVAL_SEC` (p. ej. `600`) |
| `ALERT_STATE_PATH_M2` | `/app/modulo2_motor_alertas/.alert_state_m2_loop.json` | Archivo JSON de debounce solo para el bucle M2 en Docker |
| `ENABLE_MONITOR` | `1` | `0` solo Django (+ puente y bucle M2 si aplica) |
| `MONITOR_DRY_RUN` | `1` | `0` quita `--dry-run` del monitor y permite alerta larga a Telegram si `.env` tiene `TELEGRAM_*` |
| `MONITOR_INTERVAL_SEC` | `600` | Intervalo entre ciclos del monitor (Compose lo pasa al contenedor) |
| `TELEGRAM_MONITOR_PING`, etc. | — | Van en el archivo **`.env`** montado; Python los lee al ejecutar el monitor |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,testserver` | P.ej. `*` si accedes por IP de la LAN |
| `PROMETHEUS_METRICS_DISABLE` | — | `1` desactiva registro y el servidor :9108 del monitor |
| `PROMETHEUS_MONITOR_METRICS_PORT` | `9108` | Puerto interno del endpoint `/metrics` del proceso `monitor_loop` |
| `CASO_OLLAMA_URL` | `http://host.docker.internal:11434` | URL de Ollama **desde dentro del contenedor** (Compose y `docker_up.sh`). Solo cambia si Ollama está en otro host/puerto |

### Ollama (LLM local) cuando la app va en Docker

Dentro del contenedor, `127.0.0.1:11434` **no** es tu PC. Por eso el stack ya configura:

| Mecanismo | Qué hace |
|-----------|----------|
| `docker-compose.yml` | `OLLAMA_BASE_URL=${CASO_OLLAMA_URL:-http://host.docker.internal:11434}` y `LLM_PROVIDER` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SEC` desde tu `.env` del proyecto (sustitución de Compose). |
| `./scripts/docker_up.sh` | Tras `--env-file .env`, fuerza `-e OLLAMA_BASE_URL=$CASO_OLLAMA_URL` (default `http://host.docker.internal:11434`) para que no gane el `127.0.0.1` del `.env` pensado para desarrollo local. |
| `extra_hosts` / `--add-host` | Resuelve `host.docker.internal` al host (Linux). |

**Pasos en el anfitrión**

1. Arranca Ollama escuchando en todas las interfaces (si no, Docker no conecta): p. ej. `OLLAMA_HOST=0.0.0.0` antes de `ollama serve` (detalle en la [FAQ de Ollama](https://github.com/ollama/ollama/blob/main/docs/faq.md) de tu versión).
2. `ollama pull <OLLAMA_MODEL>` con el mismo nombre que en `.env`.
3. Opcional: si Ollama no está en el puerto 11434 del host, define `CASO_OLLAMA_URL` en el entorno o en el `.env` que lee Compose (solo afecta la sustitución en `docker-compose.yml`; para `docker_up.sh` exporta la variable antes de ejecutar el script).

Puedes dejar en `.env` `OLLAMA_BASE_URL=http://127.0.0.1:11434` para cuando corres Python en local; Docker **sobrescribe** `OLLAMA_BASE_URL` en el contenedor con el valor anterior.

Si Ollama no responde, el pipeline **sigue enviando** Telegram con la **plantilla** (`used_llm=false`). Con `OPS_LOG_LEVEL=INFO`, `rag_chain` deja trazas de error HTTP o JSON inválido.

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
