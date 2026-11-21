import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


@dataclass(frozen=True)
class MathFunction:
    """Función matemática a optimizar por un hijo."""
    name: str
    description: str
    func: Callable[[Sequence[float]], float]
    dimensions: int
    bounds: tuple  # (mínimo, máximo) de cada variable
    goal: str  # "min" o "max"
    known_optimum: float  # valor óptimo conocido, para validar el resultado


def sphere(x):
    return float(np.sum(np.square(x)))


def rastrigin(x):
    x = np.asarray(x)
    return float(10 * len(x) + np.sum(x**2 - 10 * np.cos(2 * math.pi * x)))


def peaks(x):
    # Máximo global en (0, 0) con valor 1
    return float(math.exp(-(x[0] ** 2 + x[1] ** 2)) * math.cos(x[0]) * math.cos(x[1]))


FUNCTIONS = {
    f.name: f
    for f in (
        MathFunction("sphere", "f(x) = sum(x_i^2)", sphere, 3, (-5.12, 5.12), "min", 0.0),
        MathFunction("rastrigin", "f(x) = 10n + sum(x_i^2 - 10cos(2*pi*x_i))", rastrigin, 2, (-5.12, 5.12), "min", 0.0),
        MathFunction("peaks", "f(x,y) = exp(-(x^2+y^2))cos(x)cos(y)", peaks, 2, (-3.0, 3.0), "max", 1.0),
    )
}


def random_genome(fn: MathFunction) -> list:
    """Genoma base aleatorio dentro de los límites de la función."""
    rng = np.random.default_rng()
    return [float(g) for g in rng.uniform(fn.bounds[0], fn.bounds[1], fn.dimensions)]
