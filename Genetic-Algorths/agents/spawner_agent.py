import asyncio
import csv
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
from log_config import get_logger

log = get_logger("spawner")

ROOT = Path(__file__).resolve().parent.parent
# Carpeta de logs de los procesos hijo (se puede cambiar con AGENTES_CHILD_LOG_DIR)
LOG_DIR = Path(os.environ.get("AGENTES_CHILD_LOG_DIR", ROOT / "logs" / "hijos"))
# Historial por generación del algoritmo genético, un CSV por intento (se puede cambiar con AGENTES_GA_LOG_DIR)
GA_LOG_DIR = Path(os.environ.get("AGENTES_GA_LOG_DIR", ROOT / "logs" / "ga"))


def _resumen_ga(fn, mejor: dict) -> str:
    """Una línea con lo esencial de la evolución: coste, convergencia y última mejora."""
    hist = mejor["history"]
    mejora = lambda a, b: b > a if fn.goal == "max" else b < a
    ultima_mejora, ref = 0, hist[0]["best"]
    for h in hist[1:]:
        if mejora(ref, h["best"]):
            ref, ultima_mejora = h["best"], h["gen"]
    return (f"AG: {hist[-1]['gen']} generaciones, {hist[-1]['evals']} evaluaciones en {mejor['elapsed_s']:.2f} s | "
            f"mejor: {hist[0]['best']:.6g} (gen 0) -> {hist[-1]['best']:.6g} (gen {hist[-1]['gen']}), "
            f"última mejora en gen {ultima_mejora}")


def _guardar_historial(run_id: str, history: list) -> Path:
    GA_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = GA_LOG_DIR / f"{run_id}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["gen", "best", "mean", "std", "evals"])
        w.writeheader()
        w.writerows(history)
    return path


# ==========================================
# AGENTE SPAWNER (One-shot: evoluciona el mejor individuo, lanza su proceso hijo y se apaga)
# ==========================================
class SpawnerAgent(Agent):
    class SpawnBehaviour(OneShotBehaviour):
        async def run(self):
            log.info(f"[{self.agent.name}] Esperando orden del monitor...")
            msg = await self.receive(timeout=SPAWNER_TIMEOUT)

            if msg is None:
                log.warning(f"[{self.agent.name}] Sin orden, apagando.")
            else:
                orden = json.loads(msg.body)
                fn = FUNCTIONS[orden["function"]]
                log.info(f"[{self.agent.name}] Orden recibida: '{fn.name}' ({fn.goal}), genoma base {[round(g, 3) for g in orden['genome']]}")

                # Selección, cruza y mutación (DEAP) en un hilo para no frenar el loop de SPADE
                mejor = await asyncio.to_thread(evolve_best_genome, fn, orden["genome"])
                run_id = orden["run_id"]  # identifica este intento; el monitor ignora mensajes de otros
                log.info(f"[{self.agent.name}] {_resumen_ga(fn, mejor)}")
                log.info(f"[{self.agent.name}] Mejor individuo: {[round(g, 4) for g in mejor['genome']]} (f={mejor['value']:.6f}). "
                         f"Historial: {_guardar_historial(run_id, mejor['history'])}")
                hijo_jid = f"hijo_{fn.name}_{run_id.split('-', 1)[1]}@{XMPP_SERVER}"
                log.info(f"[{self.agent.name}] Lanzando proceso hijo {hijo_jid}")

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
                with open(LOG_DIR / f"{hijo_jid.split('@')[0]}.log", "w", encoding="utf-8") as fh:
                    proc = subprocess.Popen(
                        cmd,
                        cwd=ROOT,
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        env={**{k: v for k, v in os.environ.items() if k != "AGENTES_LOG_FILE"},
                             "PYTHONIOENCODING": "utf-8"},
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
