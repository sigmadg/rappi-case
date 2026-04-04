from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .paths import (
    alert_events_jsonl,
    calibration_json,
    data_xlsx,
    figures_dir,
    modulo2_dir,
    monitor_status_json,
    monitor_ticks_jsonl,
    ops_audit_jsonl,
    project_root,
)

# Claves LLM: si el proceso Django heredó ``VAR=`` vacío (p. ej. shell/Compose), el subproceso de
# run_agent también arrancaba con huecos y python-dotenv no rellenaba; se completan desde .env aquí
# y en env_bootstrap.load_repo_dotenv (doble capa).
_LLM_ENV_KEYS = (
    "OLLAMA_BASE_URL",
    "LLM_PROVIDER",
    "OLLAMA_MODEL",
    "OLLAMA_TIMEOUT_SEC",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "USE_LANGCHAIN",
)


def _fill_empty_llm_env_from_dotenv(env: Dict[str, str], repo_root: Path) -> None:
    from dotenv import dotenv_values

    p = repo_root / ".env"
    if not p.is_file():
        return
    parsed = dotenv_values(p)
    for k in _LLM_ENV_KEYS:
        cur = env.get(k)
        if cur is not None and str(cur).strip():
            continue
        v = parsed.get(k)
        if v is not None and str(v).strip():
            env[k] = str(v).strip()


@require_POST
def telegram_force_alert(request: HttpRequest) -> HttpResponse:
    """
    Ejecuta el agente M3 con --force-send (ignora debounce / TTL por zona).
    Requiere .env con TELEGRAM_* en la raíz del repo.
    """
    root = Path(settings.PROJECT_ROOT)
    script = root / "modulo3_agente_telegram" / "run_agent.py"
    if not script.is_file():
        messages.error(request, f"No se encuentra run_agent.py en {script}")
        return redirect("home")

    mode = (request.POST.get("mode") or "demo").lower().strip()
    cmd = [sys.executable, str(script), "--force-send"]
    if mode != "live":
        cmd.insert(-1, "--demo")

    env = os.environ.copy()
    _fill_empty_llm_env_from_dotenv(env, root)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        messages.error(request, "Tiempo agotado (>10 min). Revisa Ollama / red.")
        return redirect("home")
    except Exception as e:
        messages.error(request, str(e))
        return redirect("home")

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        messages.error(
            request,
            f"El agente terminó con código {proc.returncode}. "
            f"{'stderr: ' + err if err else ''} {'stdout: ' + out if out else ''}".strip(),
        )
    else:
        detail = out or "OK (sin salida en consola)."
        if err:
            detail += f" · aviso: {err[:500]}"
        messages.success(request, detail[:2000])

    return redirect("home")


def _safe_read_raw() -> tuple[pd.DataFrame | None, str | None]:
    path = data_xlsx()
    if not path.is_file():
        return None, f"No se encuentra el Excel: {path}"
    try:
        raw = pd.read_excel(path, sheet_name="RAW_DATA")
        return raw, None
    except Exception as e:
        return None, str(e)


def _safe_zone_info() -> tuple[pd.DataFrame | None, str | None]:
    path = data_xlsx()
    if not path.is_file():
        return None, "Sin Excel"
    try:
        return pd.read_excel(path, sheet_name="ZONE_INFO"), None
    except Exception as e:
        return None, str(e)


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    raw, err = _safe_read_raw()
    n_rows = int(len(raw)) if raw is not None else None
    n_zones = int(raw["ZONE"].nunique()) if raw is not None and "ZONE" in raw.columns else None
    cal_path = calibration_json()
    cal_ok = cal_path.is_file()
    cal_mtime_label: str | None = None
    n_cal_zones: int | None = None
    if cal_ok:
        try:
            cal_mtime_label = datetime.fromtimestamp(cal_path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M (local)"
            )
        except OSError:
            pass
        try:
            cal_data = json.loads(cal_path.read_text(encoding="utf-8"))
            z = cal_data.get("zones")
            if isinstance(z, dict):
                n_cal_zones = len(z)
        except (json.JSONDecodeError, OSError):
            pass
    n_figs = len([p for p in figures_dir().glob("*") if p.suffix.lower() in (".png", ".svg", ".jpg", ".jpeg")])
    audit_p = ops_audit_jsonl()
    return render(
        request,
        "viz/home.html",
        {
            "title": "Inicio",
            "n_rows": n_rows,
            "n_zones": n_zones,
            "data_error": err,
            "calibration_ok": cal_ok,
            "calibration_mtime": cal_mtime_label,
            "n_cal_zones": n_cal_zones,
            "n_figures": n_figs,
            "has_audit_log": audit_p.is_file(),
            "project_root": str(project_root()),
        },
    )


