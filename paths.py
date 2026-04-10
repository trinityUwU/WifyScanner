"""Chemins projet partagés (API, control, collecteur lancé depuis l'API)."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("CYBERALPHA_ROOT", Path(__file__).resolve().parent)).resolve()


def get_db_path() -> str:
    raw = os.environ.get("CYBERALPHA_DB", "wifi_heatmap.db")
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    return str(p)
