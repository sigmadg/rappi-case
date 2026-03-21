# n8n — orquestación del flujo (clone operativo)

El **motor de reglas (M2), debounce, LLM y Telegram** siguen en Python (`pipeline_core`, `run_agent`, `monitor_loop`). Aquí se clona el **flujo**: *disparo periódico → misma pasada operativa*.

### Importar **un** workflow principal (recomendado)

| Archivo | Uso |
|---------|-----|
| **`workflows/rappi_pipeline_unificado.json`** | **Un solo canvas:** *Prueba manual* y *Cada 10 minutos* convergen en **un** nodo `POST /tick` (equivale a `monitor_loop --once`). Incluye nota adhesiva con instrucciones. |

No mezcles en el mismo canvas los otros JSON viejos: si importaste 3 archivos distintos verás **trozos sueltos** (schedule+execute, manual+http, open-meteo aislado). Eso **no** es un bug del código Python: son **tres plantillas** que debían ser **tres workflows separados** en pestañas distintas de n8n, o sustituirlas por el **unificado**.

### Otros archivos (opcionales / legado)

| Archivo workflow | Qué hace | Requisito |
|------------------|----------|-----------|
| `workflows/rappi_operational_tick.http.json` | Igual que antes: solo manual → HTTP | Redundante con el unificado |
| `workflows/rappi_operational_tick.execute.json` | Schedule → Execute Command al script | Ruta absoluta al `.sh` |
| `workflows/rappi_open_meteo_probe.json` | Solo GET Open-Meteo | **Didáctico:** el pronóstico real ya lo hace Python dentro de `/tick`; este nodo **no** forma parte del pipeline productivo. |

## 1) Instalar n8n

**Opción A — npm (recomendada para Execute Command):**

```bash
npm install -g n8n
n8n start
```

Abre `http://127.0.0.1:5678` y crea la cuenta local.

**Opción B — Docker (solo UI + workflows HTTP):**

```bash
export CASO_TECNICO_ROOT=/home/TU_USUARIO/Documentos/caso_tecnico   # informativo
docker compose -f n8n/docker-compose.yml up -d
```

Con Docker, el nodo **Execute Command** no ve tu `.venv` del host salvo que montes el repo dentro del contenedor; por eso para Docker se usa el **puente HTTP** (`n8n_bridge/app.py`).

## 2) Puente HTTP (para Docker o para no exponer shell)

Desde la raíz `caso_tecnico/`:

```bash
source .venv/bin/activate
pip install -r n8n_bridge/requirements.txt
uvicorn n8n_bridge.app:app --host 127.0.0.1 --port 8090
```

Atajo (mismo efecto que el `uvicorn` de arriba):

```bash
./scripts/run_n8n_bridge.sh
```

- Desde el **mismo host** (n8n instalado con npm en tu PC): en el workflow HTTP usa `http://127.0.0.1:8090/tick`.
- Desde **n8n en Docker**: en el nodo HTTP Request usa **`http://host.docker.internal:8090/tick`** (el `extra_hosts` ya está en `docker-compose.yml`). **No** uses `127.0.0.1`: dentro del contenedor eso es el propio contenedor, no tu máquina.

Parámetros query: `dry_run=true|false`, `demo=true|false`, `force_send=true|false`.

### «The service refused the connection — perhaps it is offline» (n8n)

Significa **connection refused**: nada acepta TCP en esa IP:puerto, o el firewall rechaza. Revisa en orden:

1. **¿Está el puente levantado?** En otra terminal, desde la raíz del repo:
   ```bash
   ./scripts/run_n8n_bridge.sh
   ```
   Debe quedarse corriendo mientras pruebas el workflow.

2. **Prueba local:** `curl -sS -X POST 'http://127.0.0.1:8090/tick?dry_run=true' | head -c 300`  
   Si aquí falla, el puente no está activo o el puerto no es 8090.

3. **n8n en Docker:** URL del nodo = `http://host.docker.internal:8090/tick` (no `127.0.0.1`).

4. **n8n en Docker sobre Linux:** además, el puente debe escuchar **fuera** de solo-loopback, si no el contenedor sigue sin poder conectar. Arranca así:
   ```bash
   N8N_BRIDGE_HOST=0.0.0.0 ./scripts/run_n8n_bridge.sh
   ```
   (`127.0.0.1` en el host no recibe bien el tráfico que entra vía la IP del bridge de Docker.)

### Fallo en `POST /tick` (cruz roja en n8n)

1. ¿Está corriendo el puente? (ver arriba).
2. `curl` como en el punto 2 de la sección anterior.
3. Comprueba URL según n8n nativo vs Docker y, en Docker en Linux, `N8N_BRIDGE_HOST=0.0.0.0`.

## 3) Importar workflows

1. En n8n: **Workflows → Import from File**.
2. Elige **`n8n/workflows/rappi_pipeline_unificado.json`** (recomendado).
3. Si usas **Execute Command** (archivo `.execute.json`), edita el nodo y pon la **ruta absoluta** al script, por ejemplo:
   - Command: `/home/TU_USUARIO/Documentos/caso_tecnico/scripts/n8n_run_tick.sh`
   - (Opcional) CWD: `/home/TU_USUARIO/Documentos/caso_tecnico`

El JSON de ejemplo usa expresiones `{{ $env.CASO_TECNICO_ROOT }}`; si tu n8n no define esa variable, sustituye por ruta fija o define `CASO_TECNICO_ROOT` en el entorno donde arranca n8n.

## 4) Script shell (Execute Command)

`scripts/n8n_run_tick.sh` ejecuta el equivalente a `monitor_loop.py --once --dry-run` (por defecto). Para otro modo:

```bash
export N8N_TICK_ARGS="--once --demo --dry-run"
/path/caso_tecnico/scripts/n8n_run_tick.sh
```

Haz el script ejecutable:

```bash
chmod +x scripts/n8n_run_tick.sh
```

## 5) Alinear con el monitor real

- Intervalo del **Schedule Trigger** en n8n (p. ej. 10 min) ≈ `MONITOR_INTERVAL_SEC` / `monitor_loop.py`.
- La lógica **LangChain** del repo no se reimplementa en n8n: n8n **dispara** el mismo binario/Python.

## Limitaciones

- No se duplican aquí las reglas M2 en JavaScript; si cambias `calibration.json`, el comportamiento lo sigue dando Python.
- Telegram en producción: quita `dry_run` solo cuando `.env` esté bien configurado.
