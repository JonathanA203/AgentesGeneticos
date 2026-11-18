"""Proceso padre: crea hijos, acusa heartbeats y relanza si desaparecen."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from multiprocessing import Process, Queue, Event
from multiprocessing.synchronize import Event as SyncEvent
from typing import Any

from src.child import run_child
from src.genes import ChildGenome, decode
from src.ipc import Message

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def _pid_resources(pid: int | None) -> dict[str, float]:
    """Lee RSS/CPU de un PID desde el padre (verificación)."""
    if psutil is None or pid is None:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return {"rss_mb": 0.0, "cpu_pct": 0.0}
        cpu = float(proc.cpu_percent(interval=None))
        rss = float(proc.memory_info().rss) / (1024 * 1024)
        return {"rss_mb": round(rss, 3), "cpu_pct": round(cpu, 2)}
    except Exception:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}


@dataclass
class ChildRecord:
    child_id: str
    genome: ChildGenome
    process: Process
    inbox: Queue
    last_beat: float
    alive: bool = True
    recoveries_left: int = 0
    recoveries_ok: int = 0
    beats: int = 0
    # Recursos reportados por el hijo (última muestra)
    rss_mb: float = 0.0
    cpu_pct: float = 0.0
    # Peak de RAM observada durante la vida del hijo
    peak_rss_mb: float = 0.0


@dataclass
class ParentState:
    children: dict[str, ChildRecord] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)


class ParentAgent:
    """Agente padre: monitoreo, ACK y recuperación controlada de hijos."""

    def __init__(self, genomes: list[ChildGenome], stop_event: SyncEvent | None = None):
        self.stop_event = stop_event or Event()
        self.to_parent: Queue = Queue()
        self.state = ParentState()
        self._seq = 0
        for genome in genomes:
            self.spawn(genome)

    def spawn(self, genome: ChildGenome, child_id: str | None = None) -> ChildRecord:
        self._seq += 1
        cid = child_id or f"hijo-{self._seq}"
        inbox: Queue = Queue()
        proc = Process(
            target=run_child,
            args=(cid, genome.as_vector(), self.to_parent, inbox, self.stop_event),
            name=cid,
            daemon=True,
        )
        proc.start()
        rec = ChildRecord(
            child_id=cid,
            genome=genome,
            process=proc,
            inbox=inbox,
            last_beat=time.time(),
            recoveries_left=genome.recovery_attempts,
        )
        self.state.children[cid] = rec
        self._log("spawn", cid, {"pid": proc.pid})
        return rec

    def _log(self, kind: str, child_id: str, payload: dict[str, Any] | None = None) -> None:
        self.state.log.append(
            {"ts": time.time(), "kind": kind, "child": child_id, "payload": payload or {}}
        )
        if len(self.state.log) > 400:
            self.state.log = self.state.log[-300:]

    def poll(self, timeout: float = 0.05) -> None:
        """Procesa mensajes entrantes y aplica el watchdog."""
        try:
            msg = self.to_parent.get(timeout=timeout)
        except Exception:
            msg = None
        if msg is not None:
            self._handle(msg)
        self._watchdog()

    def _handle(self, msg: Message) -> None:
        rec = self.state.children.get(msg.sender)
        if rec is None:
            return
        if msg.kind == "heartbeat":
            rec.last_beat = time.time()
            rec.alive = True
            rec.beats += 1
            payload = msg.payload or {}
            # Recursos reales reportados por el hijo
            if "rss_mb" in payload:
                rec.rss_mb = float(payload["rss_mb"])
                rec.peak_rss_mb = max(rec.peak_rss_mb, rec.rss_mb)
            if "cpu_pct" in payload:
                rec.cpu_pct = float(payload["cpu_pct"])
            rec.inbox.put(Message(kind="ack", sender="parent", target=rec.child_id))
        elif msg.kind == "parent_ping":
            rec.inbox.put(Message(kind="parent_alive", sender="parent", target=rec.child_id))
        self._log(msg.kind, msg.sender, msg.payload)

    def _watchdog(self) -> None:
        now = time.time()
        for rec in list(self.state.children.values()):
            if not rec.alive:
                continue
            if now - rec.last_beat > rec.genome.watchdog_timeout:
                rec.alive = False
                self._log("child_down", rec.child_id, {"gap": round(now - rec.last_beat, 3)})
                self._recover(rec)

    def _recover(self, rec: ChildRecord) -> None:
        if rec.recoveries_left <= 0:
            return
        rec.recoveries_left -= 1
        if rec.process.is_alive():
            rec.process.terminate()
            rec.process.join(timeout=1.0)

        if rec.genome.recovery_strategy == 2:
            # report_and_idle
            self._log("idle", rec.child_id, {})
            return

        time.sleep(rec.genome.backoff)
        replacement = self.spawn(rec.genome, rec.child_id)
        replacement.recoveries_left = rec.recoveries_left
        replacement.recoveries_ok = rec.recoveries_ok + 1
        replacement.beats = rec.beats
        replacement.peak_rss_mb = rec.peak_rss_mb
        self._log("recovered", rec.child_id, {"left": rec.recoveries_left})

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.time()
        rows = []
        for rec in self.state.children.values():
            # Verificación opcional desde el padre (puede diferir ligeramente del reporte del hijo)
            parent_view = _pid_resources(rec.process.pid if rec.process.is_alive() else None)
            rows.append(
                {
                    "id": rec.child_id,
                    "pid": rec.process.pid,
                    "alive": rec.alive and rec.process.is_alive(),
                    "beats": rec.beats,
                    "last_beat_ago": round(now - rec.last_beat, 3),
                    "recoveries_ok": rec.recoveries_ok,
                    "recoveries_left": rec.recoveries_left,
                    # Recursos reales
                    "rss_mb": rec.rss_mb,
                    "peak_rss_mb": rec.peak_rss_mb,
                    "cpu_pct": rec.cpu_pct,
                    "rss_mb_parent_view": parent_view["rss_mb"],
                    # Presupuesto genético (simulado)
                    "genome_cpu_budget": rec.genome.cpu_budget,
                    "genome_memory_mb": rec.genome.memory_mb,
                    "genome": rec.genome.to_dict(),
                }
            )
        return rows

    def resource_summary(self) -> dict[str, Any]:
        """Resumen agregado de consumo de todos los hijos (vivos o no)."""
        rows = list(self.state.children.values())
        if not rows:
            return {"children": 0, "total_rss_mb": 0.0, "avg_rss_mb": 0.0, "max_peak_rss_mb": 0.0}
        total_rss = sum(r.rss_mb for r in rows)
        peaks = [r.peak_rss_mb for r in rows]
        return {
            "children": len(rows),
            "alive": sum(1 for r in rows if r.alive and r.process.is_alive()),
            "total_rss_mb": round(total_rss, 3),
            "avg_rss_mb": round(total_rss / len(rows), 3),
            "max_peak_rss_mb": round(max(peaks) if peaks else 0.0, 3),
            "per_child": [
                {
                    "id": r.child_id,
                    "rss_mb": r.rss_mb,
                    "peak_rss_mb": r.peak_rss_mb,
                    "cpu_pct": r.cpu_pct,
                    "beats": r.beats,
                }
                for r in rows
            ],
        }

    def shutdown(self) -> None:
        self.stop_event.set()
        for rec in self.state.children.values():
            try:
                rec.inbox.put(Message(kind="shutdown", sender="parent", target=rec.child_id))
            except Exception:
                pass
            if rec.process.is_alive():
                rec.process.terminate()
                rec.process.join(timeout=1.5)
