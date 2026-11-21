import asyncio
import json
import time
from spade.behaviour import State
from spade.message import Message

from config import (STATE_IDLE, STATE_SPAWNING, STATE_MONITORING, XMPP_SERVER, PASSWORD,
                    START_TIMEOUT, CHILD_TIMEOUT, DEATH_GRACE, POLL_INTERVAL, MAX_ATTEMPTS)
from functions import FUNCTIONS, random_genome
from agents.spawner_agent import SpawnerAgent
from agents.supervision import child_alive, kill_child


# ==========================================
# ESTADOS DEL AGENTE MONITOR
# IDLE -> SPAWNING -> MONITORING -> IDLE
#                 ^----(reintento)----+
#
# Con --children N (max_children > 1) el monitor puede tener varios hijos
# activos a la vez. La lógica de veredicto por hijo se mantiene.
# ==========================================
class IdleState(State):
    async def run(self):
        try:
            await asyncio.wait_for(self.agent.metrics_ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        self.agent.fase = STATE_IDLE
        print("\n[MONITOR - IDLE] Revisando si hay funciones pendientes...")

        has_pending = bool(self.agent.funciones_pendientes) or self.agent.funcion_en_curso is not None
        has_active = bool(getattr(self.agent, "active_children", {}))

        if has_pending or has_active:
            print("[MONITOR - IDLE] Trabajo pendiente. Cambiando a estado SPAWNING.")
            self.set_next_state(STATE_SPAWNING)
        else:
            print("\n[MONITOR - IDLE] No hay más funciones. Misión cumplida.")
            for r in self.agent.resultados:
                print(f"  {r['function']} ({r['goal']}): {r['best_value']:.6f} "
                      f"(óptimo conocido {r['known_optimum']}) en {[round(g, 4) for g in r['best_solution']]}")
            fallidas = {i["function"] for i in self.agent.intentos} - {r["function"] for r in self.agent.resultados}
            if fallidas:
                print(f"  SIN RESULTADO tras {MAX_ATTEMPTS} intentos: {sorted(fallidas)}")
            print("\nIntentos de hijos (cada hijo es un proceso independiente):")
            print(f"  {'función':<10}{'intento':>8}{'pid':>8}  {'veredicto':<12}{'duración s':>10}")
            for i in self.agent.intentos:
                print(f"  {i['function']:<10}{i['attempt']:>8}{str(i['pid'] or '-'):>8}  {i['verdict']:<12}{i['seconds']:>10.1f}")
            if self.agent.recorder:
                print("\nConsumo de recursos:\n" + self.agent.recorder.summary())
            await self.agent.stop()


class SpawningState(State):
    async def run(self):
        self.agent.fase = STATE_SPAWNING
        max_children = getattr(self.agent, "max_children", 1)
        behaviors = getattr(self.agent, "child_behaviors", [])

        if not hasattr(self.agent, "active_children"):
            self.agent.active_children = {}

        activos = len(self.agent.active_children)
        slots = max(0, max_children - activos)

        if slots == 0 and activos > 0:
            print(f"[MONITOR - SPAWNING] Ya hay {activos} hijo(s) activo(s) (máx {max_children}). Esperando.")
            self.set_next_state(STATE_MONITORING)
            return

        to_spawn = []
        # Reintento de la función en curso primero
        if self.agent.funcion_en_curso is not None and slots > 0:
            to_spawn.append((self.agent.funcion_en_curso, self.agent.intento_actual))
            slots -= 1
        # Nuevas funciones de la cola
        while slots > 0 and self.agent.funciones_pendientes:
            fn = self.agent.funciones_pendientes.pop(0)
            to_spawn.append((fn, 1))
            slots -= 1

        if not to_spawn:
            if activos > 0:
                self.set_next_state(STATE_MONITORING)
            else:
                self.set_next_state(STATE_IDLE)
            return

        for funcion, intento in to_spawn:
            self.agent.spawners_creados += 1
            run_id = f"{funcion}-{int(time.time())}_{intento}"

            spawner_jid = f"spawner_{self.agent.spawners_creados}_{int(time.time())}@{XMPP_SERVER}"
            print(f"[MONITOR - SPAWNING] Levantando spawner {spawner_jid} (intento {intento}/{MAX_ATTEMPTS} de '{funcion}')")
            spawner = SpawnerAgent(spawner_jid, PASSWORD)
            await spawner.start(auto_register=True)

            orden = Message(to=spawner_jid)
            orden.set_metadata("performative", "request")
            genoma_base = random_genome(FUNCTIONS[funcion])
            orden.body = json.dumps({
                "function": funcion,
                "genome": genoma_base,
                "reply_to": str(self.agent.jid),
                "run_id": run_id,
                "behaviors": behaviors,
            })
            await self.send(orden)
            print(f"[MONITOR - SPAWNING] Orden enviada: optimizar '{funcion}' con genoma base {[round(g, 3) for g in genoma_base]}.")

            self.agent.active_children[run_id] = {
                "function": funcion,
                "attempt": intento,
                "pid": None,
                "create_time": None,
                "arrancado": False,
                "resultado": None,
                "gone_since": None,
                "t0": time.monotonic(),
                "veredicto": None,
            }
            self.agent.run_id = run_id
            self.agent.hijo_pid = None
            self.agent.funcion_en_curso = funcion
            self.agent.intento_actual = intento

        self.set_next_state(STATE_MONITORING)


class MonitoringState(State):
    """Vigila a los hijos activos: mensajes XMPP + estado del proceso en el SO.
    Soporta varios hijos en paralelo (max_children)."""

    async def run(self):
        self.agent.fase = STATE_MONITORING
        if not hasattr(self.agent, "active_children"):
            self.agent.active_children = {}

        print(f"[MONITOR - MONITORING] Vigilando {len(self.agent.active_children)} hijo(s) activo(s)...")

        while self.agent.active_children:
            msg = await self.receive(timeout=POLL_INTERVAL)
            if msg:
                try:
                    body = json.loads(msg.body)
                except (json.JSONDecodeError, TypeError):
                    body = {}
                run_id = body.get("run_id")
                if run_id not in self.agent.active_children:
                    continue
                child = self.agent.active_children[run_id]
                t = body.get("type")
                if t == "launched":
                    child["pid"] = body["pid"]
                    child["create_time"] = body["create_time"]
                    self.agent.hijo_pid = body["pid"]
                    print(f"[MONITOR - MONITORING] Proceso hijo lanzado: PID {body['pid']} (run {run_id}).")
                elif t == "started":
                    child["pid"] = body["pid"]
                    child["create_time"] = body["create_time"]
                    child["arrancado"] = True
                    self.agent.hijo_pid = body["pid"]
                    print(f"[MONITOR - MONITORING] El hijo confirmó su arranque (PID {body['pid']}, run {run_id}).")
                elif t == "result":
                    child["resultado"] = body
                    child["veredicto"] = "exito"

            cerrados = []
            for run_id, child in list(self.agent.active_children.items()):
                if child["veredicto"] is not None:
                    cerrados.append(run_id)
                    continue
                elapsed = time.monotonic() - child["t0"]
                pid = child["pid"]
                create_time = child["create_time"]
                if pid is None:
                    if elapsed > START_TIMEOUT:
                        child["veredicto"] = "sin_arranque"
                        cerrados.append(run_id)
                else:
                    if child_alive(pid, create_time):
                        child["gone_since"] = None
                        if elapsed > CHILD_TIMEOUT:
                            kill_child(pid, create_time)
                            child["veredicto"] = "colgado"
                            cerrados.append(run_id)
                        elif not child["arrancado"] and elapsed > START_TIMEOUT:
                            kill_child(pid, create_time)
                            child["veredicto"] = "sin_arranque"
                            cerrados.append(run_id)
                    else:
                        child["gone_since"] = child["gone_since"] or time.monotonic()
                        if time.monotonic() - child["gone_since"] >= DEATH_GRACE:
                            child["veredicto"] = "muerto"
                            cerrados.append(run_id)

            for run_id in cerrados:
                child = self.agent.active_children.pop(run_id)
                funcion = child["function"]
                intento = child["attempt"]
                pid = child["pid"]
                veredicto = child["veredicto"]
                segundos = time.monotonic() - child["t0"]
                self.agent.intentos.append({
                    "function": funcion,
                    "attempt": intento,
                    "pid": pid,
                    "verdict": veredicto,
                    "seconds": segundos,
                })

                if veredicto == "exito":
                    resultado = child["resultado"]
                    print(f"[MONITOR - MONITORING] ¡Resultado recibido!: {resultado['function']} -> {resultado['best_value']:.6f}")
                    resultado.update({"pid": pid, "attempts": intento})
                    self.agent.resultados.append(resultado)
                    if self.agent.funcion_en_curso == funcion:
                        self.agent.funcion_en_curso = None
                else:
                    print(f"[MONITOR - MONITORING] FALLO del hijo de '{funcion}': {veredicto.upper()} "
                          f"(pid {pid or '-'}, intento {intento}/{MAX_ATTEMPTS}).")
                    if intento < MAX_ATTEMPTS:
                        self.agent.funcion_en_curso = funcion
                        self.agent.intento_actual = intento + 1
                        print("[MONITOR - MONITORING] Se reintentará con un hijo nuevo.")
                    else:
                        print(f"[MONITOR - MONITORING] Se agotaron los intentos para '{funcion}'. Se continúa con las demás.")
                        if self.agent.funcion_en_curso == funcion:
                            self.agent.funcion_en_curso = None

            # Si hay slots libres y trabajo pendiente, salir a SPAWNING para rellenar
            max_children = getattr(self.agent, "max_children", 1)
            if (len(self.agent.active_children) < max_children and
                    (self.agent.funcion_en_curso is not None or self.agent.funciones_pendientes)):
                break

        if self.agent.funcion_en_curso is not None or self.agent.funciones_pendientes or self.agent.active_children:
            self.set_next_state(STATE_SPAWNING)
        else:
            self.set_next_state(STATE_IDLE)
