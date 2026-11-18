"""Punto de entrada del laboratorio (demo en vivo o evolución genética).

Ambos modos imprimen un único documento JSON válido en stdout.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from typing import Any

from src.genes import decode, random_vector
from src.parent import ParentAgent


def run_demo(seconds: float = 18.0, children: int = 4, pressure: bool = True) -> dict[str, Any]:
    """
    Lanza un padre y N hijos reales (multiprocessing).

    Los hijos envían heartbeats; el padre responde ACK y aplica watchdog.
    Si pressure=True, el laboratorio termina procesos al azar para forzar
    recuperación adaptativa.

    Devuelve un dict listo para serializar como un único JSON válido.
    """
    rng = random.Random(7)
    genomes = [decode(random_vector(rng)) for _ in range(children)]
    parent = ParentAgent(genomes)

    events: list[dict[str, Any]] = []
    events.append(
        {
            "event": "start",
            "children": children,
            "pressure": pressure,
            "seconds": seconds,
            "ts": time.time(),
        }
    )

    end = time.time() + seconds
    last_print = 0.0
    try:
        while time.time() < end:
            parent.poll(0.08)
            now = time.time()
            if pressure and rng.random() < 0.04:
                alive = [c for c in parent.state.children.values() if c.process.is_alive()]
                if alive:
                    victim = rng.choice(alive)
                    victim.process.terminate()
                    events.append(
                        {
                            "event": "lab_pressure",
                            "child": victim.child_id,
                            "ts": now,
                        }
                    )
            if now - last_print > 2.0:
                last_print = now
                events.append(
                    {
                        "event": "snapshot",
                        "ts": now,
                        "children": parent.snapshot(),
                        "resources": parent.resource_summary(),
                    }
                )
    finally:
        summary = parent.resource_summary()
        final_children = parent.snapshot()
        parent.shutdown()
        events.append(
            {
                "event": "shutdown",
                "ts": time.time(),
                "resources": summary,
            }
        )

    return {
        "mode": "demo",
        "config": {
            "seconds": seconds,
            "children": children,
            "pressure": pressure,
        },
        "events": events,
        "final_snapshot": final_children,
        "resources": summary,
    }


def run_evolve(generations: int, population: int) -> dict[str, Any]:
    """Ejecuta el AG y devuelve un dict listo para JSON único."""
    from src.evolution import run_evolution

    result = run_evolution(generations=generations, population=population)
    return {
        "mode": "evolve",
        "config": {
            "generations": generations,
            "population": population,
        },
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="GA — laboratorio académico")
    parser.add_argument("--demo", action="store_true", help="Padre e hijos reales con heartbeat")
    parser.add_argument("--evolve", action="store_true", help="Evolución genética sobre el simulador")
    parser.add_argument("--seconds", type=float, default=18.0)
    parser.add_argument("--children", type=int, default=4)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--no-pressure", action="store_true")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Imprimir JSON indentado (por defecto es compacto en una línea)",
    )
    args = parser.parse_args()

    if args.evolve:
        output = run_evolve(generations=args.generations, population=args.population)
    elif args.demo:
        output = run_demo(
            seconds=args.seconds,
            children=args.children,
            pressure=not args.no_pressure,
        )
    else:
        parser.print_help()
        print("\nUsa --demo o --evolve.", file=__import__("sys").stderr)
        raise SystemExit(2)

    if args.pretty:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
