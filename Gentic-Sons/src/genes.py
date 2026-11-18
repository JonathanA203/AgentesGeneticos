"""
Punto 1 — Representación genética del proceso hijo.

Cada hijo es un individuo del algoritmo genético: una lista de 10 genes.
Los genes NO son técnicas de persistencia del sistema operativo; son
parámetros de comportamiento del watchdog (comunicación, recuperación,
recursos) en un laboratorio controlado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

# Orden fijo: el cromosoma es una lista alineada a estas claves.
GENE_ORDER = (
    "heartbeat_interval",
    "watchdog_timeout",
    "parent_check_interval",
    "recovery_attempts",
    "backoff",
    "jitter",
    "cpu_budget",
    "memory_mb",
    "recovery_strategy",
    "promotion_eligible",
)

# (mínimo, máximo) por gen. Enteros se redondean al decodificar.
GENE_BOUNDS: dict[str, tuple[float, float]] = {
    "heartbeat_interval": (0.40, 3.00),     # s entre heartbeats al padre
    "watchdog_timeout": (1.00, 8.00),       # s sin heartbeat → hijo ausente
    "parent_check_interval": (0.50, 4.00),  # s entre chequeos del padre
    "recovery_attempts": (1.00, 6.00),      # reintentos de recuperación
    "backoff": (0.10, 2.00),                # s de espera entre reintentos
    "jitter": (0.00, 0.25),                 # variación aleatoria del ritmo
    "cpu_budget": (0.05, 0.80),             # carga simulada (menor = mejor)
    "memory_mb": (8.00, 48.00),             # memoria simulada
    "recovery_strategy": (0.00, 2.99),      # 0 restart, 1 wait, 2 report
    "promotion_eligible": (0.00, 1.99),     # 0 no, 1 sí puede ser padre
}

RECOVERY_STRATEGIES = {
    0: "restart_self",     # el padre relanza al hijo con el mismo genoma
    1: "wait_parent",      # espera instrucciones del padre
    2: "report_and_idle",  # reporta fallo y se queda inactivo
}

GENE_DOCS: dict[str, str] = {
    "heartbeat_interval": (
        "Cada cuántos segundos el hijo avisa al padre que sigue vivo. "
        "Muy corto gasta recursos; muy largo retrasa la detección de fallos."
    ),
    "watchdog_timeout": (
        "Tiempo máximo que el padre espera un heartbeat antes de declarar "
        "al hijo ausente. Debe ser claramente mayor que heartbeat_interval."
    ),
    "parent_check_interval": (
        "Cada cuántos segundos el hijo comprueba si el padre sigue vivo. "
        "Sirve para la promoción controlada (un hijo puede asumir el rol)."
    ),
    "recovery_attempts": (
        "Cuántas veces se intenta recuperar al hijo tras una terminación "
        "simulada en el laboratorio."
    ),
    "backoff": (
        "Pausa entre reintentos de recuperación. Evita ráfagas de relanzamiento."
    ),
    "jitter": (
        "Aleatoriedad (0–25 %) sobre el intervalo de heartbeat para que "
        "varios hijos no pulsen exactamente al mismo tiempo."
    ),
    "cpu_budget": (
        "Presupuesto de CPU simulado. Un valor alto reduce la fitness "
        "(menos eficiente)."
    ),
    "memory_mb": (
        "Memoria simulada del hijo. También penaliza la eficiencia."
    ),
    "recovery_strategy": (
        "0 = relanzar, 1 = esperar al padre, 2 = reportar y quedar inactivo."
    ),
    "promotion_eligible": (
        "Si vale 1, este hijo puede convertirse en el nuevo padre si el "
        "original desaparece (solo en laboratorio)."
    ),
}


@dataclass(frozen=True)
class ChildGenome:
    heartbeat_interval: float
    watchdog_timeout: float
    parent_check_interval: float
    recovery_attempts: int
    backoff: float
    jitter: float
    cpu_budget: float
    memory_mb: float
    recovery_strategy: int
    promotion_eligible: int

    @property
    def strategy_name(self) -> str:
        return RECOVERY_STRATEGIES.get(self.recovery_strategy, "restart_self")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["strategy_name"] = self.strategy_name
        return data

    def as_vector(self) -> list[float]:
        return [float(getattr(self, name)) for name in GENE_ORDER]


def _clamp(name: str, value: float) -> float:
    lo, hi = GENE_BOUNDS[name]
    return max(lo, min(hi, float(value)))


def decode(individual: Sequence[float]) -> ChildGenome:
    """Convierte un cromosoma (lista de floats) en un genoma válido (con reparación)."""
    if len(individual) < len(GENE_ORDER):
        raise ValueError(f"Se esperaban {len(GENE_ORDER)} genes, llegaron {len(individual)}")

    raw = {name: _clamp(name, individual[i]) for i, name in enumerate(GENE_ORDER)}

    heartbeat = raw["heartbeat_interval"]
    # Reparación: el watchdog debe cubrir al menos 2 ciclos + jitter.
    min_watchdog = heartbeat * (2.0 + raw["jitter"]) + 0.25
    watchdog = max(raw["watchdog_timeout"], min_watchdog)
    watchdog = min(watchdog, GENE_BOUNDS["watchdog_timeout"][1])

    return ChildGenome(
        heartbeat_interval=round(heartbeat, 3),
        watchdog_timeout=round(watchdog, 3),
        parent_check_interval=round(raw["parent_check_interval"], 3),
        recovery_attempts=int(round(raw["recovery_attempts"])),
        backoff=round(raw["backoff"], 3),
        jitter=round(raw["jitter"], 3),
        cpu_budget=round(raw["cpu_budget"], 3),
        memory_mb=round(raw["memory_mb"], 2),
        recovery_strategy=int(raw["recovery_strategy"]) % 3,
        promotion_eligible=0 if raw["promotion_eligible"] < 1.0 else 1,
    )


def random_vector(rng) -> list[float]:
    """Genera un cromosoma aleatorio dentro de los bounds."""
    vec = []
    for name in GENE_ORDER:
        lo, hi = GENE_BOUNDS[name]
        vec.append(rng.uniform(lo, hi))
    return vec
