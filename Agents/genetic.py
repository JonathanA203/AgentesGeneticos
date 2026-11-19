import numpy as np
import pygad

from functions import MathFunction

# Parámetros por defecto del algoritmo genético
GA_PARAMS = dict(
    num_generations=100,
    num_parents_mating=10,
    sol_per_pop=40,
    mutation_percent_genes=20,
)

# Dispersión (fracción del rango) de la población inicial alrededor del genoma base
SEED_SPREAD = 0.1


def evolve_best_genome(fn: MathFunction, base_genome: list, seed: int | None = None) -> dict:
    """Evoluciona (selección, cruza y mutación) una población sembrada desde
    `base_genome` y devuelve el mejor individuo. Es bloqueante (CPU)."""
    sign = 1 if fn.goal == "max" else -1  # PyGAD siempre maximiza
    low, high = fn.bounds

    def fitness(ga_instance, solution, solution_idx):
        return sign * fn.func(solution)

    # Población inicial: el genoma base más ruido gaussiano, dentro de los límites
    rng = np.random.default_rng(seed)
    population = np.clip(
        np.asarray(base_genome) + rng.normal(0, SEED_SPREAD * (high - low), (GA_PARAMS["sol_per_pop"], fn.dimensions)),
        low,
        high,
    )
    population[0] = base_genome  # el genoma base original también compite

    ga = pygad.GA(
        fitness_func=fitness,
        num_genes=fn.dimensions,
        initial_population=population,
        gene_space={"low": low, "high": high},
        random_seed=seed,
        suppress_warnings=True,
        **{k: v for k, v in GA_PARAMS.items() if k != "sol_per_pop"},
    )
    ga.run()
    solution, fitness_value, _ = ga.best_solution()
    return {
        "genome": [float(g) for g in solution],
        "value": float(sign * fitness_value),
    }
