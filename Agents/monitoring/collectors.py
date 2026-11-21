import os
import re
import subprocess
import threading
import time

import psutil


class Collector:
    """Interfaz de un colector: devuelve {columna: valor} en cada muestra.
    Para medir algo nuevo basta con crear otro colector y registrarlo."""

    def collect(self) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SystemCollector(Collector):
    """Consumo general del sistema (CPU, RAM, swap)."""

    def __init__(self):
        psutil.cpu_percent(None)  # la primera lectura siempre es 0: se descarta

    def collect(self) -> dict:
        mem = psutil.virtual_memory()
        return {
            "sys_cpu_pct": psutil.cpu_percent(None),
            "sys_ram_pct": mem.percent,
            "sys_ram_used_mb": round(mem.used / 2**20, 1),
            "sys_ram_avail_mb": round(mem.available / 2**20, 1),
            "sys_swap_pct": psutil.swap_memory().percent,
        }


class ProcessCollector(Collector):
    """Consumo del proceso de Python del monitor (donde viven el Monitor y los Spawners) y de los
    procesos hijo de Python (un proceso por agente hijo)."""

    def __init__(self):
        self._proc = psutil.Process(os.getpid())
        self._proc.cpu_percent(None)

    def _children(self) -> tuple[int, float]:
        n, ram = 0, 0.0
        for c in self._proc.children(recursive=True):
            try:
                if "python" in c.name().lower():
                    n += 1
                    ram += c.memory_info().rss / 2**20
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # el hijo terminó justo mientras se medía
        return n, round(ram, 1)

    def collect(self) -> dict:
        with self._proc.oneshot():
            row = {
                "proc_cpu_pct": self._proc.cpu_percent(None),  # puede superar 100 con varios núcleos
                "proc_ram_mb": round(self._proc.memory_info().rss / 2**20, 1),
                "proc_threads": self._proc.num_threads(),
            }
        row["hijos_proc"], row["hijos_ram_mb"] = self._children()
        return row


_UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "kib": 2**10, "mib": 2**20, "gib": 2**30}


def _to_bytes(text: str) -> float:
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", text)
    return float(m.group(1)) * _UNITS[m.group(2).lower()] if m else 0.0


class DockerCollector(Collector):
    """Consumo del contenedor Prosody (CPU, RAM y tráfico de red = comunicaciones).

    `docker stats` tarda ~1-2 s, así que se consulta en un hilo de fondo y
    collect() devuelve la última lectura sin bloquear el muestreo."""

    COLUMNS = ("docker_cpu_pct", "docker_ram_mb", "docker_net_rx_kb", "docker_net_tx_kb")

    def __init__(self, container: str):
        self._container = container
        self._latest = {c: None for c in self.COLUMNS}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format",
                     "{{.CPUPerc}};{{.MemUsage}};{{.NetIO}}", self._container],
                    capture_output=True, text=True, timeout=15, creationflags=flags,
                ).stdout.strip()
                cpu, mem, net = out.split(";")
                rx, tx = net.split("/")
                self._latest = {
                    "docker_cpu_pct": float(cpu.strip("% ")),
                    "docker_ram_mb": round(_to_bytes(mem.split("/")[0]) / 2**20, 1),
                    "docker_net_rx_kb": round(_to_bytes(rx) / 1e3, 1),
                    "docker_net_tx_kb": round(_to_bytes(tx) / 1e3, 1),
                }
            except Exception:
                self._latest = {c: None for c in self.COLUMNS}  # Docker no disponible: celdas vacías
                self._stop.wait(5)
            self._stop.wait(0.5)

    def collect(self) -> dict:
        return dict(self._latest)

    def close(self) -> None:
        self._stop.set()


class AgentStateCollector(Collector):
    """Contexto del sistema multi-agente: fase del FSM y función en curso,
    para poder correlacionar el consumo con lo que hacen los agentes."""

    def __init__(self, agent):
        self._agent = agent

    def collect(self) -> dict:
        return {
            "fase": getattr(self._agent, "fase", ""),
            "funcion": getattr(self._agent, "funcion_en_curso", None) or "",
            "spawners_creados": getattr(self._agent, "spawners_creados", 0),
            "intento": getattr(self._agent, "intento_actual", 0),
            "hijo_pid": getattr(self._agent, "hijo_pid", None) or "",
        }
