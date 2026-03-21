"""Rutas al dataset y artefactos del caso (fuera de django_viz/)."""

from pathlib import Path

from django.conf import settings


def project_root() -> Path:
    return Path(settings.PROJECT_ROOT)


def data_xlsx() -> Path:
    return project_root() / "data" / "rappi_delivery_case_data.xlsx"


def calibration_json() -> Path:
    return project_root() / "modulo2_motor_alertas" / "calibration.json"


def figures_dir() -> Path:
    return project_root() / "modulo1_diagnostico" / "figures"


def modulo2_dir() -> Path:
    return project_root() / "modulo2_motor_alertas"


def monitor_status_json() -> Path:
    return modulo2_dir() / ".monitor_status.json"


def monitor_ticks_jsonl() -> Path:
    return modulo2_dir() / ".monitor_ticks.jsonl"


def alert_events_jsonl() -> Path:
    return modulo2_dir() / ".alert_events.jsonl"
