# Caso técnico Rappi — Sistema de alertas operacionales (AI Engineer)

Enfoque **data-driven first**: el Módulo 1 fija coeficientes, sensibilidad y “mm/hr para pasar ~1.2→1.8”; el Módulo 2 es un **sistema experto** (reglas IF-THEN + multiplicador por sensibilidad de zona); el Módulo 3 aplica **RAG-lite** (el “retrieval” es el JSON del motor, no documentos arbitrarios) y salida **JSON estricta** → mensaje Telegram.

| Capa | Implementación |
|------|----------------|
| Ingestión | Open-Meteo (sin key), forecast horario por centroide |
| Geo | Shapely + WKT; GeoPandas opcional (`geo_pipeline.py`) |
| Cerebro | `decision_engine.py` + `calibration.json` |
| Anti-fatiga | `debounce.py` + TTL vía `ALERT_DEBOUNCE_TTL_SEC` (escalado MEDIO→CRITICO) |
| Interface | `rag_chain.py` (JSON; **LangChain** LCEL en ruta OpenAI) + `python-telegram-bot` · **Dashboard** opcional: **Django** (`django_viz/`) — datos, pipeline, **página Monitor** (ticks de `monitor_loop.py`), forzar Telegram |
| Q&A ops | `docs/retroalimentacion_y_escalado.md` |

**Evaluación / demo (coherencia M1→M2, negocio, limitaciones, UX):** guía **`docs/criterios_evaluacion_demo.md`** — checklist de qué mostrar y decir; complementa **`modulo1_diagnostico/HALLAZGOS_M1.md`**.

Estructura por carpetas: **Módulo 1** (diagnóstico), **Módulo 2** (motor + clima), **Módulo 3** (agente + Telegram).

## Código y reproducibilidad

Esta sección resume lo que suele pedir una revisión de **README + entorno + demo**.

### Dependencias de setup (qué hace falta instalar)

| Pieza | Uso | Notas |
|-------|-----|--------|
| **Python 3.11+** | Obligatorio | Mismo runtime para M1 (notebook), M2 y M3. |
| **venv + pip** | Obligatorio | `python3 -m venv .venv` y `pip install -r requirements.txt`. **No hay Dockerfile ni `environment.yml` obligatorios** en este repo; si usas Conda, crea un env con Python 3.11 e instala `requirements.txt` dentro. |
| **Jupyter / VS Code + Jupyter** | Módulo 1 | Para ejecutar `01_diagnostico_operacional.ipynb`. |
| **Ollama** | Opcional (M3) | Solo si `LLM_PROVIDER=ollama` y quieres texto vía modelo local; si no, el agente puede usar **plantilla sin LLM** o **OpenAI**. |
| **pdflatex** | Opcional | Solo si compilas informes Beamer/LaTeX (`demo_caso_tecnico/`, `modulo1_diagnostico/…`). |
| **Django** | Opcional | Ya listado en `requirements.txt`; dashboard en `django_viz/`. |

### Variables de entorno y API keys (placeholders)

1. Copia **`.env.example`** → **`.env`** en la raíz `caso_tecnico/`.
2. **Nunca** commitees `.env` ni pegues claves reales en el README; solo valores de ejemplo como en `.env.example`.

| Variable | ¿Cuándo? | Descripción breve |
|----------|----------|-------------------|
| `TELEGRAM_BOT_TOKEN` | Envío real a Telegram (M3) | Token del bot (BotFather). |
| `TELEGRAM_CHAT_ID` | Idem | `@canal` o id numérico del canal/grupo. |
| `LLM_PROVIDER` | M3 | `ollama` \| `openai` \| `auto`. |
| `OPENAI_API_KEY` | Si usas OpenAI | Clave de la cuenta OpenAI (placeholder en `.env.example`). |
| `OPENAI_MODEL` | OpenAI | p. ej. `gpt-4o-mini`. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Si usas Ollama | Servidor local y nombre del modelo. |
| `ALERT_DEBOUNCE_TTL_SEC` | M2/M3 | TTL del debounce (segundos); tiene default en código. |
| `MONITOR_INTERVAL_SEC` | Monitor | Segundos entre ciclos de `monitor_loop.py`; default 600. |
| `USE_LANGCHAIN` | OpenAI | `1` (LangChain LCEL) o `0` (solo SDK). |

