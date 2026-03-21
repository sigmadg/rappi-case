"""
Puente HTTP mínimo para que n8n (p. ej. en Docker) invoque el mismo pipeline que
``run_operational_tick`` sin depender de Execute Command en el host.

Levantar (desde la raíz ``caso_tecnico/``)::

    .venv/bin/pip install -r n8n_bridge/requirements.txt
    .venv/bin/uvicorn n8n_bridge.app:app --host 127.0.0.1 --port 8090

O: ``./scripts/run_n8n_bridge.sh`` (equivalente; usa ``N8N_BRIDGE_HOST`` / ``N8N_BRIDGE_PORT``).

**n8n en Docker:** en el nodo HTTP usa ``http://host.docker.internal:8090/tick`` y arranca el
puente escuchando en todas las interfaces, no solo loopback::

    N8N_BRIDGE_HOST=0.0.0.0 ./scripts/run_n8n_bridge.sh

Si ``uvicorn`` solo usa ``--host 127.0.0.1``, en Linux el tráfico desde el contenedor a
``host.docker.internal`` puede recibir *connection refused* aunque la URL sea correcta.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M2 = ROOT / "modulo2_motor_alertas"
for p in (ROOT / "modulo3_agente_telegram" / "src", M2 / "src"):
    sys.path.insert(0, str(p))

os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, Query
from pipeline_core import run_operational_tick

app = FastAPI(title="caso_tecnico_n8n_bridge", version="0.1")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/tick")
def tick(
    demo: bool = Query(False, description="Serie demo Santiago (sin Open-Meteo real en esa zona)"),
    dry_run: bool = Query(True, description="No enviar a Telegram"),
    force_send: bool = Query(False, description="Ignorar debounce"),
) -> dict:
    """Una pasada operativa; misma función que usa el monitor LangChain."""
    out = run_operational_tick(
        demo=demo,
        dry_run=dry_run,
        force_send=force_send,
        validate=False,
        send_debounce_telegram=True,
    )
    return dict(out)
