"""Proceso hijo: heartbeat, chequeo del padre y espera de órdenes."""

from __future__ import annotations

import random
import time
import sys
import multiprocessing
from multiprocessing import Queue
from multiprocessing.synchronize import Event as SyncEvent
from typing import Any

from src.genes import ChildGenome, decode
from src.ipc import Message

try:
    import psutil
except ImportError:
    psutil = None


def _self_resources() -> dict[str, float]:
    if psutil is None:
        return {"rss_mb": 0.0, "cpu_pct": 0.0}
    try:
        proc = psutil.Process()
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
    genome: ChildGenome = decode(genome_vector)
    rng = random.Random(hash(child_id) & 0xFFFFFFFF)

    promotion_triggered = False
    last_ack_time = time.time()
    last_parent_check = 0.0
    parent_timeout_threshold = max(3.0, genome.parent_check_interval * 3.5)

    _self_resources()

    try:
        boot_res = _self_resources()
        to_parent.put(Message(kind="heartbeat", sender=child_id, target="parent", payload={"boot": True, "genome": genome.to_dict(), "cpu": genome.cpu_budget, "mem": genome.memory_mb, **boot_res}))

        while True:
            try:
                if stop_event.is_set():
                    break
            except Exception:
                pass
            
            now = time.time()
            
            if not promotion_triggered and (now - last_ack_time > parent_timeout_threshold):
                if genome.promotion_eligible == 1:
                    promotion_triggered = True
                    sys.stderr.write(f"\n[ALERTA] {child_id} detectó padre ausente. ¡Iniciando protocolo de promoción!\n\n")
                    sys.stderr.flush()
                    
                    from src.promotion import acquire_promotion_lock
                    time.sleep(rng.uniform(0.0, 1.5))
                    
                    if acquire_promotion_lock():
                        sys.stderr.write(f"\n[PROMOCIÓN] {child_id} HA GANADO EL LOCK. ¡Ahora es el nuevo Padre!\n\n")
                        sys.stderr.flush()
                        
                        from src.parent import ParentAgent
                        try:
                            # Crear un nuevo manager local para el nuevo padre
                            nuevo_manager = multiprocessing.Manager()
                            nuevo_padre = ParentAgent.from_checkpoint(
                                checkpoint_path="runtime/parent_checkpoint.json",
                                new_parent_id=child_id,
                                manager=nuevo_manager
                            )
                            nuevo_padre.stop_event = stop_event
                            
                            sys.stderr.write(f"\n[{child_id}] Nuevo Padre asumiendo el control y monitoreando...\n\n")
                            sys.stderr.flush()
                            
                            while not stop_event.is_set():
                                nuevo_padre.poll(timeout=0.05)
                                
                        except Exception as e:
                            sys.stderr.write(f"\n[ERROR] {child_id} falló al asumir como Padre: {e}\n")
                            sys.stderr.flush()
                            break
                        
                        nuevo_padre.shutdown()
                        break
                    else:
                        sys.stderr.write(f"\n[PROMOCIÓN] {child_id} perdió la carrera. Ya hay un nuevo Padre.\n\n")
                        sys.stderr.flush()
                        while not stop_event.is_set():
                            time.sleep(1.0)
                        break
                else:
                    last_ack_time = now 
                    time.sleep(5.0)
                    continue

            jitter = 1.0 + genome.jitter * (rng.random() * 2 - 1)
            sleep_for = max(0.12, genome.heartbeat_interval * jitter)

            res = _self_resources()
            try: 
                to_parent.put(Message(kind="heartbeat", sender=child_id, target="parent", payload={"cpu": genome.cpu_budget, "mem": genome.memory_mb, "rss_mb": res["rss_mb"], "cpu_pct": res["cpu_pct"]}))
            except Exception:
                pass

            if now - last_parent_check >= genome.parent_check_interval:
                last_parent_check = now
                try: 
                    to_parent.put(Message(kind="parent_ping", sender=child_id, target="parent", payload={}))
                except Exception:
                    pass

            deadline = time.time() + sleep_for
            while time.time() < deadline:
                try:
                    if stop_event.is_set():
                        break
                except Exception:
                    pass
                    
                try:
                    msg: Message | dict[str, Any] = from_parent.get(timeout=0.05)
                except Exception:
                    continue
                
                if isinstance(msg, dict): kind = msg.get("kind")
                else: kind = msg.kind
                
                if kind == "shutdown": return
                if kind == "parent_alive": last_ack_time = time.time()
                if kind == "promote":
                    try: to_parent.put(Message(kind="recovered", sender=child_id, target="parent", payload={"promoted": True}))
                    except Exception: pass
    except KeyboardInterrupt:
        sys.stderr.write(f"\n[{child_id}] Interrumpido por el usuario. Saliendo...\n")
        sys.stderr.flush()
        return
    except BaseException as e:
        import traceback
        sys.stderr.write(f"\n[{child_id}] CRASH CRÍTICO: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()