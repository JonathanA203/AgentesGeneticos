import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from config import XMPP_SERVER, SPAWNER_TIMEOUT, DEFAULT_CHILD_BEHAVIORS
from functions import FUNCTIONS
from genetic import evolve_best_genome

ROOT = Path(__file__).resolve().parent.parent
# Carpeta de logs de los procesos hijo (se puede cambiar con AGENTES_CHILD_LOG_DIR)
LOG_DIR = Path(os.environ.get("AGENTES_CHILD_LOG_DIR", ROOT / "logs" / "hijos"))


# ==========================================
# AGENTE SPAWNER (One-shot: evoluciona el mejor individuo, lanza su proceso hijo y se apaga)
# ==========================================
class SpawnerAgent(Agent):
    class SpawnBehaviour(OneShotBehaviour):
        async def run(self):
            print(f"  [{self.agent.name}] Esperando orden del monitor...")
            msg = await self.receive(timeout=SPAWNER_TIMEOUT)

            if msg is None:
                print(f"  [{self.agent.name}] Sin orden, apagando.")
            else:
                orden = json.loads(msg.body)
                fn = FUNCTIONS[orden["function"]]
                print(f"  [{self.agent.name}] Orden recibida: '{fn.name}' ({fn.goal}), genoma base {[round(g, 3) for g in orden['genome']]}")

                # Selección, cruza y mutación (DEAP) en un hilo para no frenar el loop de SPADE
                mejor = await asyncio.to_thread(evolve_best_genome, fn, orden["genome"])
                print(f"  [{self.agent.name}] Mejor individuo: {[round(g, 4) for g in mejor['genome']]} (f={mejor['value']:.6f})")

                run_id = orden["run_id"]  # identifica este intento; el monitor ignora mensajes de otros
                hijo_jid = f"hijo_{fn.name}_{run_id.split('-', 1)[1]}@{XMPP_SERVER}"
                print(f"  [{self.agent.name}] Lanzando proceso hijo {hijo_jid}")

                # Comportamientos de laboratorio que el hijo ejecutará
                behaviors = orden.get("behaviors")
                if behaviors is None:
                    behaviors = list(DEFAULT_CHILD_BEHAVIORS)
                behaviors_str = ",".join(behaviors) if behaviors else ""

                # El hijo es un proceso independiente: reportará su PID al monitor por XMPP
                cmd = [
                    sys.executable, str(ROOT / "child_main.py"),
                    "--jid", hijo_jid,
                    "--function", fn.name,
                    "--genome", json.dumps(mejor["genome"]),
                    "--monitor-jid", orden["reply_to"],
                    "--run-id", run_id,
                    "--behaviors", behaviors_str,
                ]
                # La salida del hijo va a su propio log, porque un proceso sin consola no la mostraría
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                with open(LOG_DIR / f"{hijo_jid.split('@')[0]}.log", "w", encoding="utf-8") as log:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )

                # Avisar al monitor del PID ya mismo: así puede vigilarlo incluso si el hijo muere antes
                # de conectarse (el aviso propio del hijo llega más tarde, cuando su agente ya arrancó)
                try:
                    create_time = psutil.Process(proc.pid).create_time()
                except psutil.NoSuchProcess:
                    create_time = time.time()  # murió al instante: la hora de creación es la de ahora
                aviso = Message(to=orden["reply_to"])
                aviso.set_metadata("performative", "inform")
                aviso.body = json.dumps({
                    "type": "launched",
                    "run_id": run_id,
                    "pid": proc.pid,
                    "create_time": create_time,
                })
                await self.send(aviso)

            # One-shot: tras lanzar al hijo, el spawner se apaga
            await self.agent.stop()

    async def setup(self):
        self.add_behaviour(self.SpawnBehaviour())
