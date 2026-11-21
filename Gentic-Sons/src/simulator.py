"""Simulador discreto para evaluar un genoma sin lanzar procesos reales.

Usado por el algoritmo genético: un episodio de laboratorio con presión
aleatoria (terminaciones simuladas de hijos). El modelo coincide con el
comportamiento de padre/hijo reales.
"""

from __future__ import annotations

import random

from src.fitness import EpisodeStats, FitnessBreakdown, evaluate_stats
from src.genes import ChildGenome


def simulate_episode(
    genome: ChildGenome,
    *,
    duration: float = 30.0,
    dt: float = 0.1,
    pressure_rate: float = 0.08,
    seed: int = 0,
) -> FitnessBreakdown:
    """
    Simula un episodio de duración `duration` segundos.

    - El hijo envía heartbeats según su genoma.
    - Con probabilidad pressure_rate * dt ocurre una terminación simulada.
    - Se intenta recuperar según recovery_strategy / recovery_attempts.
    """
    rng = random.Random(seed)
    t = 0.0
    alive = True
    alive_time = 0.0
    last_beat = 0.0
    last_parent_check = 0.0
    recovering_until = -1.0
    recoveries_left = genome.recovery_attempts
    recoveries_attempted = 0
    recoveries_ok = 0
    pressure_events = 0
    missed_watchdogs = 0
    heartbeats_sent = 0
    heartbeats_acked = 0
    parent_checks = 0
    parent_seen_alive = 0
    parent_alive = True

    expected = max(1, int(duration / max(0.2, genome.heartbeat_interval)))

    while t < duration:
        if alive:
            alive_time += dt
            interval = genome.heartbeat_interval * (1.0 + genome.jitter * (rng.random() * 2 - 1))
            interval = max(0.15, interval)
            if t - last_beat >= interval:
                heartbeats_sent += 1
                last_beat = t
                last_ack = t  # noqa: F841 — el padre ACK de inmediato en simulación
                heartbeats_acked += 1

            if t - last_parent_check >= genome.parent_check_interval:
                parent_checks += 1
                last_parent_check = t
                if parent_alive:
                    parent_seen_alive += 1

            if rng.random() < pressure_rate * dt:
                pressure_events += 1
                alive = False
                missed_watchdogs += 1
                recovering_until = t + genome.backoff
        else:
            if t >= recovering_until and recoveries_left > 0:
                recoveries_attempted += 1
                recoveries_left -= 1
                if genome.recovery_strategy == 2:
                    # report_and_idle: no se recupera
                    recovering_until = duration + 1
                elif genome.recovery_strategy == 1:
                    # wait_parent: recuperación probabilística
                    recovering_until = t + genome.backoff * 2
                    if rng.random() < 0.65:
                        alive = True
                        recoveries_ok += 1
                        last_beat = t
                else:
                    # restart_self
                    alive = True
                    recoveries_ok += 1
                    last_beat = t

        t += dt

    stats = EpisodeStats(
        duration=duration,
        alive_time=round(alive_time, 3),
        expected_heartbeats=expected,
        heartbeats_sent=heartbeats_sent,
        heartbeats_acked=heartbeats_acked,
        missed_watchdogs=missed_watchdogs,
        pressure_events=pressure_events,
        recoveries_attempted=recoveries_attempted,
        recoveries_ok=recoveries_ok,
        parent_checks=parent_checks,
        parent_seen_alive=parent_seen_alive,
    )
    return evaluate_stats(genome, stats)
