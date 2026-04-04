"""
Mensajes opcionales de **monitor en vivo** a Telegram cuando no hubo alerta completa.

- ``TELEGRAM_MONITOR_PING=1``: envía un texto corto de estado (p. ej. ``no_alert``, error de clima)
  para confirmar que el bucle sigue corriendo, sin repetir la alerta operativa larga.
- ``TELEGRAM_MONITOR_PING_MIN_SEC``: tiempo mínimo entre pings (anti-spam). Si **no** lo defines,
  se usa ``MONITOR_INTERVAL_SEC`` para que no haya un solo ping y luego silencio hasta 5 min.

Las **alertas reales** (LLM + plantilla) solo se envían cuando el motor + debounce lo permiten;
este ping no sustituye una alerta ni fuerza ``force_send``.
"""

from __future__ import annotations  # Dict[str, Any]

import os  # TELEGRAM_MONITOR_PING*, MONITOR_INTERVAL_SEC
import time  # Throttle por archivo de último ping
from datetime import datetime, timezone  # Cabecera “Hora UTC” en el mensaje
from pathlib import Path  # m2_root / .telegram_monitor_ping_ts
from typing import Any, Dict  # Resultado del tick serializado en texto corto

from ops_logging import get_ops_logger  # Misma jerarquía caso_tecnico.* que el resto del repo

_LOG = get_ops_logger("monitor_ping")

_TS_NAME = ".telegram_monitor_ping_ts"  # Último epoch float escrito tras ping exitoso


def monitor_ping_enabled() -> bool:
    raw = (os.environ.get("TELEGRAM_MONITOR_PING") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def monitor_ping_min_sec() -> int:
    explicit = (os.environ.get("TELEGRAM_MONITOR_PING_MIN_SEC") or "").strip()
    if explicit:
        raw = explicit
    else:
        # Mismo ritmo que el bucle del monitor (evita: 1.er ping OK y luego nada hasta 300 s).
        raw = (os.environ.get("MONITOR_INTERVAL_SEC") or "600").strip()
    try:
        return max(15, min(int(raw), 86400))  # Entre 15 s y 1 día
    except ValueError:
        return 300


def _throttle_allows(m2_root: Path) -> bool:
    path = m2_root / _TS_NAME
    min_sec = monitor_ping_min_sec()
    if not path.is_file():
        return True  # Primera vez: permitir
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True  # Archivo corrupto: no bloquear para siempre
    elapsed = time.time() - last
    if elapsed >= float(min_sec):
        return True
    _LOG.debug(
        "monitor ping omitido: throttle %.0f/%.0f s (~%.0f s restantes)",
        elapsed,
        float(min_sec),
        float(min_sec) - elapsed,
    )
    return False


def _mark_ping_sent(m2_root: Path) -> None:
    path = m2_root / _TS_NAME
    try:
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass  # Throttle en memoria fallaría en siguiente arranque; aceptable


def _format_ping(out: Dict[str, Any]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st = str(out.get("status", "?"))
    detail = (out.get("detail") or out.get("reason") or "")[:280]
    zone = out.get("zone")
    risk = out.get("risk")
    lines = [
        "📡 Monitor — caso Rappi",
        f"Hora: {ts}",
        f"Estado: {st}",
    ]
    if zone:
        lines.append(f"Zona: {zone}")
    if risk:
        lines.append(f"Riesgo: {risk}")
    if detail:
        lines.append(f"Detalle: {detail}")
    lines.append("(Ping de vigilancia; no es alerta operativa completa.)")
    return "\n".join(lines)


def maybe_send_monitor_status_ping(
    m2_root: Path,
    out: Dict[str, Any],
    *,
    dry_run: bool,
    validate: bool,
    telegram_already_sent: bool,
) -> None:
    """
    ``telegram_already_sent``: True si este tick ya mandó a Telegram la **alerta larga** o el
    **aviso de debounce**. En ``debounced`` seguimos pudiendo enviar el ping de monitor (latido
    distinto al texto ⏸️ Debounce); si ya se envió ``sent`` (alerta completa), no duplicar.
    """
    if validate:
        return  # Modo checklist sin Telegram
    if not monitor_ping_enabled():
        return
    st = str(out.get("status") or "")
    if telegram_already_sent:
        # Alerta larga ya en Telegram → no añadir ping. Debounce sí deja pasar el ping de vigilancia.
        if st != "debounced":
            return
    # La alerta larga no se envía en dry_run (solo consola); el ping corto sí puede ir a Telegram
    # si TELEGRAM_MONITOR_PING=1.
    if not _throttle_allows(m2_root):
        return
    try:
        from telegram_sender import send_message  # Import perezoso: mismo venv que el monitor
    except ImportError:
        _LOG.warning(
            "monitor ping omitido: no se importó telegram_sender (¿falta python-telegram-bot "
            "en el mismo Python que ejecuta el monitor? Usa el venv: .venv/bin/python ...)."
        )
        return
    text = _format_ping(out)
    try:
        send_message(text)
    except RuntimeError as e:
        _LOG.warning("monitor ping no enviado: %s", e)
        return
    _mark_ping_sent(m2_root)
    try:
        from ops_audit import append_audit

        append_audit(m2_root, "monitor_status_ping_sent", status=out.get("status"))
    except OSError:
        pass
