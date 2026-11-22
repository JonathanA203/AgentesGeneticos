"""Ejecuta main.py de Genetic-Algorths importando antes los comportamientos de Behaviour-EDR."""
import runpy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GENETIC_DIR = _HERE.parent / "Genetic-Algorths"
sys.path.insert(0, str(_GENETIC_DIR))
sys.path.insert(0, str(_HERE))

import behaviour_edr_behaviors  # noqa: F401  (registra los comportamientos)

if __name__ == "__main__":
    sys.argv[0] = str(_GENETIC_DIR / "main.py")
    runpy.run_path(str(_GENETIC_DIR / "main.py"), run_name="__main__")