@require_GET
def pipeline_view(request: HttpRequest) -> HttpResponse:
    return render(request, "viz/pipeline.html", {"title": "Pipeline M1 → M2 → M3"})


@require_GET
def datos_view(request: HttpRequest) -> HttpResponse:
    raw, err = _safe_read_raw()
    zinfo, _ = _safe_zone_info()
    context: Dict[str, Any] = {
        "title": "Dataset RAW_DATA",
        "error": err,
        "preview_html": None,
        "describe_html": None,
        "zone_info_html": None,
        "chart_labels": [],
        "chart_values": [],
        "chart_labels_json": "[]",
        "chart_values_json": "[]",
        "chart_hours_labels": [],
        "chart_hours_values": [],
        "chart_hours_labels_json": "[]",
        "chart_hours_values_json": "[]",
    }
    if raw is not None:
        preview = raw.head(80)
        context["preview_html"] = preview.to_html(
            classes="table table-sm table-striped table-dark align-middle",
            index=False,
        )
        num = raw.select_dtypes(include=["number"])
        if len(num.columns):
            context["describe_html"] = num.describe().to_html(
                classes="table table-sm table-dark table-striped",
            )
        if zinfo is not None:
            context["zone_info_html"] = zinfo.to_html(
                classes="table table-sm table-striped table-dark align-middle",
                index=False,
            )
        if "ZONE" in raw.columns:
            n_z = raw["ZONE"].nunique()
            n_r = len(raw)
            context["zone_balance_note"] = (
                f"Panel balanceado del caso: {n_r:,} filas ÷ {int(n_z)} zonas = "
                f"{n_r // int(n_z)} filas por zona (30 días × 24 h). "
                "Por eso el número de filas es el mismo en cada zona; el gráfico de barras muestra "
                "la suma de ORDERS (actividad distinta por zona)."
            )
            vc = raw["ZONE"].value_counts().sort_index()
            zdf = vc.rename_axis("ZONA").reset_index(name="filas")
            context["zone_counts_html"] = zdf.to_html(
                classes="table table-sm table-dark table-striped align-middle",
                index=False,
            )
            # Gráfico: suma de pedidos por zona (varía; el conteo de filas es 720/zona en panel balanceado)
            if "ORDERS" in raw.columns:
                oz = raw.groupby("ZONE", sort=True)["ORDERS"].sum().sort_index()
                labels = list(oz.index.astype(str))
                values = [int(x) for x in oz.values]
                context["chart_title"] = "Total de pedidos (ORDERS) por zona"
                context["chart_y_label"] = "Suma de ORDERS en el panel"
            else:
                labels = list(vc.index.astype(str))
                values = [int(x) for x in vc.values]
                context["chart_title"] = "Filas por zona (conteo)"
                context["chart_y_label"] = "Filas"
            context["chart_labels"] = labels
            context["chart_values"] = values
            context["chart_labels_json"] = json.dumps(labels)
            context["chart_values_json"] = json.dumps(values)
        rw = raw.copy()
        if "ORDERS" in rw.columns and "CONNECTED_RT" in rw.columns:
            rw["ratio"] = rw["ORDERS"] / rw["CONNECTED_RT"].replace(0, float("nan"))
        if "HOUR" in rw.columns and "ratio" in rw.columns:
            hr = rw.groupby("HOUR", as_index=False)["ratio"].mean()
            hl = [str(int(h)) for h in hr["HOUR"]]
            hv = [round(float(x), 4) for x in hr["ratio"]]
            context["chart_hours_labels"] = hl
            context["chart_hours_values"] = hv
            context["chart_hours_labels_json"] = json.dumps(hl)
            context["chart_hours_values_json"] = json.dumps(hv)
    return render(request, "viz/datos.html", context)


@require_GET
def calibracion_view(request: HttpRequest) -> HttpResponse:
    path = calibration_json()
    error = None
    data: Dict[str, Any] | None = None
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            error = str(e)
    else:
        error = f"No se encuentra {path}"
    full_json = ""
    if data is not None:
        full_json = json.dumps(data, indent=2, ensure_ascii=False)
    return render(
        request,
        "viz/calibracion.html",
        {
            "title": "Calibración (M2)",
            "calibration": data,
            "calibration_json": full_json,
            "error": error,
            "path": str(path),
        },
    )


