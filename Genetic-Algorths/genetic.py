"""Algoritmo genético con DEAP (reemplazo de PyGAD).

Interfaz pública:

    evolve_best_genome(fn: MathFunction, base_genome: list, seed: int | None = None) -> dict

Devuelve:
    genome       mejor genoma encontrado en toda la corrida
    value        valor de la función en ese genoma
    history      lista por generación: {"gen", "best", "mean", "std", "evals"} (gen 0 = población inicial)
    elapsed_s    segundos que tardó la evolución

Elitismo: los `elite_size` mejores individuos de cada generación pasan intactos a la siguiente, y un
Hall of Fame guarda el mejor de toda la corrida. Así el resultado nunca es peor que la mejor
población anterior (sin elitismo la cruza y la mutación podían perder al mejor individuo).
"""
from __future__ import annotations

import random
import time
from typing import Sequence

import numpy as np
from deap import base as deap_base
from deap import creator, tools

from functions import MathFunction
from log_config import get_logger

log = get_logger("ga")

# Parámetros por defecto
GA_PARAMS = dict(
    num_generations=100,
    sol_per_pop=40,
    mutation_percent_genes=20,
    cxpb=0.7,
    mutpb=0.2,
    elite_size=2,  # individuos que pasan intactos a la siguiente generación
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


def _evaluate(individual: Sequence[float], fn: MathFunction):
    """Devuelve una tupla de fitness (DEAP exige iterable)."""
    return (fn.func(individual),)


def evolve_best_genome(
    fn: MathFunction,
    base_genome: list,
    seed: int | None = None,
) -> dict:
    """Evoluciona (selección, cruza, mutación y elitismo) una población sembrada desde
    `base_genome` y devuelve el mejor individuo. Es bloqueante (CPU)."""
    _ensure_creators()
    t_start = time.perf_counter()
    low, high = fn.bounds
    dim = fn.dimensions
    pop_size = GA_PARAMS["sol_per_pop"]
    ngen = GA_PARAMS["num_generations"]
    cxpb = GA_PARAMS["cxpb"]
    mutpb = GA_PARAMS["mutpb"]
    elite_size = min(GA_PARAMS["elite_size"], pop_size - 1)
    indpb = max(0.01, GA_PARAMS["mutation_percent_genes"] / 100.0)

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    toolbox = deap_base.Toolbox()
    fit_cls = creator.FitnessMax if fn.goal == "max" else creator.FitnessMin

    toolbox.register("evaluate", _evaluate, fn=fn)
    toolbox.register("mate", tools.cxBlend, alpha=0.4)
    toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=SEED_SPREAD * (high - low), indpb=indpb)
    toolbox.register("select", tools.selTournament, tournsize=3)

    # Población inicial sembrada alrededor del genoma base (el genoma base original también compite)
    population = []
    base_list = list(base_genome)
    for i in range(pop_size):
        if i == 0:
            ind = creator.Individual(base_list)
        else:
            noise = np_rng.normal(0, SEED_SPREAD * (high - low), dim)
            ind = creator.Individual(np.clip(np.asarray(base_list) + noise, low, high).tolist())
        ind.fitness = fit_cls()
        population.append(ind)

    evals = 0
    for ind in population:
        ind.fitness.values = toolbox.evaluate(ind)
        evals += 1

    hof = tools.HallOfFame(1)  # mejor individuo de toda la corrida
    hof.update(population)
    history = []

    def record(gen: int) -> None:
        vals = np.array([ind.fitness.values[0] for ind in population])
        best = float(vals.max() if fn.goal == "max" else vals.min())
        history.append({"gen": gen, "best": best, "mean": float(vals.mean()),
                        "std": float(vals.std()), "evals": evals})
        log.debug(f"{fn.name} gen {gen:3d}: mejor={best:.6g} media={vals.mean():.6g} "
                  f"std={vals.std():.3g} evaluaciones={evals}")

    record(0)

    for gen in range(1, ngen + 1):
        # Élite: los mejores pasan sin cambios a la siguiente generación
        elites = list(map(toolbox.clone, tools.selBest(population, elite_size)))

        offspring = toolbox.select(population, pop_size - elite_size)
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
        for ind in invalid:
            ind.fitness.values = toolbox.evaluate(ind)
        evals += len(invalid)

        population[:] = offspring + elites
        hof.update(population)
        record(gen)

    best = hof[0]
    return {
        "genome": [float(g) for g in best],
        "value": float(fn.func(best)),
        "history": history,
        "elapsed_s": time.perf_counter() - t_start,
    }
