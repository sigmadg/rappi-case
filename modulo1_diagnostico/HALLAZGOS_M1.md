# Cinco hallazgos cuantificados — Módulo 1 (diagnóstico operacional)

Lista cerrada para **criterio de patrones (rúbrica)**: cada ítem enlaza el **notebook** `notebooks/01_diagnostico_operacional.ipynb` y, donde aplica, **`modulo2_motor_alertas/calibration.json`** (export alineado al M1).

**Guía de demo más amplia** (coherencia M1→M2, negocio, limitaciones, interfaz ops): `../docs/criterios_evaluacion_demo.md`.

**Definiciones usadas en el panel:**  
`ratio = ORDERS / CONNECTED_RT` · saturación = `ratio > 1.8` · saludable (doc) = 0.9–1.2 · panel **30 días × 24 h × 14 zonas = 10 080 filas** (celda de resumen de zonas / exploración).

---

### 1. Estructura del panel y métrica operativa (base para segmentación)

- **Hallazgo:** El histórico es un panel **balanceado por diseño del caso**: 10 080 observaciones (30×24×14); la métrica central es el **ratio** pedidos/repartidores conectados, con clasificación explícita (saturación / saludable / intermedio / sobre-oferta).
- **Dónde:** Notebook — introducción + `describe` tras crear `ratio` y `clasificacion`.
- **Para qué sirve:** Fija el **universo** y los **umbrales de lectura** antes de atribuir efectos a la lluvia.

---

### 2. La precipitación se asocia al ratio **después de controlar hora y zona**

- **Hallazgo:** Correlación Pearson `PRECIPITATION_MM` vs `ratio` ≈ **0,319**. En un **OLS** `ratio ~ PRECIPITATION_MM + C(HOUR) + C(ZONE)`, el coeficiente de precipitación es **estadísticamente significativo** (p-valor efectivamente ~0 en la salida del notebook) y el modelo alcanza **R² ajustado ≈ 0,72** (tabla `summary2` del ajuste en P2).
- **Dónde:** Notebook — bloque **P2** (matriz de correlación + `smf.ols(...)`).
- **Para qué sirve:** Evita quedarse en una **correlación simple**; incorpora **hora** y **zona** como controles para reducir confusión estructural (patrones horarios y heterogeneidad espacial).

---

### 3. Lluvia “fuerte” vs “débil” y saturación (efecto operativo grande)

- **Hallazgo:** Con umbral de **0,5 mm/h** en la hora (misma escala que el pronóstico):  
  **P(saturación | precip > 0,5)** ≈ **0,308** vs **P(saturación | precip ≤ 0,5)** ≈ **0,038** — la primera probabilidad es del orden de **~8×** la segunda (≈0,308 / 0,038).
- **Dónde:** Notebook — **P2**, celdas que imprimen las dos probabilidades condicionales.
- **Para qué sirve:** Cuantifica el **contraste operativo** que justifica alertas tempranas cuando el pronóstico supera umbrales por zona (no solo “correlación positiva”).

---

### 4. Heterogeneidad espacial: la sensibilidad a la lluvia **no es la misma en todas las zonas**

- **Hallazgo:** El export a `calibration.json` normaliza un **índice de sensibilidad** por zona; en el JSON empaquetado **Santiago** concentra el máximo (**`sensitivity_index`: 1,0**) y **`precip_coef`** también es el más alto (**≈ 0,192**), mientras zonas como **Mitras Centro** quedan en el extremo bajo de sensibilidad relativa (**`sensitivity_index` ≈ 0,263**; `precip_coef` ≈ 0,050). El **orden de magnitud mm/h** para mover el ratio en el tramo saludable→saturación (**`mm_precip_healthy_to_saturation_linear`**) va de **~3,1 mm/h (Santiago)** a **~11,9 mm/h (Mitras)** — orden 1:4 entre extremos.
- **Dónde:** `calibration.json` → claves `zones.<nombre>.sensitivity_index`, `precip_coef`, `mm_precip_healthy_to_saturation_linear`; notebook **P3 / sensibilidad** (lógica que replica `export_calibration_from_m1.py`).
- **Para qué sirve:** Fundamenta **umbrales e incentivos distintos por zona** en el motor (M2), no un único umbral global ingenuo.