@require_GET
def figuras_view(request: HttpRequest) -> HttpResponse:
    root = figures_dir()
    images: List[Dict[str, str]] = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".svg", ".jpg", ".jpeg", ".gif"):
                images.append({"name": p.name})
    return render(
        request,
        "viz/figuras.html",
        {"title": "Figuras Módulo 1", "images": images, "figures_dir": str(root)},
    )


@require_GET
def figure_serve(request: HttpRequest, name: str) -> HttpResponse:
    """Sirve una imagen solo dentro de modulo1_diagnostico/figures (nombre de archivo)."""
    base = (project_root() / "modulo1_diagnostico" / "figures").resolve()
    candidate = (base / Path(name).name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return HttpResponse("No permitido", status=403)
    if not candidate.is_file():
        return HttpResponse("No encontrado", status=404)
    suffix = candidate.suffix.lower()
    ctype = (
        "image/png"
        if suffix == ".png"
        else "image/svg+xml"
        if suffix == ".svg"
        else "image/jpeg"
        if suffix in (".jpg", ".jpeg")
        else "application/octet-stream"
    )
    return HttpResponse(candidate.read_bytes(), content_type=ctype)


def _read_json_dict(path: Path) -> Dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _ops_audit_rows_for_template(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filas listas para tabla HTML (ts, event, zona, detalle)."""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = row.get("ts")
        z = row.get("zone") or row.get("primary_zone") or ""
        out.append(
            {
                "ts": (str(ts)[:28] if ts is not None else ""),
                "event": str(row.get("event", "")),
                "zone": str(z) if z else "—",
                "detail": _audit_detail_short(row),
            }
        )
    return out


def _audit_detail_short(row: Dict[str, Any], max_len: int = 140) -> str:
    """Texto compacto para tabla (excluye ts/event ya mostrados en otras columnas)."""
    skip = {"ts", "event"}
    extra = {k: v for k, v in row.items() if k not in skip and v is not None}
    if not extra:
        return "—"
    s = json.dumps(extra, ensure_ascii=False, default=str)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _read_jsonl_tail(path: Path, n: int) -> List[Dict[str, Any]]:
    """Últimas n líneas válidas, más reciente primero."""
    if not path.is_file() or n <= 0:
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return list(reversed(rows))


def _monitor_context() -> Dict[str, Any]:
    st = monitor_status_json()
    ticks_p = monitor_ticks_jsonl()
    alerts_p = alert_events_jsonl()
    audit_p = ops_audit_jsonl()
    last = _read_json_dict(st)
    tick_rows = _read_jsonl_tail(ticks_p, 100)
    # Alertas: mismas columnas útiles para tabla
    alert_rows = _read_jsonl_tail(alerts_p, 50)
    audit_rows = _read_jsonl_tail(audit_p, 40)
    return {
        "monitor_last": last.get("last") if last else None,
        "monitor_updated_at": (last or {}).get("updated_at"),
        "monitor_ticks": tick_rows,
        "alert_events": alert_rows,
        "ops_audit": audit_rows,
        "ops_audit_display": _ops_audit_rows_for_template(audit_rows),
        "monitor_paths": {
            "status": str(st),
            "ticks": str(ticks_p),
            "alerts": str(alerts_p),
            "audit": str(audit_p),
        },
        "has_tick_log": ticks_p.is_file(),
        "has_audit_log": audit_p.is_file(),
        "m2_dir": str(modulo2_dir()),
    }


@require_GET
def monitor_view(request: HttpRequest) -> HttpResponse:
    ctx = {
        "title": "Monitor M3 (LangChain)",
        **_monitor_context(),
    }
    return render(request, "viz/monitor.html", ctx)


@require_GET
def api_monitor_json(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, **_monitor_context()})


def api_resumen_json(request: HttpRequest) -> JsonResponse:
    raw, err = _safe_read_raw()
    if raw is None:
        return JsonResponse({"ok": False, "error": err}, status=404)
    out: Dict[str, Any] = {
        "ok": True,
        "n_rows": len(raw),
        "columns": list(raw.columns),
        "zones": sorted(raw["ZONE"].dropna().astype(str).unique().tolist()) if "ZONE" in raw.columns else [],
    }
    return JsonResponse(out)
