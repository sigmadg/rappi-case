#!/usr/bin/env python3
"""
Pipeline: Open-Meteo → motor experto (Módulo 2) → contexto estructurado → RAG-lite (JSON) → Telegram.

Requiere: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

LLM (ver ``LLM_PROVIDER`` en .env):
  - ``ollama``: Ollama local (por defecto ``mixtral:8x7b-instruct-v0.1-q4_0``).
  - ``openai``: OPENAI_API_KEY + JSON mode.
  - ``auto``: OpenAI si hay clave; si no, Ollama.

Con OpenAI: orquestación con LangChain por defecto (USE_LANGCHAIN=0 para SDK openai directo).

Debounce: ALERT_DEBOUNCE_TTL_SEC en .env (por defecto 45 min).
Resumen diario: ``--daily-summary`` (registro en modulo2_motor_alertas/.alert_events.jsonl).

Monitor continuo (LangChain LCEL): ``python monitor_loop.py`` (desde raíz del repo).

Estructura de ``main()`` (de arriba abajo):
  1) Parseo de flags.
  2) Rama ``--test-telegram``: solo diagnóstico de credenciales (sale aquí).
  3) Rama ``--daily-summary``: lee eventos del día y opcionalmente archivo Open-Meteo.
  4) Rama por defecto: ``run_operational_tick`` (clima + motor + debounce + LLM + Telegram).
  5) Interpretación del ``status`` devuelto por el pipeline (códigos de salida al SO).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Rutas: este archivo vive en modulo3_agente_telegram/; M2 es la carpeta hermana.
# Se antepone src/ de M3 y M2 a sys.path para importar pipeline_core, weather_client, etc.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
M2 = ROOT.parent / "modulo2_motor_alertas"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(M2 / "src"))

# Variables de entorno (Telegram, LLM, debounce, clima) desde la raíz del repo.
load_dotenv(ROOT.parent / ".env")

from pipeline_core import M2 as M2_PATH  # noqa: E402
from pipeline_core import run_operational_tick  # noqa: E402
from telegram_sender import ping_telegram_async, send_message  # noqa: E402
from zones import default_data_path, load_centroids  # noqa: E402


def main() -> None:
    # --- CLI: cada flag corresponde a un “modo” de uso distinto (ver docstring del módulo).
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="No envía a Telegram")
    ap.add_argument(
        "--force-send",
        action="store_true",
        help="Ignora debounce (útil para demo en vivo)",
    )
    ap.add_argument(
        "--validate",
        action="store_true",
        help="Imprime checklist del enunciado (10 s) y sale 1 si hay incumplimientos",
    )
    ap.add_argument(
        "--test-telegram",
        action="store_true",
        help="Solo envía un ping a TELEGRAM_CHAT_ID (diagnóstico token + permisos en canal)",
    )
    ap.add_argument(
        "--daily-summary",
        action="store_true",
        help="Resumen del día con alertas registradas y comparación con archivo meteorológico",
    )
    ap.add_argument(
        "--summary-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Fecha del resumen (America/Monterrey). Por defecto: hoy.",
    )
    ap.add_argument(
        "--no-archive",
        action="store_true",
        help="Con --daily-summary: no consultar Open-Meteo archive (solo lista de eventos)",
    )
    args = ap.parse_args()

    # --- Modo diagnóstico: no ejecuta motor ni clima; solo prueba token + permisos en el chat/canal.
    if args.test_telegram:
        try:
            out = asyncio.run(ping_telegram_async())
            print(out)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1)
        return

    # --- Modo resumen: agrega líneas de .alert_events.jsonl del día y (si no --no-archive)
    #     contrasta con precipitación máxima del archivo Open-Meteo por zona afectada.
    if args.daily_summary:
        from daily_summary import build_daily_summary_text, today_in_tz  # noqa: E402

        data_path = default_data_path()
        if not data_path.exists():
            print(f"No se encuentra el dataset: {data_path}", file=sys.stderr)
            raise SystemExit(1)
        centroids = load_centroids(data_path)
        d = date.fromisoformat(args.summary_date) if args.summary_date else today_in_tz()
        text = build_daily_summary_text(
            d,
            M2_PATH,
            centroids,
            include_archive=not args.no_archive,
        )
        if args.dry_run:
            print(text)
        else:
            send_message(text)
            print("Resumen diario enviado a Telegram.")
        return

    # --- Modo operativo estándar: una pasada completa (ver pipeline_core.run_operational_tick).
    r = run_operational_tick(
        demo=args.demo,
        force_send=args.force_send,
        dry_run=args.dry_run,
        validate=args.validate,
        send_debounce_telegram=True,
    )

    # --- Mapeo de estados internos → mensajes en consola y código de salida (0 = OK, 1 = error).
    st = r.get("status")
    if st == "weather_error":
        print(f"Clima no disponible: {r.get('detail', '')}", file=sys.stderr)
        if r.get("failures"):
            print(f"Zonas con fallo: {len(r['failures'])}", file=sys.stderr)
        raise SystemExit(2)
    if st == "no_data":
        print(f"No se encuentra el dataset: {r.get('detail')}", file=sys.stderr)
        raise SystemExit(1)
    # Motor no encontró zona por encima del umbral de precipitación (condiciones normales).
    if st == "no_alert":
        print("Sin alerta: ninguna zona supera umbral.")
        return
    if st == "no_decision":
        print("Sin decisión.")
        return
    # Debounce bloqueó el mensaje largo; puede haberse enviado aviso corto a Telegram.
    if st == "debounced":
        print(f"(Debounce) {r.get('reason', '')}")
        if not args.dry_run:
            print("Aviso de debounce enviado a Telegram." if r.get("debounce_message") else "")
        return
    # Solo validar texto vs checklist del enunciado (sin enviar).
    if st == "validate":
        print("--- Mensaje generado ---")
        print(r.get("text", ""))
        print("--- Validación (criterio Operations Manager) ---")
        print(f"LLM usado: {r.get('used_llm')}")
        issues = r.get("issues") or []
        if issues:
            print("INCUMPLIMIENTOS:")
            for x in issues:
                print(f"  - {x}")
            raise SystemExit(1)
        print("OK: checklist satisfecha.")
        return
    # Alerta generada: dry_run imprime texto; en vivo ya se envió desde pipeline_core.
    if st == "sent":
        if r.get("dry_run"):
            print(r.get("text", ""))
            return
        print("Mensaje enviado a Telegram.")
        return

    print(f"Estado inesperado: {r}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
