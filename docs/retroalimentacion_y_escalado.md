# Falsos positivos, feedback y escalado (Q&A)

Guía rápida alineada a rúbrica (demo, limitaciones, checklist): **`criterios_evaluacion_demo.md`** (misma carpeta `docs/`).

## Falsos positivos (lluvia pronosticada que no ocurre)

- Acoplar el motor a **observaciones** (radar / estaciones) en una segunda etapa: si el forecast diverge del observado, bajar el tier o silenciar.
- Ventana de forecast **2h** por defecto (trade-off precisión vs tiempo de reacción documentado en el Módulo 2).

## Loop de retroalimentación (Operaciones)

- Botón o comando en Telegram: **útil / no útil** por `alert_id` (hash de zona + timestamp).
- Registrar en tabla/logs: zona, tier, precip prevista vs real (si se tiene), acción tomada.
- Recalibración periódica de `calibration.json` con nuevos datos.

## Alert fatigue

- **Debounce con escalado** (`.alert_state.json`): no repetir la misma severidad dentro del TTL; sí permitir **MEDIO → CRITICO**.
- **Resumen diario (bonus):** `run_agent.py --daily-summary` — consolida `.alert_events.jsonl` y contrasta pronóstico al envío vs máx. precipitación del archivo Open-Meteo ese día (ver `modulo3_agente_telegram/README.md`).

## Escalado a otras ciudades

- Reemplazar `ZONE_*` + recalibrar coeficientes por ciudad.
- Misma tubería: ingestión → motor experto → JSON → Telegram.
