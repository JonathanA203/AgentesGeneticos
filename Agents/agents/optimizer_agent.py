import json
import os

import psutil
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from functions import FUNCTIONS


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

            # 1. Avisar al monitor de este proceso: el monitor lo vigilará por PID.
            #    create_time evita confundirlo con otro proceso si el sistema reutiliza el PID.
            proc = psutil.Process(os.getpid())
            await self._inform({"type": "started", "pid": proc.pid, "create_time": proc.create_time(),
                                "function": fn.name})
            print(f"  [{self.agent.name}] Proceso {proc.pid} iniciado. Validando genoma "
                  f"{[round(g, 4) for g in genome]} en '{fn.name}'...")

            # 2. Validar y reportar el resultado
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

            # 3. El hijo ha cumplido su propósito: el agente se detiene y el proceso termina
            await self.agent.stop()

    async def setup(self):
        self.add_behaviour(self.ValidateBehaviour())
