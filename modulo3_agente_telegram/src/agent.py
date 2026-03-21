"""
Compatibilidad: el flujo principal vive en `rag_chain.py` (RAG-lite + JSON).
Este módulo se mantiene por si se reutilizan tipos auxiliares en extensiones.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AlertContext:
    """Contexto legado; el motor experto expone `expert_context` en `decision_engine.AlertDecision`."""

    zone: str
    risk_label: str
    precip_mm_hr: float
    horizon_hours: int
    projected_ratio: float
    earnings_from: float
    earnings_to: float
    action_minutes: int
    secondary_zones: list[str]
    historical_note: str