---

### 5. Calidad de geometría y continuidad M1 → M2

- **Hallazgo:** Del Excel, **12/14** polígonos WKT son parseables; **dos zonas** (Carretera Nacional, Santiago) quedan **sin WKT válido** (truncado típico de Excel ~32k caracteres). El motor de forecast usa entonces **centroides `ZONE_INFO`** como respaldo para Open-Meteo, coherente con el aviso del notebook.
- **Dónde:** Notebook — salida `n_polygons_valid: 12` y lista de zonas; `zones.py` / README M2.
- **Hallazgo complementario (motor):** Los **`alert_precip_mm_hr`** por zona en `calibration.json` se derivan del histórico (p. ej. referencia **6,55 mm/h** donde aplica la regla del export cuando el percentil en saturación es bajo); el **rango** empaquetado va aproximadamente de **0,55 a 6,55 mm/h** según zona — cuantificación explícita de “cuándo alertar” por territorio.

---

## Uso en demo (30 s)

1. Mostrar **tabla o frase** del hallazgo **2** (R² ~0,72 con controles).  
2. Mostrar **números** del hallazgo **3** (0,308 vs 0,038).  
3. Abrir **`calibration.json`** para **Santiago vs Mitras** (hallazgo **4**).  
4. Cerrar con **10 080 filas** y **umbrales por zona** (hallazgos **1** y **5**).

---

## Cómo esto cierra la rúbrica “coherencia end-to-end” y criterio de negocio

| Expectativa del evaluador | Dónde está cubierto en el repo |
|---------------------------|--------------------------------|
| **M1 → M2 no genérico** | `export_calibration_from_m1.py` (y notebook) escribe `calibration.json` con **coeficientes, umbrales y sensibilidad por zona** que el **M2 lee tal cual** (`decision_engine.py`). No hay “constantes mágicas” fuera del pipeline M1 o del JSON exportado. |
| **Reglas con números del dataset** | `alert_precip_mm_hr`, `precip_coef`, `sensitivity_index`, `mm_precip_healthy_to_saturation_linear`, `base_earnings_mxn` salen de definiciones alineadas al notebook (ver README M2 y `HALLAZGOS` arriba). |
| **Pensamiento crítico (limitaciones)** | `docs/retroalimentacion_y_escalado.md` (falsos positivos, feedback, otra ciudad), `modulo3_agente_telegram/docs/qa_arquitectura.md` (Q&A arquitectura). Conviene decir **en voz alta** 2–3 líneas de la siguiente sección. |
| **Orientación al usuario (ops)** | Mensaje Telegram validado (`rag_chain`: checklist ~10 s), debounce, resumen diario, dashboard Django; en demo **mostrar un mensaje real** o `--dry-run` + canal. |

---

## Limitaciones y qué haríamos con más tiempo o datos (30–60 s de discurso)

1. **Pronóstico vs realidad:** Open-Meteo es **forecast**, no observación; con más datos: acoplar **radar/estaciones** o bajar tier si observado ≪ pronosticado (`retroalimentacion_y_escalado.md`).
2. **Panel fijo de 30 días:** coeficientes son **snapshot**; con más tiempo: **recalibración mensual** y A/B de umbrales con feedback de Ops (botón útil/no útil en Telegram).
3. **WKT truncado en 2 zonas:** forecast por **centroide**; con más datos: geometrías completas o rejilla (`geo_pipeline`) para puntos de lluvia más representativos.
4. **Causalidad:** regresión y correlaciones **no prueban causa** solas; el motor es **sistema experto** acotado al caso — se declara en demo, no se vende como “modelo causal total”.

---

## Frase de cierre para el evaluador

> “Los umbrales del motor son el mismo lenguaje que el diagnóstico: mm/h por zona, sensibilidad desde el histórico, incentivos en MXN. Lo genérico es la **tubería**; lo **calibrado** es este Excel y este `calibration.json`.”
