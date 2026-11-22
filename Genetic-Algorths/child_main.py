"""Punto de entrada del proceso hijo. Lo lanza el SpawnerAgent; no se ejecuta a mano.

Cada hijo es un proceso del sistema operativo independiente: si el EDR (o cualquier otra cosa)
lo termina, el monitor y el resto del sistema siguen vivos.

Comportamientos de laboratorio (behaviors.py) se pueden activar con --behaviors.
"""
import argparse
import asyncio
import json
import sys

from config import PASSWORD, DEFAULT_CHILD_BEHAVIORS
from agents.optimizer_agent import OptimizerAgent


async def main(args) -> int:
    agent = OptimizerAgent(args.jid, PASSWORD)
    agent.function_name = args.function
    agent.genome = json.loads(args.genome)
    agent.monitor_jid = args.monitor_jid
    agent.run_id = args.run_id
    # Lista de comportamientos de laboratorio (puede venir vacía)
    if args.behaviors:
        agent.behaviors = [b.strip() for b in args.behaviors.split(",") if b.strip()]
    else:
        agent.behaviors = list(DEFAULT_CHILD_BEHAVIORS)
    await agent.start(auto_register=True)

    # Vivir mientras el agente siga activo; al detenerse (tras reportar) el proceso termina
    while agent.is_alive():
        await asyncio.sleep(0.2)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jid", required=True)
    ap.add_argument("--function", required=True)
    ap.add_argument("--genome", required=True, help="genoma en JSON")
    ap.add_argument("--monitor-jid", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument(
        "--behaviors",
        default="",
        help="comportamientos de laboratorio separados por comas (ver behaviors.py)",
    )
    sys.exit(asyncio.run(main(ap.parse_args())))
