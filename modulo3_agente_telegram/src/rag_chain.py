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

from __future__ import annotations  # Tipos hacia adelante sin comillas

import json  # Serializar contexto del motor y parsear salida del LLM
import os  # LLM_PROVIDER, URLs, API keys, timeouts
import re  # Quitar fences ```json y extraer objeto; validar “minutos” en action
from typing import Any, Dict, List, Optional, Tuple  # Contratos de funciones públicas/privadas

import requests  # Cliente HTTP para Ollama (/api/chat) sin SDK obligatorio

from ops_logging import get_ops_logger  # Logger unificado del monorepo

_LOG = get_ops_logger("rag_chain")  # Prefijo para filtrar logs de generación de alertas


def _env_int(name: str, default: int, *, min_v: int = 1, max_v: int = 65536) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return max(min_v, min(max_v, v))
    except ValueError:
        return default


def _ollama_json_repair_enabled() -> bool:
    raw = (os.environ.get("OLLAMA_JSON_REPAIR_RETRY") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _strip_trailing_commas_json(s: str) -> str:
    """Quita comas finales ilegales antes de ``}`` / ``]`` (error frecuente en salidas LLM)."""
    out = s
    for _ in range(32):
        nxt = re.sub(r",(\s*[\]}])", r"\1", out)
        if nxt == out:
            return out
        out = nxt
    return out


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


DEFAULT_OLLAMA_MODEL = "mixtral:8x7b-instruct-v0.1-q4_0"  # Valor por defecto si OLLAMA_MODEL vacío

_SYSTEM_PROMPT = (
    "Eres el asistente de Operations Rappi (México). Redactas alertas operativas: un manager debe leer "
    "el mensaje final en unos 10 segundos y saber qué hacer. Sé concreto, sin vaguedades "
    "(nada de 'considerar subir' sin números). Responde únicamente JSON válido."
)  # Rol del sistema para ambos proveedores (Ollama y OpenAI)


def context_from_expert(expert_context: Dict[str, Any]) -> str:
    """Serializa el dict del motor a texto legible para el prompt del LLM."""
    return json.dumps(expert_context, ensure_ascii=False, indent=2)  # Unicode legible + indentación


# --- Parsing tolerante: fences ```json```, texto alrededor, comas finales, JSON truncado vía reintento Ollama.
def _parse_json_llm_output(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text, count=1).strip()

    candidates: List[str] = [text]
    repaired = _strip_trailing_commas_json(text)
    if repaired != text:
        candidates.append(repaired)

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        inner = m.group(0)
        for cand in (inner, _strip_trailing_commas_json(inner)):
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
    return None


# --- Post-procesado: el motor es fuente de verdad para riesgo, zonas secundarias y ventana.
def _merge_llm_with_expert(parsed: Dict[str, Any], expert: Dict[str, Any]) -> Dict[str, Any]:
    """Garantiza campos críticos desde el motor si el LLM omitió o vació."""
    out = dict(parsed)  # Copia superficial para no mutar el dict del parser
    sec_ex = expert.get("secondary_zones") or []  # Lista del motor (autoritativa)
    sec_llm = out.get("secondary_zones")  # Lo que devolvió el modelo
    if not isinstance(sec_llm, list) or len(sec_llm) < len(sec_ex):  # Omitió o acortó
        out["secondary_zones"] = list(sec_ex)  # Sustituir por la lista completa del motor
    am = expert.get("action_minutes", 30)  # Minutos por defecto si falta en contexto
    try:
        tw = int(out.get("time_window_min", am))  # Coaccionar entero desde LLM
    except (TypeError, ValueError):
        tw = int(am)  # Fallback si el LLM puso texto no numérico
    out["time_window_min"] = tw  # Alinear ventana con motor o valor saneado
    if expert.get("risk"):  # Si el motor tiene riesgo, imponerlo al payload
        out["risk_level"] = str(expert["risk"]).upper()  # CRITICO, ALTO, etc.
    z = str(expert.get("zone", ""))  # Nombre de zona para enriquecer headline
    hl = str(out.get("headline", ""))
    if z and z not in hl:  # El checklist exige mencionar zona en headline
        out["headline"] = f"{z} — Riesgo {out.get('risk_level', expert.get('risk', ''))}"

    # Si el modelo alucina earnings distintos al motor, solo se corrige la oración de acción (datos del M2);
    # forecast_summary / historical_parallel siguen siendo redacción del LLM.
    ef, et = expert.get("earnings_from"), expert.get("earnings_to")
    act = str(out.get("action") or "")
    tw_act = int(out.get("time_window_min", expert.get("action_minutes", 30)))
    if ef is not None and et is not None:
        s_ef = str(ef).rstrip("0").rstrip(".") if isinstance(ef, float) else str(ef)
        s_et = str(et).rstrip("0").rstrip(".") if isinstance(et, float) else str(et)
        bad_ef = s_ef not in act and str(ef) not in act
        bad_et = s_et not in act and str(et) not in act
        if bad_ef or bad_et:
            out["action"] = (
                f"Suba los earnings de {ef} a {et} MXN y tome medidas en los próximos {tw_act} minutos."
            )
    return out


def validate_operator_payload(data: Dict[str, Any], expert: Dict[str, Any]) -> List[str]:
    """
    Comprueba criterio enunciado (mensaje accionable ~10 s). Devuelve incumplimientos (vacía = OK).
    Se usa tanto para salida LLM como para la plantilla determinista (pseudo-dict).
    """
    issues: List[str] = []  # Acumulador de strings descriptivos (para logs/UI de validate)
    zone = str(expert.get("zone", ""))
    if not data.get("headline"):
        issues.append("falta headline")
    elif zone and zone not in (data.get("headline") or ""):  # Zona debe ser reconocible
        issues.append("headline no menciona la zona del motor")

    rl = (data.get("risk_level") or "").upper()  # Normalizar mayúsculas
    er = str(expert.get("risk", "")).upper()
    if er and rl != er:  # Coherencia motor ↔ mensaje
        issues.append(f"risk_level ({rl}) no coincide con motor ({er})")

    for key in ("forecast_summary", "historical_parallel", "action"):  # Campos narrativos obligatorios
        if not (data.get(key) or "").strip():
            issues.append(f"falta o vacío: {key}")

    ef = expert.get("earnings_from")  # Número objetivo que debe citarse literalmente
    et = expert.get("earnings_to")
    action = str(data.get("action", ""))
    if ef is not None:
        s_ef = str(ef).rstrip("0").rstrip(".") if isinstance(ef, float) else str(ef)  # Evitar “12.0” vs “12”
        if s_ef not in action and str(ef) not in action:  # Al menos una representación reconocible
            issues.append("action no incluye earnings_from explícito")
    if et is not None:
        s_et = str(et).rstrip("0").rstrip(".") if isinstance(et, float) else str(et)
        if s_et not in action and str(et) not in action:
            issues.append("action no incluye earnings_to explícito")

    if "mxn" not in action.lower():  # Moneda explícita para operaciones
        issues.append("action debería mencionar MXN")

    tw = expert.get("action_minutes", 30)
    if not (  # Ventana temporal en lenguaje natural o dígitos
        re.search(r"\d+\s*min", action.lower())
        or re.search(r"próxim", action.lower())
        or re.search(r"\d+\s*minut", action.lower())
        or str(tw) in action
    ):
        issues.append("action debería mencionar ventana en minutos")

    sec_ex = set(expert.get("secondary_zones") or [])  # Conjunto esperado
    sec_out = set(data.get("secondary_zones") or [])  # Conjunto en el mensaje
    if sec_ex and not sec_ex.issubset(sec_out):  # No se puede omitir ninguna secundaria del motor
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
    secs = ", ".join(sec) if sec else "—"  # Lista vacía → guión tipográfico
    hist = ctx.get("historical_note") or ctx.get("historical_parallel") or ""  # Nota inyectada por pipeline
    prj = ctx.get("projected_ratio", "")
    return (
        f"🚨 {z} — Riesgo {r}\n"
        f"▸ Pronóstico: hasta ~{pr} mm/h (umbral zona {thr} mm/h); ratio proyectado ~{prj}\n"
        f"▸ Histórico: {hist}\n"
        f"▸ ACCIÓN: subir earnings de {ef} a {et} MXN en los próximos {tw} minutos.\n"
        f"▸ Zonas secundarias a vigilar: {secs}"
    )


def _ollama_message_content_to_str(content: Any) -> str:
    """Normaliza `message.content` de Ollama (string o, en algunas versiones, objeto JSON)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content  # Forma más común
    if isinstance(content, dict):  # Algunas builds serializan como objeto
        try:
            return json.dumps(content, ensure_ascii=False)  # Re-stringificar para _parse_json_llm_output
        except (TypeError, ValueError):
            return str(content)  # Último recurso
    return str(content)  # int, list, etc.


def _ollama_chat_options() -> Dict[str, Any]:
    """
    ``num_predict`` por defecto amplio: si queda bajo, el modelo corta a mitad del JSON y caes en plantilla.
    ``num_ctx``: más contexto si el prompt + motor es largo (Mixtral suele soportar 32k; 8k es conservador).
    """
    opts: Dict[str, Any] = {"temperature": 0.1}
    opts["num_predict"] = _env_int("OLLAMA_NUM_PREDICT", 1024, min_v=256, max_v=8192)
    nctx = _env_int("OLLAMA_NUM_CTX", 8192, min_v=2048, max_v=131072)
    opts["num_ctx"] = nctx
    return opts


_REPAIR_SYSTEM = (
    "Eres un corrector de JSON. Tu salida debe ser un único objeto JSON válido (RFC 8259), "
    "sin markdown, sin comillas triples, sin texto antes ni después."
)


def _ollama_repair_json_rag(base: str, model: str, timeout: float, broken_text: str) -> Optional[Dict[str, Any]]:
    """Segunda llamada genérica al mismo modelo: arregla JSON casi válido o truncado (no fija el texto operativo)."""
    snippet = (broken_text or "").strip()[:6000]
    if not snippet:
        return None
    user = (
        "Este bloque debería ser un único objeto JSON con las claves exactas: "
        "headline, risk_level, forecast_summary, historical_parallel, action, time_window_min, secondary_zones. "
        "Puede estar mal formado, truncado o tener comas finales ilegales. "
        "Devuelve SOLO el objeto JSON corregido y completo.\n\n"
        + snippet
    )
    url = f"{base.rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _REPAIR_SYSTEM},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": _env_int("OLLAMA_NUM_PREDICT_REPAIR", 1536, min_v=256, max_v=4096)},
    }
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if not r.ok:
            _LOG.warning("Ollama reparación JSON: HTTP %s", r.status_code)
            return None
        data = r.json()
        raw_content = (data.get("message") or {}).get("content")
        msg = _ollama_message_content_to_str(raw_content)
        return _parse_json_llm_output(msg)
    except requests.RequestException as e:
        _LOG.warning("Ollama reparación JSON: red/timeout: %s", e)
        return None


# --- Proveedor local: API HTTP de Ollama (/api/chat) con format=json.
def _ollama_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")  # Sin barra final
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    timeout = float(os.environ.get("OLLAMA_TIMEOUT_SEC", "180"))  # Modelos grandes pueden tardar
    user = (
        f"Contexto operacional (datos del motor):\n{context_from_expert(context)}\n\n"
        f"{SCHEMA_INSTRUCTION}"
    )  # Un solo mensaje usuario con contexto + esquema
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,  # Respuesta única (más simple de parsear)
        "format": "json",  # Ollama fuerza salida JSON cuando el modelo lo soporta
        "options": _ollama_chat_options(),
    }
    url = f"{base}/api/chat"  # Endpoint chat de Ollama
    try:
        r = requests.post(url, json=payload, timeout=timeout)  # POST síncrono
        if not r.ok:  # 4xx/5xx
            _LOG.warning(
                "Ollama HTTP %s en %s (modelo=%s). Cuerpo: %s",
                r.status_code,
                url,
                model,
                (r.text or "")[:500],
            )
            return None
        data = r.json()  # Cuerpo JSON de Ollama
        raw_content = (data.get("message") or {}).get("content")  # Texto o objeto anidado
        msg = _ollama_message_content_to_str(raw_content)  # Siempre str para el parser
        parsed = _parse_json_llm_output(msg)
        if parsed is None and msg and _ollama_json_repair_enabled():
            _LOG.info("Ollama: JSON ilegible en 1.er intento; reparación (OLLAMA_JSON_REPAIR_RETRY).")
            parsed = _ollama_repair_json_rag(base, model, timeout, msg)
        if parsed is None:
            if msg:
                tip = ""
                if len(msg) >= 800 and not msg.rstrip().endswith("}"):
                    tip = " La salida parece truncada: prueba OLLAMA_NUM_PREDICT=1536 o un modelo más rápido."
                _LOG.warning(
                    "Ollama respondió pero el JSON no es válido (modelo=%s). "
                    "Primeros 280 caracteres: %r.%s",
                    model,
                    msg[:280],
                    tip,
                )
            else:
                _LOG.warning(
                    "Ollama devolvió `message.content` vacío (modelo=%s). ¿El modelo está cargado? `ollama pull %s`",
                    model,
                    model,
                )
        else:
            _LOG.info("Ollama: JSON de alerta parseado OK (modelo=%s)", model)
        return parsed  # Dict o None
    except requests.RequestException as e:  # Timeout, conexión rechazada, DNS, etc.
        _LOG.warning(
            "No se pudo contactar Ollama en %s (%s). Si corres el stack en Docker y Ollama en el host, "
            "pon OLLAMA_BASE_URL=http://host.docker.internal:11434 en .env y arranca Ollama con "
            "OLLAMA_HOST=0.0.0.0 para que escuche fuera de localhost.",
            base,
            e,
        )
        return None
    except (ValueError, KeyError, TypeError) as e:  # r.json() o estructura inesperada
        _LOG.warning("Respuesta Ollama inesperada (no JSON HTTP): %s", e)
        return None


# --- Proveedor nube: LangChain (por defecto) o SDK openai con response_format json_object.
def _openai_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = os.environ.get("OPENAI_API_KEY")  # Sin clave no hay llamada
    if not key:
        return None
    try:
        from openai import OpenAI  # Import perezoso: entorno puede no tener OpenAI
    except ImportError:
        return None

    # LangChain es la ruta por defecto con OpenAI (desactivar con USE_LANGCHAIN=0).
    _lc = (os.environ.get("USE_LANGCHAIN", "1") or "1").lower().strip()
    if _lc not in ("0", "false", "no", "off"):  # LangChain activado
        try:
            lc = _langchain_json(context, key)  # Intento primario
            if lc is not None:
                return lc  # Éxito con LangChain
        except Exception:
            pass  # Caer al SDK directo

    client = OpenAI(api_key=key)  # Cliente oficial
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    user = f"Contexto operacional (datos del motor):\n{context_from_expert(context)}\n\n{SCHEMA_INSTRUCTION}"
    r = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},  # Forzar objeto JSON en modelos compatibles
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    raw = (r.choices[0].message.content or "").strip()  # Primer choice estándar
    return _parse_json_llm_output(raw)


def _langchain_json(context: Dict[str, Any], api_key: str) -> Optional[Dict[str, Any]]:
    try:
        from langchain_core.prompts import ChatPromptTemplate  # Plantilla de mensajes
        from langchain_openai import ChatOpenAI  # Wrapper sobre API OpenAI
    except ImportError:
        return None  # Paquetes opcionales no instalados

    llm = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.1,
        api_key=api_key,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", "{body}"),  # Variable ``body`` con contexto + schema
        ]
    )
    body = context_from_expert(context) + "\n\n" + SCHEMA_INSTRUCTION  # Mismo contenido que SDK path
    chain = prompt | llm  # Pipe de LangChain LCEL
    out = chain.invoke({"body": body})  # AIMessage o similar
    raw = getattr(out, "content", None) or str(out)  # Extraer texto de la respuesta
    return _parse_json_llm_output(str(raw))


# --- Punto de conmutación: LLM_PROVIDER + detección de OPENAI_API_KEY.
def llm_json_rag(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    provider = os.environ.get("LLM_PROVIDER", "auto").lower().strip()
    if provider in ("ollama", "local"):  # Forzar solo Ollama
        return _ollama_json_rag(context)
    if provider == "openai":
        out = _openai_json_rag(context)
        if out is not None:
            return out
        _LOG.warning(
            "LLM_PROVIDER=openai pero OpenAI no devolvió JSON usable; probando Ollama como respaldo."
        )
        return _ollama_json_rag(context)

    if os.environ.get("OPENAI_API_KEY"):  # Modo auto: probar OpenAI primero si hay clave
        out = _openai_json_rag(context)
        if out is not None:
            return out
    return _ollama_json_rag(context)  # Fallback local o si OpenAI falló/devolvió None


def json_to_telegram_message(data: Dict[str, Any]) -> str:
    """Formato escaneable en ~10 s: bloques cortos y jerarquía clara."""
    tw = data.get("time_window_min", 30)  # Entero para la línea de ventana
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
        **expert_context,  # Copia superficial del contexto del motor
        "historical_note": historical_note,  # Clave usada por plantilla y validación cruzada
        "historical_parallel": historical_note,  # Duplicado para prompts que piden “parallel”
    }
    parsed = llm_json_rag(merged)  # Intento de obtener dict estructurado del LLM
    used_llm = parsed is not None  # True si hubo respuesta parseable (aunque luego haya issues)
    if parsed and apply_validation_fixes:  # Corregir headline, riesgo, secundarias desde motor
        parsed = _merge_llm_with_expert(parsed, merged)
    issues: List[str] = []
    if parsed:  # Flujo con LLM (o merge) exitoso
        issues = validate_operator_payload(parsed, merged)  # Checklist de calidad
        text = json_to_telegram_message(parsed)  # Formato final para Telegram
    else:  # Sin LLM: plantilla + pseudo-dict solo para validar gaps
        _LOG.warning(
            "Sin salida JSON del LLM (Ollama/OpenAI inalcanzable, timeout o JSON inválido); "
            "mensaje Telegram con plantilla determinista. Revisa OPS_LOG_LEVEL=INFO y trazas rag_chain."
        )
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
        issues = validate_operator_payload(pseudo, merged)  # Suele estar vacío si plantilla alineada
    return text, issues, used_llm


def generate_telegram_from_rag(
    expert_context: Dict[str, Any],
    historical_note: str,
) -> str:
    """API estable: solo el texto listo para Telegram."""
    text, _, _ = build_telegram_alert(expert_context, historical_note)  # Descartar issues y flag LLM
    return text
