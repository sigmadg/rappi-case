# Arquitectura del código — mapa para demo y auditoría

Este documento resume **qué hace cada parte** del repositorio y **dónde mirar** si algo falla. No sustituye leer los docstrings de los módulos; sirve como guion de explicación en revisión oral.

## Flujo de punta a punta

1. **Datos históricos** (`data/rappi_delivery_case_data.xlsx`) alimentan el diagnóstico M1 y el `calibration.json` del M2.
2. **Tiempo real:** `weather_client` consulta Open-Meteo (forecast por lat/lon). Hay **reintentos** y registro en log si la API falla.
3. **Motor experto** (`decision_engine`): dado el máximo de lluvia en la ventana y la calibración, produce riesgo, incentivos y contexto JSON.
4. **Debounce** (`debounce`): evita repetir la misma severidad en la misma zona hasta que pase el TTL; permite **escalada** (p. ej. MEDIO → CRITICO).
5. **Agente M3** (`rag_chain`, `telegram_sender`): convierte el JSON en mensaje operativo (LLM o plantilla) y envía a Telegram.
6. **Monitor** (`monitor_loop` + `langchain_monitor`): repite el paso 2–5 cada `MONITOR_INTERVAL_SEC`.

## Carpetas principales

| Ruta | Rol |
|------|-----|
| `modulo1_diagnostico/notebooks/` | Análisis exploratorio y figuras; coeficientes conceptuales hacia M2. |
| `modulo2_motor_alertas/src/` | Cerebro operativo: `decision_engine`, `debounce`, `zones`, `weather_client`, `ops_logging`, `ops_audit`. |
| `modulo2_motor_alertas/run_alert_engine.py` | CLI del motor sin Telegram (útil para depurar clima + reglas). |
| `modulo3_agente_telegram/src/` | Pipeline completo hacia Telegram: `pipeline_core`, `rag_chain`, `alert_event_log`, `daily_summary`, etc. |
| `modulo3_agente_telegram/run_agent.py` | Entrada principal del agente (flags `--demo`, `--dry-run`, resumen diario, etc.). |
| `django_viz/` | Dashboard de lectura (Excel, calibración, monitor). |
| `docs/` | Operación, Q&A y este mapa. |

## Módulos M2 clave (explicación breve)

- **`weather_client.py`** — HTTP a Open-Meteo con **reintentos**, backoff y timeout configurable. Errores finales: `WeatherAPIError` o, en modo resiliente por zona, `try_fetch_hourly_precipitation` devuelve `([], mensaje)`.
- **`decision_engine.py`** — Reglas IF-THEN sobre umbrales y sensibilidad por zona; expone `pick_primary_zone`, `decide_for_zone`, `AlertDecision`.
- **`debounce.py`** — Estado en `.alert_state.json`; `should_emit_alert` decide si Telegram debe dispararse de nuevo.
- **`zones.py`** — Carga del Excel, centroides, WKT y punto de consulta al clima.
- **`ops_logging.py`** — Configura el logger `caso_tecnico.*` en stderr (nivel `OPS_LOG_LEVEL`).
- **`ops_audit.py`** — Append JSONL a `.ops_audit.jsonl`: eventos atómicos (`weather_zone_failed`, `operational_tick`, `telegram_alert_sent`, …).

## Módulos M3 clave

- **`pipeline_core.py`** — Orquesta una **pasada**: clima → primaria → decisión → debounce → LLM/plantilla → Telegram. Estados de salida incluyen `weather_error` si **todas** las zonas fallan al clima.
- **`langchain_monitor.py`** — Cadena LCEL que solo encadena timestamps + `run_operational_tick` + línea de log; **no** reemplaza reglas del motor.
- **`monitor_tick_log.py`** — Persistencia para el dashboard: `.monitor_ticks.jsonl`, `.monitor_status.json`.
- **`alert_event_log.py`** — Una línea por **alerta enviada** (no dry-run): `.alert_events.jsonl`.

## Trazas y auditoría (qué mirar cuando “no alertó”)

| Pregunta | Dónde |
|----------|--------|
| ¿Falló Open-Meteo? | stderr (`caso_tecnico.weather`), eventos `weather_zone_failed` / `operational_tick` con `status=weather_error` en `.ops_audit.jsonl`. |
| ¿El motor vio umbral? | `status=no_alert` en audit / monitor tick. |
| ¿Debounce bloqueó? | `debounce_blocked` en audit; `status=debounced` en monitor. |
| ¿Se mandó Telegram? | `telegram_alert_sent` en audit + línea en `.alert_events.jsonl`. |
| ¿Qué hizo el monitor? | `.monitor_ticks.jsonl` y vista `/monitor/` en Django. |

## Variables de entorno relacionadas

Ver `.env.example`: `WEATHER_HTTP_RETRIES`, `WEATHER_HTTP_TIMEOUT_SEC`, `WEATHER_HTTP_BACKOFF_SEC`, `OPS_LOG_LEVEL`, además de Telegram, LLM y debounce.

## Código limpio y límites

- La lógica de negocio **no** está en el dashboard ni en LaTeX; vive en `src/` de M2/M3.
- Los comentarios en código usan **docstrings de módulo** (qué problema resuelve el archivo) y **marcadores de sección** (`# --- Fase …`) en el flujo principal: `run_agent.py`, `pipeline_core.py`, `run_alert_engine.py`, `rag_chain.py`, `weather_client.py`, `monitor_loop.py`, `debounce.py`, `telegram_sender.py`, `zones.py`, etc.
- No se comenta cada línea trivial (`return`, imports estándar): en demo, seguir el hilo desde `run_agent.main` → `run_operational_tick` → `decide_for_zone` / `build_telegram_alert`.

## Guía rápida “por archivo” (demo oral)

| Archivo | Qué decir en una frase |
|---------|-------------------------|
| `run_agent.py` | Punto de entrada: enruta flags a ping, resumen diario o `run_operational_tick`. |
| `pipeline_core.py` | Orquesta clima → primaria → decisión → debounce → RAG → Telegram. |
| `weather_client.py` | HTTP a Open-Meteo con reintentos; degradación por zona. |
| `decision_engine.py` | Reglas expertas e incentivos a partir de `calibration.json`. |
| `debounce.py` | TTL por zona + escalada de riesgo. |
| `rag_chain.py` | LLM o plantilla: JSON fijo → texto Telegram validable. |
| `telegram_sender.py` | Bot API: credenciales y errores legibles. |
| `langchain_monitor.py` + `monitor_loop.py` | Bucle periódico sin duplicar lógica del motor. |
