# Guía: criterios de evaluación y qué mostrar en demo

Documento de apoyo para **coherencia end-to-end**, **criterio de negocio**, **pensamiento crítico** y **orientación al usuario**. Todo lo listado ya existe en el repo; esta guía solo **ordena** qué abrir o decir.

---

## 1. Coherencia analítica → operacional (M1 → M2)

| Qué demostrar | Evidencia en repo | Acción en demo (60 s) |
|---------------|-------------------|------------------------|
| Los hallazgos del diagnóstico alimentan las reglas | `export_calibration_from_m1.py` → `calibration.json` → `decision_engine.py` | Abrir **una zona** en `calibration.json` y nombrar **de dónde sale** cada campo (`precip_coef`, `alert_precip_mm_hr`, …). |
| No es un sistema genérico | Umbrales **distintos por zona** en JSON | Comparar **Santiago vs Mitras** (`sensitivity_index`, `mm_precip_healthy_to_saturation_linear`). |
| Trazabilidad explícita | `modulo1_diagnostico/HALLAZGOS_M1.md` | Leer la tabla *“Cómo esto cierra la rúbrica”* o la **frase de cierre**. |

---

## 2. Criterio de negocio (números, no intuición)

| Qué demostrar | Evidencia | Acción en demo |
|---------------|-----------|----------------|
| Reglas cuantificadas | Notebook P2 + `calibration.json` | Mencionar **R² ~0,72** con `C(HOUR)+C(ZONE)` y **P(sat\|lluvia fuerte)** vs **P(sat\|lluvia débil)** (~0,31 vs ~0,04). |
| Acciones concretas | Motor + M3 | Mostrar **earnings X→Y MXN** y **minutos** en salida `--dry-run` o Telegram. |

Detalle numérico: **`HALLAZGOS_M1.md`** (cinco hallazgos).

---

## 3. Pensamiento crítico (limitaciones + siguiente iteración)

| Tema | Documento | Frase tipo (15 s cada una) |
|------|-----------|----------------------------|
| Forecast ≠ observado | `docs/retroalimentacion_y_escalado.md` | “Si tuviéramos radar/estaciones, podríamos confirmar antes de escalar tier.” |
| Panel 30 días = snapshot | `HALLAZGOS_M1.md` → sección limitaciones | “Recalibración periódica y feedback útil/no útil en Telegram.” |
| WKT truncado | Notebook + `zones.py` | “Dos zonas sin polígono completo: usamos centroide; con geometrías completas mejoraría el punto de clima.” |
| No confundir correlación con causa | `HALLAZGOS_M1.md` | “El motor es experto acotado al caso; no afirmamos modelo causal completo.” |
| Q&A arquitectura | `modulo3_agente_telegram/docs/qa_arquitectura.md` | Falsos positivos, alert fatigue, otra ciudad. |

---

## 4. Orientación al usuario (ops manager de campo)

| Superficie | Qué prueba | Comando o ruta |
|------------|------------|----------------|
| **Mensaje** | Legible en ~10 s, acción clara | `run_agent.py --demo --dry-run` o mensaje real en canal |
| **Validación** | Checklist del enunciado | `run_agent.py --demo --validate` |
| **Anti-spam** | Debounce + escalada | Explicar TTL; opcional mostrar aviso corto de debounce |
| **Dashboard** | Datos + calibración + monitor | `django_viz/` → `/`, `/calibracion/`, `/monitor/` |
| **Resumen del día** | Contraste eventos vs archivo | `run_agent.py --daily-summary --dry-run` |

---

## 5. Checklist rápido el día de la demo

- [ ] `pip install -r requirements.txt` en venv limpio (o verificar antes).
- [ ] `.env` con Telegram si hay envío real; si no, plan B: `--demo --dry-run`.
- [ ] Abrir `HALLAZGOS_M1.md` o PDF de presentación en la slide de **5 hallazgos**.
- [ ] Abrir `calibration.json` (dos zonas).
- [ ] Terminal: `run_alert_engine.py --demo` y `run_agent.py --demo --dry-run`.
- [ ] (Opcional) Navegador: `django_viz` + `/monitor/` si el monitor corrió al menos una vez.

---

## Referencias cruzadas

| Archivo | Contenido |
|---------|-----------|
| `modulo1_diagnostico/HALLAZGOS_M1.md` | 5 hallazgos + coherencia rúbrica + limitaciones |
| `docs/arquitectura_codigo.md` | Mapa técnico del código |
| `docs/retroalimentacion_y_escalado.md` | Falsos positivos, feedback, escalado |
| `modulo3_agente_telegram/docs/qa_arquitectura.md` | Preguntas típicas de arquitectura |
| `demo_caso_tecnico/presentacion_demo.pdf` | Slides (incl. hallazgos M1 y riesgos) |
