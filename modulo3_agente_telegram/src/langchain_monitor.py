"""
Orquestación LangChain (LCEL) para ciclos de monitorización: cada invocación
consulta Open-Meteo, ejecuta el motor M2 y decide envío (debounce / Telegram).

No sustituye las reglas del motor: la \"validación\" de si corresponde alerta nueva
es ``should_emit_alert`` + umbrales; LangChain encadena los pasos de forma explícita.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from langchain_core.runnables import RunnableLambda

from monitor_tick_log import record_monitor_cycle
from pipeline_core import run_operational_tick


# --- Paso 1 de la cadena LCEL: anotar inicio (útil en depuración y en JSON de monitor).
def _stamp_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(cfg)
    out["tick_started_at"] = datetime.now(timezone.utc).isoformat()
    return out


# --- Paso 2: una pasada completa M2+M3 (misma función que usa run_agent en modo operativo).
def _execute_tick(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ejecuta una pasada operativa y adjunta el resultado al estado."""
    result = run_operational_tick(
        demo=bool(cfg.get("demo")),
        force_send=bool(cfg.get("force_send")),
        dry_run=bool(cfg.get("dry_run")),
        validate=False,
        send_debounce_telegram=bool(cfg.get("send_debounce_telegram", True)),
    )
    return {**cfg, "result": result, "tick_finished_at": datetime.now(timezone.utc).isoformat()}


# --- Paso 3: línea humana + escritura en disco para dashboard / tail -f.
def _summarize_for_log(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Línea breve para consola / logs."""
    r = cfg.get("result") or {}
    st = r.get("status", "?")
    z = r.get("zone", "")
    line = f"[monitor] status={st}"
    if z:
        line += f" zone={z}"
    if st == "debounced":
        line += f" reason={r.get('reason', '')}"
    if st == "weather_error":
        d = str(r.get("detail", ""))[:160]
        if d:
            line += f" detail={d}"
    cfg["log_line"] = line
    try:
        record_monitor_cycle(cfg)
    except OSError:
        pass
    return cfg


def build_monitor_chain():
    """
    Cadena: marcar tiempo → ejecutar tick operativo → resumen para log.

    Uso::

        chain = build_monitor_chain()
        out = chain.invoke({"demo": False, "dry_run": False, "force_send": False})
    """
    return (
        RunnableLambda(_stamp_config)
        | RunnableLambda(_execute_tick)
        | RunnableLambda(_summarize_for_log)
    )


def run_monitor_cycle(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Un ciclo completo (invoca la cadena LangChain)."""
    cfg = config or {}
    chain = build_monitor_chain()
    return chain.invoke(cfg)


def default_interval_sec() -> int:
    raw = (os.environ.get("MONITOR_INTERVAL_SEC") or "600").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 600
