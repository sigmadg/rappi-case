#!/usr/bin/env python3
"""
Bucle de monitorización: cada N segundos consulta Open-Meteo, valida con el motor M2
y envía alertas nuevas a Telegram cuando corresponde (debounce / escalada).

La orquestación de cada ciclo usa LangChain LCEL (``langchain_monitor.build_monitor_chain``).

Uso (desde la raíz ``caso_tecnico/``)::

    python modulo3_agente_telegram/monitor_loop.py
    python modulo3_agente_telegram/monitor_loop.py --interval-sec 300 --dry-run
    python modulo3_agente_telegram/monitor_loop.py --demo --interval-sec 120

Variables opcionales en ``.env``:
    MONITOR_INTERVAL_SEC=600   # default si no pasas --interval-sec

Cada iteración del ``while`` invoca la cadena LangChain (misma pasada operativa que ``run_agent``
sin reescribir reglas): timestamp → ``run_operational_tick`` → log + persistencia ``.monitor_ticks.jsonl``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
M2 = ROOT.parent / "modulo2_motor_alertas"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(M2 / "src"))

load_dotenv(ROOT.parent / ".env")


def _require_telegram_if_monitor_ping() -> None:
    """Si TELEGRAM_MONITOR_PING=1 hace falta python-telegram-bot en este intérprete."""
    raw = (os.environ.get("TELEGRAM_MONITOR_PING") or "0").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return
    try:
        import telegram  # noqa: F401
    except ImportError:
        print(
            "[monitor] ERROR: TELEGRAM_MONITOR_PING=1 pero falta el paquete 'python-telegram-bot' "
            "en este Python. Activa el venv del repo (source .venv/bin/activate) o ejecuta:\n"
            f"  {ROOT.parent / '.venv' / 'bin' / 'python'} {ROOT / 'monitor_loop.py'} ...",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)


from langchain_monitor import build_monitor_chain, default_interval_sec  # noqa: E402
from monitor_tick_log import record_monitor_error  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Monitor Open-Meteo + motor + Telegram (LangChain LCEL)")
    ap.add_argument(
        "--interval-sec",
        type=int,
        default=None,
        help=f"Segundos entre ciclos (default: env MONITOR_INTERVAL_SEC o {default_interval_sec()})",
    )
    ap.add_argument("--dry-run", action="store_true", help="No envía a Telegram")
    ap.add_argument("--demo", action="store_true", help="Simula lluvia en Santiago (sin Open-Meteo)")
    ap.add_argument(
        "--force-send",
        action="store_true",
        help="Ignora debounce en cada ciclo (no recomendado salvo pruebas)",
    )
    ap.add_argument(
        "--no-debounce-telegram",
        action="store_true",
        help="Si debounce bloquea, no enviar aviso corto a Telegram",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta un solo ciclo y termina",
    )
    args = ap.parse_args()
    _require_telegram_if_monitor_ping()

    # Intervalo efectivo: flag CLI > MONITOR_INTERVAL_SEC > default 600 (mín. 15 s en langchain_monitor).
    interval = args.interval_sec if args.interval_sec is not None else default_interval_sec()

    # Estado fijo que recibe cada ``chain.invoke`` (demo/dry-run/force/debounce-telegram).
    base_cfg = {
        "demo": args.demo,
        "dry_run": args.dry_run,
        "force_send": args.force_send,
        "send_debounce_telegram": not args.no_debounce_telegram,
    }

    chain = build_monitor_chain()
    print(
        f"Monitor iniciado (intervalo {interval}s, demo={args.demo}, dry_run={args.dry_run}, "
        f"force_send={args.force_send}). Ctrl+C para detener.",
        flush=True,
    )

    while True:
        try:
            out = chain.invoke(dict(base_cfg))
            print(out.get("log_line", out), flush=True)
            res = out.get("result") or {}
            # En dry-run con alerta preparada, mostrar el cuerpo del mensaje en consola.
            if res.get("status") == "sent" and res.get("dry_run"):
                print("--- Mensaje (dry-run) ---", flush=True)
                print(res.get("text", ""), flush=True)
        except KeyboardInterrupt:
            print("\nMonitor detenido.", flush=True)
            raise SystemExit(0)
        except Exception as e:
            # Excepción no controlada en la cadena: log stderr + línea en monitor_tick (status error).
            print(f"[monitor] error: {e}", flush=True, file=sys.stderr)
            try:
                record_monitor_error(
                    M2,
                    str(e),
                    demo=bool(base_cfg.get("demo")),
                    dry_run=bool(base_cfg.get("dry_run")),
                    force_send=bool(base_cfg.get("force_send")),
                )
            except OSError:
                pass

        if args.once:
            break
        time.sleep(interval)  # espera hasta el próximo ciclo de vigilancia


if __name__ == "__main__":
    main()
