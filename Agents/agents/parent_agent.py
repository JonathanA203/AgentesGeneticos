import asyncio
from spade.agent import Agent
from spade.behaviour import FSMBehaviour

from config import STATE_IDLE, STATE_MONITORING, FUNCTIONS_TO_OPTIMIZE, STATE_SPAWNING, METRICS_ENABLED
from agents.states import IdleState, MonitoringState, SpawningState
from monitoring import ResourceMonitorBehaviour


# ==========================================
# AGENTE MONITOR (Orquestador FSM)
# ==========================================
class ParentAgent(Agent):
    async def setup(self):
        # Variables internas de la "memoria" del agente
        self.funciones_pendientes = list(FUNCTIONS_TO_OPTIMIZE)
        self.resultados = []
        self.spawners_creados = 0
        self.funcion_en_curso = None
        self.intento_actual = 0
        self.run_id = None
        self.hijo_pid = None  # PID del proceso hijo en vigilancia
        self.intentos = []  # historial de intentos: función, pid, veredicto y duración
        self.fase = ""  # fase actual del FSM, la lee el monitoreo de recursos
        self.recorder = None
        # Se activa cuando el monitoreo de recursos ya está muestreando
        self.metrics_ready = asyncio.Event()
        if not METRICS_ENABLED:
            self.metrics_ready.set()

        # Máquina de Estados
        fsm = FSMBehaviour()

        # Registrar los estados
        fsm.add_state(name=STATE_IDLE, state=IdleState(), initial=True)
        fsm.add_state(name=STATE_MONITORING, state=MonitoringState())
        fsm.add_state(name=STATE_SPAWNING, state=SpawningState())

        # Registrar las transiciones válidas
        fsm.add_transition(source=STATE_IDLE, dest=STATE_SPAWNING)
        fsm.add_transition(source=STATE_SPAWNING, dest=STATE_MONITORING)
        fsm.add_transition(source=STATE_MONITORING, dest=STATE_IDLE)
        fsm.add_transition(source=STATE_MONITORING, dest=STATE_SPAWNING)  # reintento tras un hijo muerto o colgado

        self.add_behaviour(fsm)

        # Monitoreo de recursos en paralelo al FSM
        if METRICS_ENABLED:
            self.add_behaviour(ResourceMonitorBehaviour())
