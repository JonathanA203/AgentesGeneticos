"""Gestión de persistencia de estado (checkpoints) del proceso padre."""

from __future__ import annotations

import json
import os
from typing import Any

def save_checkpoint(state_dict: dict[str, Any], filepath: str) -> None:
    """Guarda el estado de forma atómica para evitar corrupción."""
    # Asegurar que el directorio existe
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    tmp_path = f"{filepath}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, indent=2)
            f.flush()
            os.fsync(f.fileno()) # Fuerza la escritura física en disco
        os.replace(tmp_path, filepath) # Reemplazo atómico a nivel de SO
    except Exception as e:
        print(f"[ERROR] No se pudo guardar checkpoint: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def load_checkpoint(filepath: str) -> dict[str, Any] | None:
    """Carga el estado desde disco. Devuelve None si no existe o está corrupto."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] No se pudo cargar checkpoint: {e}")
        return None