**Sin API key de pago:** Open-Meteo no requiere key. Telegram Bot API no cobra por uso típico de bots.

### Configurar el bot de Telegram para la demo

1. En Telegram, abre **[@BotFather](https://t.me/BotFather)** → `/newbot` → guarda el **token** (solo tú lo ves).
2. **Canal de demo:** crea un canal (o usa uno existente) → *Ajustes del canal* → *Administradores* → añade el bot con permiso **Publicar mensajes**.
3. **`TELEGRAM_CHAT_ID`:** puedes poner el **@usuario_del_canal** (p. ej. `@mi_canal_demo`) si es público, o el **id numérico** tipo `-100…` (útil para canales privados; se obtiene con bots como @userinfobot tras un mensaje en el canal o vía `getUpdates` si escribes al bot).
4. Coloca token y chat id en **`.env`** en la raíz del repo (los scripts M3 cargan `caso_tecnico/.env`).
5. Prueba: desde la raíz del repo, `python modulo3_agente_telegram/run_agent.py --test-telegram` (debe llegar un mensaje corto al destino).

Si el bot no publica: revisa que sea **admin del canal** y que el token no esté revocado en BotFather.

### Reproducir los tres módulos paso a paso

Ejecuta desde la raíz del clon salvo que se indique otra carpeta. Asume **venv activado** y **`pip install -r requirements.txt`** ya hecho.

#### Módulo 1 — Diagnóstico operacional

1. Confirma que existe `data/rappi_delivery_case_data.xlsx`.
2. Abre `modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb` y ejecuta las celdas (idealmente con el intérprete del `.venv`).
3. Las figuras se escriben en `modulo1_diagnostico/figures/`.
4. *(Opcional)* Regenerar calibración alineada al notebook: en `modulo2_motor_alertas/`, `python export_calibration_from_m1.py` (ver README de M2).

**Solo lectura de resultados:** puedes saltarte el notebook si aceptas el `calibration.json` ya versionado en M2.

#### Módulo 2 — Motor de alertas

1. Desde `modulo2_motor_alertas/`:
   - Sin red, prueba rápida: `python run_alert_engine.py --demo`
   - Con Open-Meteo real: `python run_alert_engine.py` (requiere internet).
2. Revisa salida en consola (zona primaria, riesgo, contexto).
3. *(Opcional)* `python run_alert_engine.py --recalibrate` para regenerar `calibration.json` desde el Excel y ejecutar.

#### Módulo 3 — Agente Telegram

1. Crea y configura **`.env`** (Telegram como arriba; LLM según prefieras).
2. Desde la raíz `caso_tecnico/`:
   - `python modulo3_agente_telegram/run_agent.py --test-telegram`
   - `python modulo3_agente_telegram/run_agent.py --demo --dry-run` (sin enviar, muestra lógica)
   - `python modulo3_agente_telegram/run_agent.py --demo --force-send` (envía al canal si `.env` está bien)
3. *(Opcional)* Monitor continuo: `python modulo3_agente_telegram/monitor_loop.py --interval-sec 600` (ver `modulo3_agente_telegram/README.md`).

Más detalle: **`modulo2_motor_alertas/README.md`**, **`modulo3_agente_telegram/README.md`**, **`django_viz/README.md`**.

### Buenas prácticas (errores, logging, auditoría)

- **Clima (Open-Meteo):** reintentos con backoff y timeout configurable (`WEATHER_HTTP_*` en `.env.example`). Si **una** zona falla, se degrada a precipitación 0 en esa zona y se registra el error; si **todas** fallan, el agente devuelve `status=weather_error` y el motor CLI sale con código `2`.
- **Logging:** logger `caso_tecnico.*` en stderr; nivel con `OPS_LOG_LEVEL` (p. ej. `INFO` o `DEBUG`).
- **Auditoría JSONL:** `modulo2_motor_alertas/.ops_audit.jsonl` — eventos (`operational_tick`, `weather_zone_failed`, `debounce_blocked`, `telegram_alert_sent`, …) con marca temporal. Complementa `.alert_events.jsonl` (solo envíos reales a Telegram) y `.monitor_ticks.jsonl`.
- **Mapa del código para la demo:** **`docs/arquitectura_codigo.md`** (flujo, tablas, dónde mirar si “no alertó”).

## Stack tecnológico (cumplimiento del enunciado)

El caso permite **libertad de herramientas**; lo siguiente es lo que este repositorio usa y puede defenderse en demo/revisión.

| Tema (enunciado) | Qué se usa aquí |
|------------------|-----------------|
| **LLMs** (OpenAI, Anthropic, Google, open-source…) | **OpenAI** por API (`OPENAI_API_KEY`, `OPENAI_MODEL`, p. ej. `gpt-4o-mini`). **Open source local:** **Ollama** + modelo configurable (por defecto **Mixtral** vía `OLLAMA_MODEL`). No hay conectores listos para Anthropic o Gemini; la capa `rag_chain.py` concentra el proveedor y el fallback determinista. |
| **Lenguaje** | **Python** 3.11+ (recomendado en el caso) en análisis (M1), motor (M2) y agente (M3). |
| **Orquestación** (LangChain, LlamaIndex, n8n, propia…) | **LangChain** (`langchain-core` + `langchain-openai`): cadena `ChatPromptTemplate \| ChatOpenAI` para generar el JSON de alerta cuando usas **OpenAI** (por defecto activo; desactivar con `USE_LANGCHAIN=0`). El pipeline (`run_agent.py` → motor M2 → `rag_chain.py`) y la validación/ plantilla de fallback siguen en código propio. Con **Ollama** el cliente usa la API HTTP de Ollama (sin LangChain en esta versión). |
| **Notificaciones** | **Telegram Bot API** (obligatorio M3): librería `python-telegram-bot`, envío desde `telegram_sender.py`. |
| **Coste APIs pagas** | Documentado en la siguiente sección; ejemplo tipo enunciado: **~US\$0.03 por alerta** solo sería plausible con modelos caros o prompts muy largos — con **gpt-4o-mini** y un solo intercambio corto, el orden típico es **&lt; US\$0.01** por ejecución (ver tabla y [precios OpenAI](https://openai.com/pricing)). |

```
caso_tecnico/
├── data/
│   └── rappi_delivery_case_data.xlsx
├── docs/
│   ├── arquitectura_codigo.md
│   ├── criterios_evaluacion_demo.md   # guión rúbrica: M1→M2, negocio, limitaciones, UX
│   └── retroalimentacion_y_escalado.md
├── modulo1_diagnostico/
│   ├── HALLAZGOS_M1.md   # 5 hallazgos cuantificados + coherencia evaluación
│   ├── notebooks/01_diagnostico_operacional.ipynb
│   ├── figures/          # gráficos generados por el notebook
│   └── Diagnóstico Operacional/   # informe PDF + Diagnóstico Operacional.tex
├── modulo2_motor_alertas/
│   ├── src/              # decision_engine, debounce, weather, zones, geo_pipeline
│   ├── calibration.json
│   ├── run_alert_engine.py
│   └── latex/motor_reglas.tex
├── modulo3_agente_telegram/
│   ├── src/              # rag_chain, telegram_sender, alert_event_log, daily_summary
│   ├── run_agent.py
│   └── latex/arquitectura_agente.tex
├── demo_caso_tecnico/    # presentación Beamer para demo oral (PDF)
├── n8n/                  # workflows importables + docker-compose (orquestación local)
├── n8n_bridge/         # API opcional POST /tick para n8n en Docker
├── django_viz/           # dashboard Django: datos, pipeline, calibración, figuras M1
├── requirements.txt
└── .env.example
```

## Entorno (copiar y pegar)

```bash
cd caso_tecnico
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # luego edita .env (Telegram, opcional OpenAI)
```

La guía **paso a paso por módulo**, **Telegram** y **tabla de variables** está en la sección **Código y reproducibilidad** (más arriba en este README).

## Reproducción (checklist ultra corto)

1. **Entorno + dataset:** venv, `pip install -r requirements.txt`, `data/rappi_delivery_case_data.xlsx`.
2. **M1:** notebook `01_diagnostico_operacional.ipynb` *(opcional si usas `calibration.json` fijo)*.
3. **M2:** `cd modulo2_motor_alertas && python run_alert_engine.py --demo`.
4. **M3:** `.env` con Telegram → `run_agent.py --test-telegram` → `--demo --dry-run` → `--demo --force-send` si aplica.

Detalle: `modulo2_motor_alertas/README.md`, `modulo3_agente_telegram/README.md`, `demo_caso_tecnico/` (presentación).

## Costo estimado de APIs por uso

Todos los importes son **orientativos**; los de pago dependen del proveedor y del volumen. Revisa siempre la tarifa vigente.

| Servicio | Uso típico en este repo | Coste API monetario |
|----------|-------------------------|---------------------|
| **Open-Meteo** (forecast) | ~1 petición HTTP por zona con centroide en cada pasada completa del agente/motor (orden **decenas** de llamadas por ejecución completa sobre todas las zonas). | **0 USD** (API pública sin key; uso razonable según [términos Open-Meteo](https://open-meteo.com/en/terms)). |
| **Open-Meteo Archive** | Opcional: al ejecutar `--daily-summary` **sin** `--no-archive`, hasta **1 petición por zona distinta** con eventos ese día. | **0 USD** (misma política; no sustituir por scraping masivo). |
| **Telegram Bot API** | `sendMessage` por alerta enviada, ping de prueba, avisos de debounce y resumen diario si los lanzas. | **0 USD** ([Bot API](https://core.telegram.org/bots/api) gratuita para bots). |
| **OpenAI** (si `LLM_PROVIDER=openai` o `auto` con clave) | ~**1** llamada de chat completions por **alerta** generada (entrada: contexto JSON + instrucciones; salida: JSON corto + texto). Ejemplos orientativos por alerta (revisar tarifa vigente): **gpt-4o-mini** — a menudo **&lt; US\$0.01**; **gpt-4o** — suele seguir en centavos si el contexto es corto, puede acercarse a **~US\$0.02–0.05+** si se dispara el uso de tokens. | Cobro por **tokens**; ver [precios OpenAI](https://openai.com/pricing). |
| **Ollama** (si `LLM_PROVIDER=ollama`) | Misma lógica que OpenAI pero **local**; coste de **electricidad/GPU/CPU** en tu máquina, no de API en la nube. | **0 USD** de API. |

**Resumen:** flujo solo con **Ollama** o **plantilla sin LLM** + Open-Meteo + Telegram → **coste de APIs en nube ≈ 0 USD** por ejecución. El único coste recurrente de API de pago habitual en este diseño es **OpenAI** si lo activas explícitamente.

## Módulo 1

**Checklist de hallazgos (rúbrica “patrones”):** lista numerada con métricas y referencias al notebook + `calibration.json` en **`modulo1_diagnostico/HALLAZGOS_M1.md`**.

**Coherencia end-to-end, criterio de negocio, limitaciones y orientación ops:** **`docs/criterios_evaluacion_demo.md`**.

Abre `modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb` en **VS Code** (extensión Jupyter) o con Jupyter clásico. La primera celda detecta solo la raíz del proyecto (`data/rappi_delivery_case_data.xlsx`) aunque el directorio de trabajo sea la raíz del repo o la carpeta `notebooks/`.

Con VS Code, conviene abrir la carpeta `caso_tecnico` como workspace: se usa `.vscode/settings.json` (intérprete `.venv` y raíz del notebook).

```bash
cd modulo1_diagnostico/notebooks
jupyter notebook 01_diagnostico_operacional.ipynb
```

Las figuras se guardan en `modulo1_diagnostico/figures/`.

## Módulo 2

Resumen de diseño, API y umbrales: **`modulo2_motor_alertas/README.md`**. Justificación de reglas (1 página): compilar `modulo2_motor_alertas/latex/motor_reglas.tex` → `motor_reglas.pdf`.

- **Tiempo real (Open-Meteo):** consulta por centroide de cada zona en `ZONE_INFO` (polígonos WKT en `geo_pipeline` / `zones` para mapeo punto→zona).

```bash
cd modulo2_motor_alertas
python run_alert_engine.py
```

- **Demo sin red (simula lluvia fuerte en Santiago):**

```bash
python run_alert_engine.py --demo
```

## Módulo 3

Desde la **raíz** `caso_tecnico/` (carga `caso_tecnico/.env`):

```bash
python modulo3_agente_telegram/run_agent.py --demo --dry-run
python modulo3_agente_telegram/run_agent.py --demo --force-send
python modulo3_agente_telegram/run_agent.py --daily-summary --dry-run   # resumen del día

# Monitor continuo (Open-Meteo cada N s, LangChain LCEL + debounce)
python modulo3_agente_telegram/monitor_loop.py --interval-sec 600
```

Detalle, Telegram, cron y **monitor**: **`modulo3_agente_telegram/README.md`**.

- **`OPENAI_API_KEY`:** RAG-lite con salida JSON (modelo configurable con `OPENAI_MODEL`).
- **`USE_LANGCHAIN`:** con **OpenAI**, por defecto se usa **LangChain** para la cadena LLM (`1` o vacío); pon `USE_LANGCHAIN=0` para llamar solo al SDK `openai` sin LangChain.
- Sin API de LLM: plantilla determinista con los mismos números del motor.

## LaTeX (Módulo 1)

Informe en `modulo1_diagnostico/Diagnóstico Operacional/`: compilar `Diagnóstico Operacional.tex` con `pdflatex` (las figuras referencian `../figures/`). Ver `Diagnóstico Operacional/README.md`.

## Orquestación con n8n (opcional)

Flujos importables en **`n8n/`** que disparan la **misma pasada operativa** que `monitor_loop.py` (vía script o API local). No reimplementan el motor M2 en nodos; **n8n programa el cuándo** y Python ejecuta el qué.

- Guía: **`n8n/README.md`** · workflow recomendado (un solo canvas): **`n8n/workflows/rappi_pipeline_unificado.json`** · script **`scripts/n8n_run_tick.sh`** · puente HTTP opcional **`n8n_bridge/app.py`** (`POST /tick`).

## Dashboard web (Django)

Visualización del análisis de datos, pipeline M1→M2→M3, tablas del Excel, `calibration.json` y galería de figuras del notebook:

```bash
cd django_viz
python manage.py runserver
```

→ <http://127.0.0.1:8000/> · **`/monitor/`** muestra ciclos del monitor si ejecutas `modulo3_agente_telegram/monitor_loop.py` (escribe `modulo2_motor_alertas/.monitor_ticks.jsonl`). Detalle: **`django_viz/README.md`**.

**Un solo comando (monitor + Django):** desde la raíz, **`./scripts/run_stack.sh`** (hace `migrate`, levanta el monitor en segundo plano y `runserver` en primer plano; al salir con Ctrl+C se detiene el monitor). Opciones: `./scripts/run_stack.sh --help`.

## Dataset

El archivo Excel original puede permanecer en la raíz del proyecto; la copia de trabajo para scripts es `data/rappi_delivery_case_data.xlsx`.
# rappi-case
