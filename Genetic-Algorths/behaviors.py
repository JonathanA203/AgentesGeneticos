"""Comportamientos extensibles de los procesos hijo (capa de "supervivencia").

Este módulo permite añadir, de forma controlada y por el propio equipo,
comportamientos que el hijo puede ejecutar antes/después de validar su
genoma. Está pensado para el laboratorio de evasión/persistencia:

- Los comportamientos son funciones registradas con un nombre.
- El hijo recibe la lista de nombres por CLI (--behaviors) o por defecto.
- Cada comportamiento recibe el contexto del hijo y puede decidir si
  continuar o abortar.

IMPORTANTE (ámbito académico / laboratorio aislado):
- No se incluyen técnicas reales de persistencia, inyección o evasión de EDR.
- Solo hay simulaciones inocuas (retardos, bucles de bajo perfil, escritura
  de artefactos de laboratorio en una carpeta controlada).
- Cualquier comportamiento nuevo debe implementarse y revisarse por el
  equipo de la tesis dentro del entorno de prueba.

Uso desde el hijo (OptimizerAgent o child_main):

    from behaviors import run_behaviors
    run_behaviors(["low_profile", "lab_artifact"], context={...})
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Callable, Any

from log_config import get_logger

log = get_logger("behaviors")

# Carpeta de artefactos de laboratorio (solo para pruebas; no es persistencia real)
LAB_ARTIFACT_DIR = Path(os.environ.get("AGENTES_LAB_ARTIFACT_DIR", Path(__file__).parent / "logs" / "lab_artifacts"))


BehaviorFn = Callable[[dict[str, Any]], bool]
# Devuelve True si el hijo debe continuar; False para abortar la validación.


_REGISTRY: dict[str, BehaviorFn] = {}


def register(name: str):
    """Decorador para registrar un comportamiento por nombre."""
    def decorator(fn: BehaviorFn):
        _REGISTRY[name] = fn
        return fn
    return decorator


def available() -> list[str]:
    return sorted(_REGISTRY.keys())


def run_behaviors(names: list[str] | None, context: dict[str, Any] | None = None) -> bool:
    """Ejecuta la lista de comportamientos en orden.

    Returns:
        True si todos permitieron continuar; False si alguno abortó.
    """
    context = context or {}
    if not names:
        return True
    for name in names:
        fn = _REGISTRY.get(name)
        if fn is None:
            log.warning(f"comportamiento desconocido '{name}', se omite")
            continue
        log.info(f"ejecutando '{name}'...")
        ok = fn(context)
        if not ok:
            log.warning(f"'{name}' abortó la continuación")
            return False
    return True


# ---------------------------------------------------------------------------
# Comportamientos de laboratorio (simulaciones inocuas)
# ---------------------------------------------------------------------------

@register("noop")
def _noop(ctx: dict) -> bool:
    """No hace nada. Útil como control."""
    return True


@register("low_profile")
def _low_profile(ctx: dict) -> bool:
    """Simula un perfil bajo: pequeños retardos aleatorios y poca actividad de CPU.

    No realiza ninguna acción de evasión real; solo introduce jitter temporal
    para que el monitor/EDR vea un proceso que no es 100 % CPU-bound.
    """
    total = float(ctx.get("low_profile_seconds", 1.5))
    steps = max(1, int(total / 0.15))
    for _ in range(steps):
        time.sleep(0.1 + random.random() * 0.1)
        # Micro-trabajo para no parecer completamente idle
        _ = sum(i * i for i in range(50))
    return True


@register("lab_artifact")
def _lab_artifact(ctx: dict) -> bool:
    """Escribe un artefacto de laboratorio (archivo de texto) en una carpeta
    controlada. Sirve para comprobar que el hijo puede dejar rastro observable
    sin implementar técnicas de persistencia reales.
    """
    LAB_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = ctx.get("run_id", "unknown")
    pid = os.getpid()
    path = LAB_ARTIFACT_DIR / f"artifact_{run_id}_{pid}.txt"
    path.write_text(
        f"lab artifact\nrun_id={run_id}\npid={pid}\nfunction={ctx.get('function', '?')}\n",
        encoding="utf-8",
    )
    log.info(f"artefacto de laboratorio escrito en {path}")
    return True


@register("heartbeat")
def _heartbeat(ctx: dict) -> bool:
    """Emite algunos heartbeats con retardo (útil para pruebas de detección
    de procesos de larga duración o de actividad periódica)."""
    n = int(ctx.get("heartbeat_count", 3))
    for i in range(n):
        log.info(f"heartbeat {i + 1}/{n}")
        time.sleep(0.4 + random.random() * 0.3)
    return True
