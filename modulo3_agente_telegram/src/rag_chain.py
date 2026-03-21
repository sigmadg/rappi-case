"""
RAG-lite: el \"retrieval\" es el diccionario estructurado del motor experto (Módulo 2).
El LLM redacta en JSON fijo → mensaje Telegram escaneable en ~10 s para un Operations Manager.

Proveedores: Ollama (Mixtral por defecto) u OpenAI (``LLM_PROVIDER``).
Orquestación **OpenAI**: LangChain (``ChatPromptTemplate | ChatOpenAI``) por defecto; ``USE_LANGCHAIN=0`` fuerza el SDK ``openai`` directo.

Flujo de ``build_telegram_alert`` (punto de entrada desde ``pipeline_core``):
  1) Armar contexto con nota histórica.
  2) ``llm_json_rag`` → JSON según ``SCHEMA_INSTRUCTION`` (Ollama / OpenAI / auto).
  3) Si hay JSON: fusionar con datos del motor y validar con ``validate_operator_payload``.
  4) Si no hay LLM: ``_fallback_message`` + validación sobre pseudo-JSON.
  5) ``json_to_telegram_message`` formatea el texto final para Telegram.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Prompt: el LLM solo ve el JSON del motor + estas reglas de salida (esquema fijo).
# ---------------------------------------------------------------------------
SCHEMA_INSTRUCTION = """
Devuelve SOLO un JSON válido con estas claves exactas (sin markdown ni texto extra):
{
  "headline": "Una línea: zona afectada + nivel de riesgo en mayúsculas (BAJO|MEDIO|ALTO|CRITICO)",
  "risk_level": "CRITICO|ALTO|MEDIO|BAJO",
  "forecast_summary": "1-2 frases: qué se espera en la ventana (lluvia mm/h, horizonte) y por qué importa",
  "historical_parallel": "1-2 frases: patrón comparable del histórico Monterrey (dataset 30 días) — p.ej. lluvia fuerte asociada a más saturación",
  "action": "Oración imperativa con números EXACTOS: subir earnings de X a Y MXN (usa earnings_from y earnings_to del contexto). Menciona actuar en los próximos Z minutos (usa action_minutes del contexto).",
  "time_window_min": número entero (minutos para actuar; debe coincidir con action_minutes del contexto si está presente),
  "secondary_zones": ["nombre1", "nombre2", ...]
}

