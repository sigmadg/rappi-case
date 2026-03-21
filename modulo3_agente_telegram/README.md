# Módulo 3 — Agente Telegram + LLM (RAG-lite)

Flujo: **Open-Meteo** → motor Módulo 2 → **LLM** (JSON) → mensaje en lenguaje natural → **Telegram**.

**Stack / costos / Telegram (enunciado):** ver **`README.md` raíz** del repo — sección *Stack tecnológico* y *Costo estimado de APIs por uso*.

## Seguridad (importante)

- **Nunca** subas `TELEGRAM_BOT_TOKEN` al repositorio: usa solo `.env` (ya está en `.gitignore`).
- Si el token se filtró (chat, captura, issue público), **revócalo** en [@BotFather](https://t.me/BotFather) (`/revoke`) y pega el **nuevo** token solo en tu `.env` local.

## Configuración `.env` (raíz del repo `caso_tecnico/.env`)

```bash
TELEGRAM_BOT_TOKEN=<token del BotFather>
# Canal público: suele funcionar @nombre_del_canal (el bot debe ser administrador con permiso de publicar)
TELEGRAM_CHAT_ID=@examen_rappi

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=mixtral:8x7b-instruct-v0.1-q4_0
```

1. Crea el bot con BotFather y copia el token a `.env`.
2. Añade el bot como **administrador** del canal (p. ej. [@examen_rappi](https://t.me/examen_rappi)) con permiso de **publicar mensajes**.
3. `TELEGRAM_CHAT_ID`: prueba `@examen_rappi` o el id numérico (p. ej. `-100...`) si la API lo exige.

### Ollama

```bash
ollama pull mixtral:8x7b-instruct-v0.1-q4_0
```

- `LLM_PROVIDER=openai` + `OPENAI_API_KEY` → nube.
- `LLM_PROVIDER=auto` → OpenAI si hay clave; si no, Ollama.

**Orquestación (OpenAI):** por defecto **LangChain** — `ChatPromptTemplate | ChatOpenAI` en `rag_chain.py` (`langchain-core`, `langchain-openai`). Para desactivar y usar solo el SDK oficial: `USE_LANGCHAIN=0` en `.env`.

Si el LLM falla, se usa una **plantilla determinista** que sigue cumpliendo el checklist del enunciado.

## Observabilidad (clima, logs, auditoría)

- Si Open-Meteo **no responde** para ninguna zona, `run_operational_tick` devuelve **`status=weather_error`** (y el monitor lo refleja en consola / `.monitor_ticks.jsonl`). Fallos parciales: zona degradada a 0 mm/h + evento `weather_zone_failed` en **`modulo2_motor_alertas/.ops_audit.jsonl`**.
- **Logs** en stderr bajo `caso_tecnico.pipeline` y `caso_tecnico.weather` (`OPS_LOG_LEVEL`).
- Cada pasada escribe un resumen en **`.ops_audit.jsonl`** (`operational_tick`, `telegram_alert_sent`, `debounce_blocked`, …). Guía: **`docs/arquitectura_codigo.md`**.

## Monitor continuo (LangChain LCEL + Open-Meteo)

Script **`monitor_loop.py`**: bucle que **vuelve a consultar** la API del tiempo (Open-Meteo) cada **N segundos**, ejecuta el **motor M2** y decide si hay que **enviar una alerta nueva** a Telegram.

- La **validación** de “¿hace falta alerta?” sigue siendo el **motor experto** + **debounce** (`should_emit_alert`, TTL configurable). LangChain **orquesta** el ciclo (`RunnableLambda`: timestamp → `run_operational_tick` → línea de log), no reemplaza las reglas.
- **Escalada de riesgo** (p. ej. MEDIO → CRITICO) **sí** dispara envío aunque no haya pasado el TTL.
- Sin `--force-send`, el debounce **evita spam** de la misma severidad en la misma zona.

```bash
cd ~/Documentos/caso_tecnico
# Producción sugerida: intervalo 10–15 min (Open-Meteo es gratuito; no abuses del intervalo)
python modulo3_agente_telegram/monitor_loop.py --interval-sec 600

# Prueba: un solo ciclo, demo, sin Telegram
python modulo3_agente_telegram/monitor_loop.py --once --demo --dry-run

# Sin avisos cortos de debounce en Telegram (solo silencio si está en cooldown)
python modulo3_agente_telegram/monitor_loop.py --no-debounce-telegram
```

Variable opcional: **`MONITOR_INTERVAL_SEC`** en `.env` si no pasas `--interval-sec`.

**Producción:** ejecutar bajo `systemd`, `supervisor` o `screen`/`tmux`; revisar coste de llamadas Open-Meteo (muchas zonas × cada ciclo).

Archivos: `src/pipeline_core.py` (pasada única), `src/langchain_monitor.py` (cadena LCEL), `src/monitor_tick_log.py` (escribe `.monitor_ticks.jsonl` y `.monitor_status.json` en M2 para el **dashboard Django** → `/monitor/`).

## Mensaje (criterio ~10 s)

El texto incluye: **zona**, **nivel de riesgo**, **qué se espera**, **paralelo histórico**, **acción con X→Y MXN** y **minutos**, **zonas secundarias**. La lógica está en `src/rag_chain.py` (`SCHEMA_INSTRUCTION`, `validate_operator_payload`, `json_to_telegram_message`).

## Memoria / debounce (bonus)

- Variable **`ALERT_DEBOUNCE_TTL_SEC`** en `caso_tecnico/.env` (segundos). Por defecto **2700** (45 min) si no está definida.
- Misma lógica que M2: no repite la misma severidad en la misma zona hasta que pase el TTL; **sí** permite escalada (p. ej. MEDIO → CRITICO).
- Si el motor **suprime** el envío por debounce, el agente envía igualmente un **mensaje corto a Telegram** (zona, riesgo, motivo), salvo que uses **`--dry-run`**.

## Registro y resumen diario (bonus)

Cada alerta **enviada a Telegram** (sin `--dry-run`) se añade a **`modulo2_motor_alertas/.alert_events.jsonl`** (no se sube a git).

```bash
# Ver resumen en consola (hoy, zona horaria Monterrey)
python modulo3_agente_telegram/run_agent.py --daily-summary --dry-run

# Enviar resumen al canal
python modulo3_agente_telegram/run_agent.py --daily-summary

# Fecha concreta + sin llamar al archivo meteorológico
python modulo3_agente_telegram/run_agent.py --daily-summary --summary-date 2025-03-19 --no-archive --dry-run
```

**Cron (ejemplo 22:00):** `0 22 * * * cd /ruta/caso_tecnico && .venv/bin/python modulo3_agente_telegram/run_agent.py --daily-summary`

El resumen contrasta el **pronóstico al momento del envío** con la **máx. precipitación horaria del archivo Open-Meteo** ese día en el centroide de la zona (proxy de impacto observado vs proyectado).

## Comandos

Las rutas del tipo `modulo3_agente_telegram/run_agent.py` son **desde la raíz del repo** (`caso_tecnico/`), no desde `modulo2_motor_alertas/`.

**Opción A — siempre desde la raíz del repo:**

```bash
cd ~/Documentos/caso_tecnico   # o tu ruta a caso_tecnico
python modulo3_agente_telegram/run_agent.py --demo --dry-run
python modulo3_agente_telegram/run_agent.py --demo --validate
python modulo3_agente_telegram/run_agent.py --demo --force-send
```

**Opción B — estás dentro de `modulo2_motor_alertas/` (u otra subcarpeta):**

```bash
python ../modulo3_agente_telegram/run_agent.py --demo --dry-run
```

**Opción C — script que fija la raíz del repo** (`scripts/run_module3.sh`):

```bash
chmod +x scripts/run_module3.sh   # una vez
./scripts/run_module3.sh --demo --dry-run
./scripts/run_module3.sh --demo --validate
./scripts/run_module3.sh --test-telegram
./scripts/run_module3.sh --daily-summary --dry-run
```

El **monitor en bucle** se lanza con `python modulo3_agente_telegram/monitor_loop.py` (ver sección *Monitor continuo*).

## No veo los mensajes en el canal

1. **Prueba solo Telegram** (sin clima ni motor):
   ```bash
   cd ~/Documentos/caso_tecnico
   python modulo3_agente_telegram/run_agent.py --test-telegram
   ```
   Si falla, el error suele indicar token revocado, `chat_id` mal o **falta de permisos**.

2. **Canal (p. ej. @examen_rappi)**  
   - El bot debe ser **administrador** del canal con **“Publicar mensajes”**.  
   - Invítalo desde ajustes del canal → administradores.  
   - `TELEGRAM_CHAT_ID`: prueba `@examen_rappi` (con @) o el id numérico `-100xxxxxxxxxx` (sacarlo con @userinfobot o la API `getUpdates` tras un mensaje al bot).

3. **`.env` en la raíz del repo**  
   El script carga `caso_tecnico/.env`, no un `.env` dentro de `modulo3_agente_telegram/`.

4. **Debounce**  
   Sin `--force-send`, una segunda ejecución igual puede **no enviar** (`(Debounce) ...`). Para probar alertas reales:  
   `python modulo3_agente_telegram/run_agent.py --demo --force-send`

5. **`--dry-run`**  
   Solo imprime en consola; **no** envía a Telegram.

## Q&A arquitectura (presentación)

Ver `docs/qa_arquitectura.md` (falsos positivos, alert fatigue, escalado a otras ciudades).

## Más

- Diagrama corto: `latex/arquitectura_agente.tex`.
