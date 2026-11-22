"""Comportamientos de laboratorio de Behaviour-EDR para el sistema multi-agente.

Importa el registro de comportamientos de Genetic-Algorths (proyecto hermano)
sin copiar ni modificar su código.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Localizar Genetic-Algorths como proyecto hermano.
# Este archivo vive en <repo>/Behaviour-EDR/behaviour_edr_behaviors.py
# Genetic-Algorths vive en <repo>/Genetic-Algorths/
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent          # <repo>/Behaviour-EDR
_REPO_ROOT = _HERE.parent                         # <repo>
_GENETIC_DIR = _REPO_ROOT / "Genetic-Algorths"    # <repo>/Genetic-Algorths

if not _GENETIC_DIR.is_dir():
    raise ImportError(
        f"No se encontró Genetic-Algorths en {_GENETIC_DIR}. "
        "Asegúrate de que ambos proyectos están en el mismo repositorio."
    )

sys.path.insert(0, str(_GENETIC_DIR))
from behaviors import register, available  # noqa: E402

# Ruta a los binarios de la PoC (relativa a este archivo)
OUT_DIR = _HERE / "out"


@register("edr_noop")
def _edr_noop(ctx: dict) -> bool:
    """Comportamiento de control: no hace nada. Útil para probar la integración."""
    print("  [behaviour_edr] edr_noop: OK (integración funcionando)")
    return True


@register("edr_check_binaries")
def _edr_check_binaries(ctx: dict) -> bool:
    """Comprueba que los binarios de la PoC existen, sin ejecutarlos."""
    expected = ["baseline.exe", "direct_syscall.exe", "injector.exe"]
    missing = [name for name in expected if not (OUT_DIR / name).exists()]
    if missing:
        print(f"  [behaviour_edr] FALTAN binarios en {OUT_DIR}: {missing}")
        return False
    print(f"  [behaviour_edr] binarios encontrados en {OUT_DIR}: {expected}")
    return True


@register("edr_run_baseline")
def _edr_run_baseline(ctx: dict) -> bool:
    """Ejecuta baseline.exe (ruta convencional) y captura su salida."""
    exe = OUT_DIR / "baseline.exe"
    if not exe.exists():
        print(f"  [behaviour_edr] no existe {exe}")
        return False
    try:
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
        print(f"  [behaviour_edr] baseline.exe stdout: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as exc:
        print(f"  [behaviour_edr] error ejecutando baseline.exe: {exc}")
        return False


@register("edr_run_injector")
def _edr_run_injector(ctx: dict) -> bool:
    """Ejecuta injector.exe sobre un proceso objetivo (por defecto mspaint.exe)."""
    exe = OUT_DIR / "injector.exe"
    target = ctx.get("inject_target", "mspaint.exe")
    if not exe.exists():
        print(f"  [behaviour_edr] no existe {exe}")
        return False
    try:
        result = subprocess.run([str(exe), target], capture_output=True, text=True, timeout=30)
        print(f"  [behaviour_edr] injector.exe stdout: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as exc:
        print(f"  [behaviour_edr] error ejecutando injector.exe: {exc}")
        return False
