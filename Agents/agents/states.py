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
# ==========================================
class IdleState(State):
    async def run(self):
        # No arrancar el trabajo hasta que el monitoreo de recursos esté midiendo
        try:
            await asyncio.wait_for(self.agent.metrics_ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        self.agent.fase = STATE_IDLE
        print("\n[MONITOR - IDLE] Revisando si hay funciones pendientes...")

        if self.agent.funciones_pendientes:
            print("[MONITOR - IDLE] Funciones encontradas. Cambiando a estado SPAWNING.")
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
            # No definimos siguiente estado, el FSM terminará
            await self.agent.stop()


class SpawningState(State):
    async def run(self):
        self.agent.fase = STATE_SPAWNING
        if self.agent.funcion_en_curso is None:  # función nueva (si no, es un reintento)
            self.agent.funcion_en_curso = self.agent.funciones_pendientes.pop(0)
            self.agent.intento_actual = 1
        funcion = self.agent.funcion_en_curso
        intento = self.agent.intento_actual
        self.agent.spawners_creados += 1
        self.agent.hijo_pid = None
        self.agent.run_id = f"{funcion}-{int(time.time())}_{intento}"

        # 1. Levantar un spawner (one-shot) que quedará esperando la orden
        spawner_jid = f"spawner_{self.agent.spawners_creados}_{int(time.time())}@{XMPP_SERVER}"
        print(f"[MONITOR - SPAWNING] Levantando spawner {spawner_jid} (intento {intento}/{MAX_ATTEMPTS} de '{funcion}')")
        spawner = SpawnerAgent(spawner_jid, PASSWORD)
        await spawner.start(auto_register=True)

        # 2. Ordenarle crear un hijo para la función
        orden = Message(to=spawner_jid)
        orden.set_metadata("performative", "request")
        genoma_base = random_genome(FUNCTIONS[funcion])
        orden.body = json.dumps({"function": funcion, "genome": genoma_base,
                                 "reply_to": str(self.agent.jid), "run_id": self.agent.run_id})
        await self.send(orden)
        print(f"[MONITOR - SPAWNING] Orden enviada: optimizar '{funcion}' con genoma base {[round(g, 3) for g in genoma_base]}.")

        self.set_next_state(STATE_MONITORING)


class MonitoringState(State):
    """Vigila al hijo con dos señales: los mensajes que envía (arranque con PID, resultado) y el
    estado de su proceso en el sistema operativo. Con ambas distingue éxito, muerte y cuelgue."""

    async def run(self):
        self.agent.fase = STATE_MONITORING
        funcion, intento, run_id = self.agent.funcion_en_curso, self.agent.intento_actual, self.agent.run_id
        print(f"[MONITOR - MONITORING] Esperando al hijo de '{funcion}' (intento {intento})...")

        t0 = time.monotonic()
        pid = create_time = None
        arrancado = False  # el agente del hijo ya está conectado y avisó
        resultado = None
        gone_since = None
        veredicto = None

        while veredicto is None:
            msg = await self.receive(timeout=POLL_INTERVAL)
            if msg:
                body = json.loads(msg.body)
                if body.get("run_id") != run_id:
                    continue  # mensaje de un intento anterior: se ignora
                if body["type"] == "launched":  # del spawner: el proceso existe desde ya
                    pid, create_time = body["pid"], body["create_time"]
                    self.agent.hijo_pid = pid
                    print(f"[MONITOR - MONITORING] Proceso hijo lanzado: PID {pid}. Vigilándolo.")
                elif body["type"] == "started":  # del propio hijo: ya conectó a XMPP
                    pid, create_time, arrancado = body["pid"], body["create_time"], True
                    self.agent.hijo_pid = pid
                    print(f"[MONITOR - MONITORING] El hijo confirmó su arranque (PID {pid}).")
                elif body["type"] == "result":
                    resultado = body
                    veredicto = "exito"
                    break

            elapsed = time.monotonic() - t0
            if pid is None:
                if elapsed > START_TIMEOUT:
                    veredicto = "sin_arranque"  # el spawner nunca lanzó el proceso
            else:
                if child_alive(pid, create_time):
                    gone_since = None
                    if elapsed > CHILD_TIMEOUT:
                        kill_child(pid, create_time)
                        veredicto = "colgado"  # vivo pero sin entregar resultado
                    elif not arrancado and elapsed > START_TIMEOUT:
                        kill_child(pid, create_time)
                        veredicto = "sin_arranque"  # vivo, pero nunca llegó a conectarse
                else:
                    # El proceso ya no existe. Antes de darlo por muerto se espera un momento
                    # por si el resultado va en camino (el hijo envía y luego termina).
                    gone_since = gone_since or time.monotonic()
                    if time.monotonic() - gone_since >= DEATH_GRACE:
                        veredicto = "muerto"

        segundos = time.monotonic() - t0
        self.agent.intentos.append({"function": funcion, "attempt": intento, "pid": pid,
                                    "verdict": veredicto, "seconds": segundos})

        if veredicto == "exito":
            print(f"[MONITOR - MONITORING] ¡Resultado recibido!: {resultado['function']} -> {resultado['best_value']:.6f}")
            resultado.update({"pid": pid, "attempts": intento})
            self.agent.resultados.append(resultado)
            self.agent.funcion_en_curso = None
        else:
            print(f"[MONITOR - MONITORING] FALLO del hijo de '{funcion}': {veredicto.upper()} "
                  f"(pid {pid or '-'}, intento {intento}/{MAX_ATTEMPTS}).")
            if intento < MAX_ATTEMPTS:
                self.agent.intento_actual = intento + 1
                print("[MONITOR - MONITORING] Reintentando con un hijo nuevo.")
                self.set_next_state(STATE_SPAWNING)
                return
            print(f"[MONITOR - MONITORING] Se agotaron los intentos para '{funcion}'. Se continúa con las demás funciones.")
            self.agent.funcion_en_curso = None

        self.set_next_state(STATE_IDLE)
