"""Punto de entrada del proceso hijo. Lo lanza el SpawnerAgent; no se ejecuta a mano.

Cada hijo es un proceso del sistema operativo independiente: si el EDR (o cualquier otra cosa)
lo termina, el monitor y el resto del sistema siguen vivos.
"""
import argparse
import asyncio
import json
import sys

from config import PASSWORD
from agents.optimizer_agent import OptimizerAgent


async def main(args) -> int:
    agent = OptimizerAgent(args.jid, PASSWORD)
    agent.function_name = args.function
    agent.genome = json.loads(args.genome)
    agent.monitor_jid = args.monitor_jid
    agent.run_id = args.run_id
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
    sys.exit(asyncio.run(main(ap.parse_args())))
