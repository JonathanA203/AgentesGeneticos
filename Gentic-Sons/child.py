"""Proceso hijo: heartbeat, chequeo del padre y espera de órdenes."""

from __future__ import annotations

import random
import time
from multiprocessing import Queue
from multiprocessing.synchronize import Event as SyncEvent
from typing import Any

from src.genes import ChildGenome, decode
from src.ipc import Message

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def _self_resources() -> dict[str, float]:
    """Mide RAM (RSS en MB) y CPU del proceso hijo actual."""
    if psutil is None:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}
    try:
        proc = psutil.Process()
        # cpu_percent(None) usa el intervalo desde la última llamada
        cpu = float(proc.cpu_percent(interval=None))
        rss = float(proc.memory_info().rss) / (1024 * 1024)
        return {"rss_mb": round(rss, 3), "cpu_pct": round(cpu, 2)}
    except Exception:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}


def run_child(
    child_id: str,
    genome_vector: list[float],
    to_parent: Queue,
    from_parent: Queue,
    stop_event: SyncEvent,
) -> None:
    """
    Bucle principal del proceso hijo.

    - Envía heartbeats periódicos al padre (incluye consumo real de RAM/CPU).
    - Comprueba periódicamente si el padre sigue vivo.
    - Atiende órdenes (ack, promote, shutdown).
    """
    genome: ChildGenome = decode(genome_vector)
    rng = random.Random(hash(child_id) & 0xFFFFFFFF)
    last_parent_check = 0.0

    # Primera lectura de CPU para que las siguientes tengan intervalo válido.
    _self_resources()

    # Aviso de arranque.
    boot_res = _self_resources()
    to_parent.put(
        Message(
            kind="heartbeat",
            sender=child_id,
            target="parent",
            payload={
                "boot": True,
                "genome": genome.to_dict(),
                "cpu": genome.cpu_budget,
                "mem": genome.memory_mb,
                **boot_res,
            },
        )
    )

    while not stop_event.is_set():
        now = time.time()
        jitter = 1.0 + genome.jitter * (rng.random() * 2 - 1)
        sleep_for = max(0.12, genome.heartbeat_interval * jitter)

        res = _self_resources()
        to_parent.put(
            Message(
                kind="heartbeat",
                sender=child_id,
                target="parent",
                payload={
                    "cpu": genome.cpu_budget,       # presupuesto genético (simulado)
                    "mem": genome.memory_mb,        # presupuesto genético (simulado)
                    "rss_mb": res["rss_mb"],        # RAM real (RSS)
                    "cpu_pct": res["cpu_pct"],      # CPU real (%)
                },
            )
        )

        if now - last_parent_check >= genome.parent_check_interval:
            last_parent_check = now
            to_parent.put(
                Message(kind="parent_ping", sender=child_id, target="parent", payload={})
            )

        # Escucha mensajes del padre durante el intervalo de sleep.
        deadline = time.time() + sleep_for
        while time.time() < deadline and not stop_event.is_set():
            try:
                msg: Message | dict[str, Any] = from_parent.get(timeout=0.05)
            except Exception:
                continue
            if isinstance(msg, dict):
                kind = msg.get("kind")
            else:
                kind = msg.kind
            if kind == "shutdown":
                return
            if kind == "promote":
                to_parent.put(
                    Message(
                        kind="recovered",
                        sender=child_id,
                        target="parent",
                        payload={"promoted": True},
                    )
                )
