# Entorno virtual + Jupyter (proyecto caso Rappi)

## 1. Crear el venv (solo la primera vez)

Desde la carpeta `caso_tecnico`:

```bash
cd /ruta/a/caso_tecnico
python3 -m venv .venv
```

## 2. Activar el entorno

**Linux / macOS:**

```bash
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.venv\Scripts\Activate.ps1
```

## 3. Instalar dependencias (incluye Jupyter)

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Kernel de Jupyter para el notebook

Para que en **Jupyter Lab** / **VS Code** aparezca un kernel con nombre explícito:

```bash
python -m ipykernel install --user --name=caso-rappi --display-name="Python (.venv caso_rappi)"
```

(Con el venv activado, `python` es el de `.venv`.)

En **VS Code** también puedes elegir directamente el intérprete:  
`./.venv/bin/python` → **Select Kernel** → Python del proyecto.

## 5. Probar Jupyter

```bash
jupyter lab
# o
jupyter notebook
```

Abre `modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb` y selecciona el kernel **Python (.venv caso_rappi)** o el intérprete `.venv`.

## No se ven tablas ni gráficos en VS Code

1. Instala la extensión oficial **Jupyter** (Microsoft) y **Python** (Microsoft).
2. Abre la carpeta **`caso_tecnico`** como workspace (no solo el archivo suelto).
3. **Select Kernel** → elige el Python de `.venv`.
4. La primera celda de código incluye **`%matplotlib inline`**: vuelve a ejecutarla y luego las que generan gráficos (`Run All` desde arriba).
5. Si la salida sigue vacía: **View → Appearance → Reset Zoom** o reinicia la ventana (`Developer: Reload Window`).

## No se abre el notebook (vista en blanco)

Si ves celdas vacías o el archivo no renderiza, cierra el `.ipynb` y ábrelo de nuevo; evita duplicar celdas vacías al pegar contenido.
