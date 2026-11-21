"""Algoritmo genético con DEAP (reemplazo de PyGAD).

Mantiene la misma interfaz pública:

    evolve_best_genome(fn: MathFunction, base_genome: list, seed: int | None = None) -> dict

Devuelve {"genome": [...], "value": float} para no romper SpawnerAgent ni el resto
de la arquitectura.
"""
from __future__ import annotations

import random
from typing import Sequence

import numpy as np
from deap import base as deap_base
from deap import creator, tools

from functions import MathFunction

# Parámetros por defecto (equivalentes a los que había con PyGAD)
GA_PARAMS = dict(
    num_generations=100,
    num_parents_mating=10,
    sol_per_pop=40,
    mutation_percent_genes=20,
    cxpb=0.7,
    mutpb=0.2,
)

# Dispersión (fracción del rango) de la población inicial alrededor del genoma base
SEED_SPREAD = 0.1


def _ensure_creators() -> None:
    """Crea FitnessMax/FitnessMin e Individual solo una vez (DEAP es global)."""
    if not hasattr(creator, "FitnessMax"):
        creator.create("FitnessMax", deap_base.Fitness, weights=(1.0,))
    if not hasattr(creator, "FitnessMin"):
        creator.create("FitnessMin", deap_base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMax)


def evolve_best_genome(
    fn: MathFunction,
    base_genome: list,
    seed: int | None = None,
) -> dict:
    """Evoluciona (selección, cruza y mutación) una población sembrada desde
    `base_genome` y devuelve el mejor individuo. Es bloqueante (CPU).

    Interfaz idéntica a la versión anterior con PyGAD.
    """
    _ensure_creators()
    low, high = fn.bounds
    dim = fn.dimensions
    pop_size = GA_PARAMS["sol_per_pop"]
    ngen = GA_PARAMS["num_generations"]
    cxpb = GA_PARAMS["cxpb"]
    mutpb = GA_PARAMS["mutpb"]
    indpb = max(0.01, GA_PARAMS["mutation_percent_genes"] / 100.0)

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    toolbox = deap_base.Toolbox()

    # Elegir clase de fitness según el objetivo
    if fn.goal == "max":
        fit_cls = creator.FitnessMax
    else:
        fit_cls = creator.FitnessMin

    def init_individual():
        genes = np_rng.uniform(low, high, dim).tolist()
        ind = creator.Individual(genes)
        ind.fitness = fit_cls()
        return ind

    toolbox.register("individual", init_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", _evaluate, fn=fn)
    toolbox.register("mate", tools.cxBlend, alpha=0.4)
    toolbox.register(
        "mutate",
        tools.mutGaussian,
        mu=0,
        sigma=SEED_SPREAD * (high - low),
        indpb=indpb,
    )
    toolbox.register("select", tools.selTournament, tournsize=3)

    # Población inicial sembrada alrededor del genoma base
    population = []
    base_list = list(base_genome)
    for i in range(pop_size):
        if i == 0:
            ind = creator.Individual(base_list)
        else:
            noise = np_rng.normal(0, SEED_SPREAD * (high - low), dim)
            genes = np.clip(np.asarray(base_list) + noise, low, high).tolist()
            ind = creator.Individual(genes)
        ind.fitness = fit_cls()
        population.append(ind)

    # Evaluar población inicial
    fitnesses = list(map(toolbox.evaluate, population))
    for ind, fit in zip(population, fitnesses):
        ind.fitness.values = fit

    # Bucle generacional
    for gen in range(ngen):
        offspring = toolbox.select(population, len(population))
        offspring = list(map(toolbox.clone, offspring))

        for i in range(1, len(offspring), 2):
            if rng.random() < cxpb:
                offspring[i - 1], offspring[i] = toolbox.mate(offspring[i - 1], offspring[i])
                del offspring[i - 1].fitness.values
                del offspring[i].fitness.values

        for i in range(len(offspring)):
            if rng.random() < mutpb:
                offspring[i], = toolbox.mutate(offspring[i])
                del offspring[i].fitness.values
            for j in range(dim):
                offspring[i][j] = float(np.clip(offspring[i][j], low, high))

        invalid = [ind for ind in offspring if not ind.fitness.valid]
        fitnesses = list(map(toolbox.evaluate, invalid))
        for ind, fit in zip(invalid, fitnesses):
            ind.fitness.values = fit

        population[:] = offspring

    # Mejor individuo según el objetivo
    if fn.goal == "max":
        best = tools.selBest(population, 1)[0]
    else:
        # weights=(-1,): el "mejor" fitness es el menos negativo = valor de función más bajo
        best = tools.selBest(population, 1)[0]

    value = float(fn.func(best))
    return {
        "genome": [float(g) for g in best],
        "value": value,
    }


def _evaluate(individual: Sequence[float], fn: MathFunction):
    """Devuelve una tupla de fitness (DEAP exige iterable)."""
    return (fn.func(individual),)
