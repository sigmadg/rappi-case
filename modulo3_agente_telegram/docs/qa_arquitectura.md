# Preguntas de arquitectura (presentación / Q&A)

Guía unificada (checklist demo, criterios de evaluación): **`../../docs/criterios_evaluacion_demo.md`**.

## ¿Cómo maneja el sistema los falsos positivos?

- El **pronóstico** puede fallar (lluvia que no ocurre). El motor solo alerta si la precipitación **prevista** supera el **umbral calibrado por zona** (`alert_precip_mm_hr` desde histórico), no ante cualquier nube.
- **Debounce** (`modulo2_motor_alertas/.alert_state.json`): no se reenvía la **misma severidad** dentro de un TTL (por defecto ~45 min, **`ALERT_DEBOUNCE_TTL_SEC`** en `.env`), reduciendo spam si el modelo meteorológico oscila.
- **Segunda lectura operativa**: el mensaje indica **ventana de actuación** y números concretos; el manager puede contrastar con radar/observación antes de ejecutar cambios irreversibles.
- Evolución posible: confirmación con **observaciones reales** (API o estación) antes de escalar a CRITICO.

## ¿Cómo se evita la alert fatigue?

- Umbral **por zona** (no alerta global por gotas).
- Ventana **corta** (p. ej. 2 h de forecast) y mensaje **único** por escalada relevante gracias al debounce.
- **Resumen diario** (`run_agent.py --daily-summary`): consolida eventos del día desde `.alert_events.jsonl` y contrasta el pronóstico al enviar con la máx. precipitación horaria del **archivo** Open-Meteo ese día (proxy operativo).

## ¿Cómo escalar a otras ciudades?

- **Datos**: un Excel (o pipeline) por ciudad con `RAW_DATA`, `ZONE_INFO`, `ZONE_POLYGONS` y recalibración → `calibration.json` por mercado.
- **Clima**: Open-Meteo es global; parametrizar `timezone` y coordenadas por ciudad.
- **Telegram**: mismo bot puede publicar en canales distintos (`TELEGRAM_CHAT_ID` por ciudad o routing interno).
- **LLM**: mismo prompt; el contexto ya viene estructurado del motor.
