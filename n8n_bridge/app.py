"""
Puente HTTP para n8n: mismo pipeline que el monitor (POST /tick).
Métricas Prometheus en GET /metrics (proceso uvicorn).
"""

from __future__ import annotations

import sys
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from prometheus_client import make_asgi_app

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modulo3_agente_telegram" / "src"))
sys.path.insert(0, str(ROOT / "modulo2_motor_alertas" / "src"))

from env_bootstrap import load_repo_dotenv, normalize_ollama_for_docker_container  # noqa: E402

load_repo_dotenv(ROOT)
normalize_ollama_for_docker_container()

from pipeline_core import run_operational_tick  # noqa: E402


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from ops_prometheus import ensure_metrics_registered_for_scrape

    ensure_metrics_registered_for_scrape()
    yield


app = FastAPI(title="n8n bridge", version="1.0", lifespan=_lifespan)
app.mount("/metrics", make_asgi_app())


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/tick")
def tick(
    dry_run: bool = Query(False),
    demo: bool = Query(False),
    validate: bool = Query(False),
    force_send: bool = Query(False),
) -> dict:
    return run_operational_tick(
        demo=demo,
        dry_run=dry_run,
        validate=validate,
        force_send=force_send,
    )
