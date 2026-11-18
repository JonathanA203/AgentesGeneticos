"""
Punto 2 — Función de fitness orientada a persistencia adaptativa.

La fitness es un número en [0, 1] (maximizar). Premia:

  - sobrevivir bajo presión de laboratorio
  - recuperarse tras terminaciones simuladas
  - comunicar bien (heartbeats / ACK)
  - no gastar recursos en exceso

Penaliza genomas inválidos (watchdog demasiado corto respecto al heartbeat).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.genes import ChildGenome, GENE_BOUNDS

# Pesos de la función de fitness (deben sumar ~1.0 antes de la penalización).
WEIGHTS = {
    "survival": 0.40,
    "recovery": 0.25,
    "heartbeat": 0.20,
    "efficiency": 0.10,
    "sync": 0.05,
}


@dataclass
class EpisodeStats:
    """Métricas recolectadas durante un episodio de laboratorio."""

    duration: float
    alive_time: float
    expected_heartbeats: int
    heartbeats_sent: int
    heartbeats_acked: int
    missed_watchdogs: int
    pressure_events: int
    recoveries_attempted: int
    recoveries_ok: int
    parent_checks: int
    parent_seen_alive: int
    invalid_genome: bool = False


@dataclass
class FitnessBreakdown:
    """Desglose de la fitness para análisis e informes."""

    total: float
    survival: float
    recovery: float
    heartbeat: float
    efficiency: float
    sync: float
    penalty: float
    stats: dict

    def as_tuple(self) -> tuple[float, ...]:
        return (self.total,)


def _ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def evaluate_stats(genome: ChildGenome, stats: EpisodeStats) -> FitnessBreakdown:
    """
    Calcula la fitness a partir de un genoma y las estadísticas del episodio.

    Fórmula:
        fitness = 0.40·supervivencia
                + 0.25·recuperación
                + 0.20·heartbeat
                + 0.10·eficiencia
                + 0.05·sync
                − penalización
    """
    # 1) Supervivencia: fracción del tiempo que el hijo estuvo vivo.
    survival = _ratio(stats.alive_time, stats.duration)

    # 2) Recuperación: éxitos / intentos tras presión de laboratorio.
    recovery = _ratio(stats.recoveries_ok, max(1, stats.recoveries_attempted))
    if stats.pressure_events == 0 and stats.recoveries_attempted == 0:
        recovery = 1.0 if survival > 0.8 else 0.5

    # 3) Calidad de heartbeat: enviados vs esperados, y ACK del padre.
    heartbeat = _ratio(stats.heartbeats_sent, max(1, stats.expected_heartbeats))
    heartbeat *= _ratio(stats.heartbeats_acked, max(1, stats.heartbeats_sent))
    if stats.missed_watchdogs:
        heartbeat *= max(0.2, 1.0 - 0.15 * stats.missed_watchdogs)

    # 4) Eficiencia: menor CPU y memoria → mejor.
    cpu_span = GENE_BOUNDS["cpu_budget"][1] - GENE_BOUNDS["cpu_budget"][0]
    mem_span = GENE_BOUNDS["memory_mb"][1] - GENE_BOUNDS["memory_mb"][0]
    cpu_norm = (genome.cpu_budget - GENE_BOUNDS["cpu_budget"][0]) / cpu_span
    mem_norm = (genome.memory_mb - GENE_BOUNDS["memory_mb"][0]) / mem_span
    efficiency = 1.0 - (0.65 * cpu_norm + 0.35 * mem_norm)

    # 5) Sincronía con el padre.
    sync = _ratio(stats.parent_seen_alive, max(1, stats.parent_checks))

    # Penalización por genoma inválido (watchdog demasiado corto).
    penalty = 0.0
    min_watchdog = genome.heartbeat_interval * (2.0 + genome.jitter) + 0.25
    if genome.watchdog_timeout < min_watchdog or stats.invalid_genome:
        penalty = 0.35

    total = (
        WEIGHTS["survival"] * survival
        + WEIGHTS["recovery"] * recovery
        + WEIGHTS["heartbeat"] * heartbeat
        + WEIGHTS["efficiency"] * efficiency
        + WEIGHTS["sync"] * sync
        - penalty
    )
    total = max(0.0, min(1.0, total))

    return FitnessBreakdown(
        total=round(total, 4),
        survival=round(survival, 4),
        recovery=round(recovery, 4),
        heartbeat=round(heartbeat, 4),
        efficiency=round(efficiency, 4),
        sync=round(sync, 4),
        penalty=round(penalty, 4),
        stats=asdict(stats),
    )
