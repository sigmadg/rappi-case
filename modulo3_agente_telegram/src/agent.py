"""
Compatibilidad: el flujo principal vive en `rag_chain.py` (RAG-lite + JSON).
Este módulo se mantiene por si se reutilizan tipos auxiliares en extensiones.
"""

from __future__ import annotations  # list[str] en anotaciones

from dataclasses import dataclass  # Contenedor inmutable de contexto legado


@dataclass
class AlertContext:
    """Contexto legado; el motor experto expone `expert_context` en `decision_engine.AlertDecision`."""

    zone: str  # Zona operativa
    risk_label: str  # Etiqueta de riesgo (texto)
    precip_mm_hr: float  # Intensidad de lluvia en la ventana
    horizon_hours: int  # Horas de pronóstico consideradas
    projected_ratio: float  # Ratio operativo proyectado (M1)
    earnings_from: float  # MXN base
    earnings_to: float  # MXN objetivo sugerido
    action_minutes: int  # Ventana de actuación para Ops
    secondary_zones: list[str]  # Otras zonas a vigilar
    historical_note: str  # Texto de paralelo histórico (M1)
