import json
import os

import psutil
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from functions import FUNCTIONS
from behaviors import run_behaviors


# ==========================================
# AGENTE HIJO (corre en su propio proceso: avisa su PID, valida su genoma y reporta)
# ==========================================
class OptimizerAgent(Agent):
    class ValidateBehaviour(OneShotBehaviour):
        async def _inform(self, body: dict):
            msg = Message(to=self.agent.monitor_jid)
            msg.set_metadata("performative", "inform")
            msg.body = json.dumps({"run_id": self.agent.run_id, **body})
            await self.send(msg)

        async def run(self):
            fn = FUNCTIONS[self.agent.function_name]
            genome = self.agent.genome
            behaviors = getattr(self.agent, "behaviors", []) or []

            # 1. Avisar al monitor de este proceso: el monitor lo vigilará por PID.
            #    create_time evita confundirlo con otro proceso si el sistema reutiliza el PID.
            proc = psutil.Process(os.getpid())
            await self._inform({"type": "started", "pid": proc.pid, "create_time": proc.create_time(),
                                "function": fn.name})
            print(f"  [{self.agent.name}] Proceso {proc.pid} iniciado. Validando genoma "
                  f"{[round(g, 4) for g in genome]} en '{fn.name}'...")

            # 2. Capa de comportamientos de laboratorio (extensible; ver behaviors.py).
            #    Pensada para que el equipo de la tesis añada simulaciones de supervivencia
            #    sin tocar el resto de la arquitectura. No incluye técnicas reales de APT/EDR.
            ctx = {
                "run_id": self.agent.run_id,
                "function": fn.name,
                "genome": genome,
                "pid": proc.pid,
            }
            if not run_behaviors(behaviors, ctx):
                print(f"  [{self.agent.name}] Un comportamiento abortó; no se envía resultado.")
                await self.agent.stop()
                return

            # 3. Validar y reportar el resultado
            valor = fn.func(genome)
            print(f"  [{self.agent.name}] f(genoma) = {valor:.6f} (óptimo conocido {fn.known_optimum}). "
                  f"Enviando resultado al monitor.")
            await self._inform({
                "type": "result",
                "function": fn.name,
                "goal": fn.goal,
                "best_solution": genome,
                "best_value": valor,
                "known_optimum": fn.known_optimum,
            })

            # 4. El hijo ha cumplido su propósito: el agente se detiene y el proceso termina
            await self.agent.stop()

    async def setup(self):
        self.add_behaviour(self.ValidateBehaviour())
