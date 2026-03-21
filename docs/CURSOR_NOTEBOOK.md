# Cursor: notebook `.ipynb` no abre o error de webview / ServiceWorker

## Diagnóstico (lo que vimos en logs)

1. **Error de webview:** `Could not register service worker` → caché corrupta del motor Chromium de Cursor (no es el archivo `.ipynb`).
2. **Kernel equivocado:** en logs aparece `/usr/bin/python3` con error `No module named ipykernel_launcher`. El intérprete del sistema **no** tiene el kernel; el proyecto sí lo tiene en **`.venv`**.

El archivo `01_diagnostico_operacional.ipynb` es JSON válido; el problema es **Cursor + intérprete + caché**.

---

## Paso A — Abrir el workspace correcto

Abre la carpeta **`caso_tecnico`** con **File → Open Folder** (no solo el archivo suelto, ni un directorio padre enorme).

Así `${workspaceFolder}` apunta a donde está `.venv/`.

---

## Paso B — Elegir el Python del proyecto (obligatorio)

1. `Ctrl+Shift+P` → **Python: Select Interpreter**
2. Elige: **`./.venv/bin/python`** (Python 3.13.x del proyecto)

O el que muestre la ruta completa a `Documentos/caso_tecnico/.venv/bin/python`.

3. Abre el `.ipynb` → **Select Kernel** (arriba a la derecha) → **Python Environments** → el mismo **`.venv`**.

Si el kernel sigue apuntando a `/usr/bin/python3`, el notebook puede fallar aunque el visor funcione.

---

## Paso C — Limpiar caché de Cursor (webview / ServiceWorker)

1. **Cierra Cursor por completo.**
2. En terminal:

```bash
chmod +x scripts/limpiar_cache_cursor.sh
./scripts/limpiar_cache_cursor.sh
```

3. Vuelve a abrir Cursor y la carpeta `caso_tecnico`.

*(Opcional manual: borrar solo `~/.config/Cursor/Cache`, `Code Cache`, `Service Worker`, `GPUCache` con Cursor cerrado.)*

---

## Paso D — Si sigue fallando el visor

- Actualiza Cursor.
- Prueba **Help → Toggle Developer Tools** y revisa la consola al abrir el `.ipynb`.
- Mientras tanto: `jupyter lab` en terminal con `.venv` activado, o abre el **`.html`** exportado en el navegador.

---

## Extensiones recomendadas

- **Python** (Microsoft)
- **Jupyter** (Microsoft)

En este repo, `.vscode/extensions.json` puede sugerirlas al abrir el proyecto.
