"""
Carga de `.env` y ajustes de entorno antes de importar `pipeline_core` / `rag_chain`.

En Docker, el `.env` del repo suele traer ``OLLAMA_BASE_URL=http://127.0.0.1:11434`` (válido solo
en el host). Si esa variable no viene ya corregida del entrypoint/Compose, hay que apuntar al
anfitrión con ``host.docker.internal``.
"""

from __future__ import annotations  # Anotaciones con tipos forward

import os  # Lectura de OLLAMA_* y bandera OLLAMA_DOCKER_USE_LOOPBACK
from pathlib import Path  # Rutas al .env y detección /.dockerenv


def load_repo_dotenv(repo_root: Path) -> None:
    """Carga ``repo_root/.env`` sin pisar variables ya definidas y **no vacías** en el proceso.

    Si el padre exportó ``LLM_PROVIDER=`` u otra clave como cadena vacía, ``load_dotenv(override=False)``
    no la sustituye por el valor del archivo; aquí rellenamos solo cuando el valor actual falta o está
    en blanco (mismo criterio que suele romper el LLM al lanzar ``run_agent`` desde Django/subprocess).
    """
    from dotenv import dotenv_values, load_dotenv  # Valores crudos + carga estándar

    p = repo_root / ".env"  # Convención: raíz del monorepo caso_tecnico
    if not p.is_file():
        return
    # override=False: respeta OLLAMA/TELEGRAM ya inyectadas por Docker/entrypoint (no vacías)
    load_dotenv(p, override=False)
    for k, v in dotenv_values(p).items():
        if not k or v is None:
            continue
        v_str = str(v).strip()
        if not v_str:
            continue
        cur = os.environ.get(k)
        if cur is None or (isinstance(cur, str) and cur.strip() == ""):
            os.environ[k] = v_str


def normalize_ollama_for_docker_container() -> None:
    """Si vamos dentro de un contenedor y la URL es loopback, usar el gateway al host."""
    if not Path("/.dockerenv").is_file():
        return  # Fuera de Docker no se reescribe la URL
    if (os.environ.get("OLLAMA_DOCKER_USE_LOOPBACK") or "").strip() == "1":
        return  # Caso excepcional: Ollama en el mismo contenedor en localhost
    u = (os.environ.get("OLLAMA_BASE_URL") or "").strip().rstrip("/")
    bad = ("", "http://127.0.0.1:11434", "http://localhost:11434")
    if u in bad:
        # El daemon Ollama en la máquina anfitriona se alcanza vía host.docker.internal (Linux + extra_hosts)
        os.environ["OLLAMA_BASE_URL"] = "http://host.docker.internal:11434"
