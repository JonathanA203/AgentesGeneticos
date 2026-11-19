import asyncio
from spade.behaviour import PeriodicBehaviour

from config import METRICS_INTERVAL, METRICS_CSV_PATH, DOCKER_CONTAINER
from monitoring.collectors import SystemCollector, ProcessCollector, DockerCollector, AgentStateCollector
from monitoring.recorder import CsvRecorder


class ResourceMonitorBehaviour(PeriodicBehaviour):
    """Función de monitoreo de recursos del Monitor: muestrea periódicamente
    todos los colectores registrados y escribe una fila por muestra en el CSV.

    Corre en paralelo al FSM. Para medir algo nuevo, agregar un colector a
    `self.collectors`. (Futuro: evaluar umbrales sobre `sample` y alertar.)"""

    def __init__(self):
        super().__init__(period=METRICS_INTERVAL)
        self.collectors = []
        self.recorder = None

    async def on_start(self):
        self.recorder = CsvRecorder(METRICS_CSV_PATH)
        self.collectors = [
            AgentStateCollector(self.agent),
            SystemCollector(),
            ProcessCollector(),
            DockerCollector(DOCKER_CONTAINER),
        ]
        # Esperar la primera lectura de Docker (tarda ~2 s) para no dejar celdas vacías al inicio
        for _ in range(20):
            if self.collectors[-1].collect()["docker_cpu_pct"] is not None:
                break
            await asyncio.sleep(0.25)
        self.agent.recorder = self.recorder  # el FSM lo usa para imprimir el resumen final
        self.agent.metrics_ready.set()

    async def run(self):
        sample = {}
        for collector in self.collectors:
            sample.update(collector.collect())
        self.recorder.write(sample)

    async def on_end(self):
        for collector in self.collectors:
            collector.close()
        self.recorder.close()
