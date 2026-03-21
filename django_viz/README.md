# Dashboard Django — visualización de datos y pipeline

Interfaz web ligera para explorar:

- **Inicio:** resumen (filas del Excel, existencia de `calibration.json`, conteo de figuras M1).
- **Pipeline:** diagrama M1 → M2 → M3 (Mermaid).
- **Datos:** preview de `RAW_DATA`, `describe`, `ZONE_INFO`, gráficos (filas por zona, ratio medio por hora).
- **Calibración:** parámetros por zona desde `modulo2_motor_alertas/calibration.json`.
- **Figuras M1:** galería de imágenes en `modulo1_diagnostico/figures/`.
- **Monitor:** historial del bucle `monitor_loop.py` (LangChain): último ciclo, tabla de ticks y alertas Telegram recientes. Lee `modulo2_motor_alertas/.monitor_status.json` y `.monitor_ticks.jsonl` (el servidor Django no arranca el monitor).
- **API:** `GET /api/resumen.json` — metadatos del panel; `GET /api/monitor.json` — mismo contenido que la página Monitor (útil para refresco automático).
- **Inicio → Forzar Telegram:** botones que ejecutan el Módulo 3 con `--force-send` (sin debounce). **Demo** garantiza envío; **en vivo** depende de umbrales. Solo para entorno local de confianza (cualquiera con acceso al dashboard puede disparar el bot).

## Requisitos

Desde la raíz `caso_tecnico/` (mismo `venv` que el resto del proyecto):

```bash
pip install -r requirements.txt
cd django_viz
python manage.py migrate
python manage.py runserver
```

Abre <http://127.0.0.1:8000/>.

### Monitor + dashboard a la vez

Desde la **raíz** del repo (no hace falta `cd django_viz`):

```bash
./scripts/run_stack.sh
```

Arranca `monitor_loop.py` en segundo plano y Django en primer plano; la página **`/monitor/`** irá mostrando ticks mientras corre. Opciones: `./scripts/run_stack.sh --help` (p. ej. `--dry-run`, `--front-only`, `--port 8080`).

### Puerto 8000 ocupado

Con **`scripts/run_stack.sh`**, si 8000 está ocupado se elige automáticamente el siguiente libre (8001, …) y se avisa en consola.

Si ejecutas Django a mano y ves `Error: That port is already in use`, usa otro puerto:

```bash
python manage.py runserver 8080
```

→ <http://127.0.0.1:8080/>

O cierra el proceso que sigue escuchando en 8000 (a menudo un `runserver` anterior): en otra terminal, `pkill -f "manage.py runserver"` (solo si es tuyo). Para forzar error si el puerto pedido está ocupado (sin auto-incremento): `RUN_STACK_STRICT_PORT=1 ./scripts/run_stack.sh`.

## Rutas

| URL | Descripción |
|-----|-------------|
| `/` | Inicio |
| `/pipeline/` | Diagrama del flujo |
| `/datos/` | Tablas y gráficos |
| `/calibracion/` | JSON de calibración |
| `/figuras/` | Galería notebook |
| `/monitor/` | Ciclos del monitor M3 + alertas enviadas (lectura de archivos locales) |
| `/api/resumen.json` | JSON con filas, columnas y zonas |
| `/api/monitor.json` | Estado último tick + listas de ticks y eventos de alerta |

Los datos se leen de `../data/rappi_delivery_case_data.xlsx` respecto a esta carpeta (raíz del repo `caso_tecnico/`).

**Nota:** `SECRET_KEY` y `DEBUG=True` son solo para desarrollo local; no despliegues así en producción sin endurecer configuración.
