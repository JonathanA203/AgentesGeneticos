"""Algoritmo genético sobre el simulador de episodios.

Usa DEAP para la evolución (selección por torneo, cruce de dos puntos,
mutación gaussiana acotada a los bounds de cada gen, elitismo).
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
from deap import base, creator, tools

from src.fitness import FitnessBreakdown
from src.genes import GENE_BOUNDS, GENE_ORDER, decode, random_vector
from src.simulator import simulate_episode


def _evaluate_vector(individual: list[float], seed: int = 0) -> FitnessBreakdown:
    genome = decode(individual)
    return simulate_episode(genome, seed=seed + int(abs(sum(individual)) * 10) % 10000)


def _pack_result(
    history: list[dict[str, Any]],
    best_vector: list[float],
    best_genome,
    best_fit: FitnessBreakdown,
    engine: str,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "history": history,
        "best_vector": best_vector,
        "best_genome": best_genome.to_dict(),
        "best_fitness": best_fit.total,
        "best_breakdown": {
            "survival": best_fit.survival,
            "recovery": best_fit.recovery,
            "heartbeat": best_fit.heartbeat,
            "efficiency": best_fit.efficiency,
            "sync": best_fit.sync,
            "penalty": best_fit.penalty,
        },
    }


def _run_deap(
    *,
    generations: int,
    population: int,
    cxpb: float,
    mutpb: float,
    seed: int,
) -> dict[str, Any]:
    """Ejecuta el AG con DEAP: torneo, two-point crossover, mutación gaussiana acotada, elitismo."""
    random.seed(seed)
    np.random.seed(seed)

    # Evitar redefinición de clases si se llama varias veces en el mismo proceso
    if hasattr(creator, "FitnessMax"):
        del creator.FitnessMax
    if hasattr(creator, "Individual"):
        del creator.Individual

    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMax)

    toolbox = base.Toolbox()

    def init_individual() -> Any:
        return creator.Individual(random_vector(random))

    toolbox.register("individual", init_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    # Cache por individuo (vector redondeado) para no re-evaluar innecesariamente
    eval_cache: dict[tuple[float, ...], float] = {}

    def evaluate(individual: list[float]) -> tuple[float]:
        key = tuple(round(v, 6) for v in individual)
        if key in eval_cache:
            return (eval_cache[key],)
        result = _evaluate_vector(list(individual), seed=seed)
        fitness = float(result.total)
        eval_cache[key] = fitness
        return (fitness,)

    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("select", tools.selTournament, tournsize=3)

    def mut_bounded_gaussian(
        individual: list[float],
        mu: float = 0.0,
        sigma: float = 0.35,
        indpb: float = 0.2,
    ):
        """Mutación gaussiana con clamp a los bounds de cada gen."""
        for i, name in enumerate(GENE_ORDER):
            if random.random() < indpb:
                lo, hi = GENE_BOUNDS[name]
                individual[i] += random.gauss(mu, sigma)
                individual[i] = max(lo, min(hi, individual[i]))
        return (individual,)

    toolbox.register("mutate", mut_bounded_gaussian, mu=0.0, sigma=0.35, indpb=mutpb)

    # Población inicial
    pop = toolbox.population(n=population)

    # Evaluar población inicial
    fitnesses = list(map(toolbox.evaluate, pop))
    for ind, fit in zip(pop, fitnesses):
        ind.fitness.values = fit

    history: list[dict[str, Any]] = []
    hall_of_fame = tools.HallOfFame(2)  # elitismo de los 2 mejores

    def record_stats(generation: int, population: list) -> None:
        fits = [ind.fitness.values[0] for ind in population]
        history.append(
            {
                "generation": generation,
                "best": round(float(np.max(fits)), 4),
                "avg": round(float(np.mean(fits)), 4),
                "worst": round(float(np.min(fits)), 4),
            }
        )

    record_stats(0, pop)
    hall_of_fame.update(pop)

    # Bucle generacional
    for gen in range(1, generations + 1):
        # Selección
        offspring = toolbox.select(pop, len(pop))
        offspring = list(map(toolbox.clone, offspring))

        # Cruce de dos puntos
        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < cxpb:
                toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values

        # Mutación
        for mutant in offspring:
            if random.random() < mutpb:
                toolbox.mutate(mutant)
                del mutant.fitness.values

        # Evaluar solo los inválidos
        invalid = [ind for ind in offspring if not ind.fitness.valid]
        fitnesses = list(map(toolbox.evaluate, invalid))
        for ind, fit in zip(invalid, fitnesses):
            ind.fitness.values = fit

        # Elitismo: asegurar que los mejores de HallOfFame estén en la nueva población
        for i, elite in enumerate(hall_of_fame):
            if i < len(offspring):
                offspring[i] = toolbox.clone(elite)

        hall_of_fame.update(offspring)
        pop[:] = offspring

        record_stats(gen, pop)

    # Mejor individuo final
    best_ind = tools.selBest(pop, 1)[0]
    best_vector = [float(x) for x in best_ind]
    best_genome = decode(best_vector)
    best_fit = simulate_episode(best_genome, seed=seed)

    return _pack_result(history, best_vector, best_genome, best_fit, engine="deap")


def run_evolution(
    *,
    generations: int = 12,
    population: int = 24,
    cxpb: float = 0.55,
    mutpb: float = 0.30,
    seed: int = 42,
) -> dict[str, Any]:
    return _run_deap(
        generations=generations,
        population=population,
        cxpb=cxpb,
        mutpb=mutpb,
        seed=seed,
    )