Reglas:
- risk_level debe coincidir con el campo "risk" del contexto (mismo nivel).
- action DEBE incluir los números literales de earnings_from y earnings_to del contexto (MXN).
- secondary_zones: al menos las mismas zonas que en el contexto "secondary_zones" (puedes ordenar distinto pero no omitir).
"""


DEFAULT_OLLAMA_MODEL = "mixtral:8x7b-instruct-v0.1-q4_0"

_SYSTEM_PROMPT = (
    "Eres el asistente de Operations Rappi (México). Redactas alertas operativas: un manager debe leer "
    "el mensaje final en unos 10 segundos y saber qué hacer. Sé concreto, sin vaguedades "
    "(nada de 'considerar subir' sin números). Responde únicamente JSON válido."
)


def context_from_expert(expert_context: Dict[str, Any]) -> str:
    """Serializa el dict del motor a texto legible para el prompt del LLM."""
    return json.dumps(expert_context, ensure_ascii=False, indent=2)


# --- Parsing tolerante: modelos a veces envuelven JSON en ```json ... ``` o añaden texto.
def _parse_json_llm_output(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text, count=1)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


# --- Post-procesado: el motor es fuente de verdad para riesgo, zonas secundarias y ventana.
def _merge_llm_with_expert(parsed: Dict[str, Any], expert: Dict[str, Any]) -> Dict[str, Any]:
    """Garantiza campos críticos desde el motor si el LLM omitió o vació."""
    out = dict(parsed)
    sec_ex = expert.get("secondary_zones") or []
    sec_llm = out.get("secondary_zones")
    if not isinstance(sec_llm, list) or len(sec_llm) < len(sec_ex):
        out["secondary_zones"] = list(sec_ex)
    am = expert.get("action_minutes", 30)
    try:
        tw = int(out.get("time_window_min", am))
    except (TypeError, ValueError):
        tw = int(am)
    out["time_window_min"] = tw
    if expert.get("risk"):
        out["risk_level"] = str(expert["risk"]).upper()
    z = str(expert.get("zone", ""))
    hl = str(out.get("headline", ""))
    if z and z not in hl:
        out["headline"] = f"{z} — Riesgo {out.get('risk_level', expert.get('risk', ''))}"
    return out


def validate_operator_payload(data: Dict[str, Any], expert: Dict[str, Any]) -> List[str]:
    """
    Comprueba criterio enunciado (mensaje accionable ~10 s). Devuelve incumplimientos (vacía = OK).
    Se usa tanto para salida LLM como para la plantilla determinista (pseudo-dict).
    """
    issues: List[str] = []
    zone = str(expert.get("zone", ""))
    if not data.get("headline"):
        issues.append("falta headline")
    elif zone and zone not in (data.get("headline") or ""):
        issues.append("headline no menciona la zona del motor")

    rl = (data.get("risk_level") or "").upper()
    er = str(expert.get("risk", "")).upper()
    if er and rl != er:
        issues.append(f"risk_level ({rl}) no coincide con motor ({er})")

    for key in ("forecast_summary", "historical_parallel", "action"):
        if not (data.get(key) or "").strip():
            issues.append(f"falta o vacío: {key}")

    ef = expert.get("earnings_from")
    et = expert.get("earnings_to")
    action = str(data.get("action", ""))
    if ef is not None:
        s_ef = str(ef).rstrip("0").rstrip(".") if isinstance(ef, float) else str(ef)
        if s_ef not in action and str(ef) not in action:
            issues.append("action no incluye earnings_from explícito")
    if et is not None:
        s_et = str(et).rstrip("0").rstrip(".") if isinstance(et, float) else str(et)
        if s_et not in action and str(et) not in action:
            issues.append("action no incluye earnings_to explícito")

    if "mxn" not in action.lower():
        issues.append("action debería mencionar MXN")

    tw = expert.get("action_minutes", 30)
    if not (
        re.search(r"\d+\s*min", action.lower())
        or re.search(r"próxim", action.lower())
        or re.search(r"\d+\s*minut", action.lower())
        or str(tw) in action
    ):
        issues.append("action debería mencionar ventana en minutos")

    sec_ex = set(expert.get("secondary_zones") or [])
    sec_out = set(data.get("secondary_zones") or [])
    if sec_ex and not sec_ex.issubset(sec_out):
        issues.append("secondary_zones incompletas respecto al motor")

    return issues


# --- Plantilla determinista (sin LLM): mismos números que el motor, formato tipo checklist.
def _fallback_message(ctx: Dict[str, Any]) -> str:
    """Plantilla determinista: cumple checklist si el LLM no está disponible."""
    z = ctx.get("zone", "")
    r = str(ctx.get("risk", "")).upper()
    pr = ctx.get("forecast_precip_mm_hr", 0)
    thr = ctx.get("threshold_precip_mm_hr", "")
    ef = ctx.get("earnings_from")
    et = ctx.get("earnings_to")
    tw = int(ctx.get("action_minutes", 30))
    sec = ctx.get("secondary_zones") or []
    secs = ", ".join(sec) if sec else "—"
    hist = ctx.get("historical_note") or ctx.get("historical_parallel") or ""
    prj = ctx.get("projected_ratio", "")
    return (
        f"🚨 {z} — Riesgo {r}\n"
        f"▸ Pronóstico: hasta ~{pr} mm/h (umbral zona {thr} mm/h); ratio proyectado ~{prj}\n"
        f"▸ Histórico: {hist}\n"
        f"▸ ACCIÓN: subir earnings de {ef} a {et} MXN en los próximos {tw} minutos.\n"
        f"▸ Zonas secundarias a vigilar: {secs}"
    )


# --- Proveedor local: API HTTP de Ollama (/api/chat) con format=json.
def _ollama_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    timeout = float(os.environ.get("OLLAMA_TIMEOUT_SEC", "180"))
    user = (
        f"Contexto operacional (datos del motor):\n{context_from_expert(context)}\n\n"
        f"{SCHEMA_INSTRUCTION}"
    )
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    try:
        r = requests.post(f"{base}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        msg = (data.get("message") or {}).get("content") or ""
        return _parse_json_llm_output(msg)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


# --- Proveedor nube: LangChain (por defecto) o SDK openai con response_format json_object.
def _openai_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    # LangChain es la ruta por defecto con OpenAI (desactivar con USE_LANGCHAIN=0).
    _lc = (os.environ.get("USE_LANGCHAIN", "1") or "1").lower().strip()
    if _lc not in ("0", "false", "no", "off"):
        try:
            lc = _langchain_json(context, key)
            if lc is not None:
                return lc
        except Exception:
            pass

    client = OpenAI(api_key=key)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    user = f"Contexto operacional (datos del motor):\n{context_from_expert(context)}\n\n{SCHEMA_INSTRUCTION}"
    r = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    raw = (r.choices[0].message.content or "").strip()
    return _parse_json_llm_output(raw)


def _langchain_json(context: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    llm = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.1,
        api_key=api_key,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", "{body}"),
        ]
    )
    body = context_from_expert(context) + "\n\n" + SCHEMA_INSTRUCTION
    chain = prompt | llm
    out = chain.invoke({"body": body})
    raw = getattr(out, "content", None) or str(out)
    return _parse_json_llm_output(str(raw))


# --- Punto de conmutación: LLM_PROVIDER + detección de OPENAI_API_KEY.
def llm_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    provider = os.environ.get("LLM_PROVIDER", "auto").lower().strip()
    if provider in ("ollama", "local"):
        return _ollama_json_rag(context)
    if provider == "openai":
        return _openai_json_rag(context)

    if os.environ.get("OPENAI_API_KEY"):
        out = _openai_json_rag(context)
        if out is not None:
            return out
    return _ollama_json_rag(context)


def json_to_telegram_message(data: Dict[str, Any]) -> str:
    """Formato escaneable en ~10 s: bloques cortos y jerarquía clara."""
    tw = data.get("time_window_min", 30)
    sec = data.get("secondary_zones") or []
    secs = ", ".join(sec) if sec else "—"
    risk = (data.get("risk_level") or "").upper()
    return (
        f"{data.get('headline', 'Alerta operativa')}\n"
        f"──────────────\n"
        f"📍 Nivel: {risk}\n"
        f"🌧️ Qué se espera: {data.get('forecast_summary', '')}\n"
        f"📊 Histórico (referencia): {data.get('historical_parallel', '')}\n"
        f"✅ QUÉ HACER: {data.get('action', '')}\n"
        f"⏱️ Ventana: ~{tw} min\n"
        f"👀 Zonas secundarias: {secs}"
    )


def build_telegram_alert(
    expert_context: Dict[str, Any],
    historical_note: str,
    *,
    apply_validation_fixes: bool = True,
) -> Tuple[str, List[str], bool]:
    """
    Returns:
        (texto_telegram, lista_issues_validación, usó_llm)
    """
    merged = {
        **expert_context,
        "historical_note": historical_note,
        "historical_parallel": historical_note,
    }
    parsed = llm_json_rag(merged)
    used_llm = parsed is not None
    if parsed and apply_validation_fixes:
        parsed = _merge_llm_with_expert(parsed, merged)
    issues: List[str] = []
    if parsed:
        issues = validate_operator_payload(parsed, merged)
        text = json_to_telegram_message(parsed)
    else:
        text = _fallback_message(merged)
        pseudo = {
            "headline": str(merged.get("zone", "")),
            "risk_level": str(merged.get("risk", "")).upper(),
            "forecast_summary": f"Lluvia ~{merged.get('forecast_precip_mm_hr')} mm/h",
            "historical_parallel": historical_note,
            "action": (
                f"subir earnings de {merged.get('earnings_from')} a {merged.get('earnings_to')} "
                f"MXN en los próximos {merged.get('action_minutes', 30)} minutos"
            ),
            "time_window_min": merged.get("action_minutes", 30),
            "secondary_zones": merged.get("secondary_zones") or [],
        }
        issues = validate_operator_payload(pseudo, merged)
    return text, issues, used_llm


def generate_telegram_from_rag(
    expert_context: Dict[str, Any],
    historical_note: str,
) -> str:
    """API estable: solo el texto listo para Telegram."""
    text, _, _ = build_telegram_alert(expert_context, historical_note)
    return text
