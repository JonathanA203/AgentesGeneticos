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
        self.active_children = {}  # run_id -> info del hijo (soporte multi-hijo)
        # Cola de reintentos: (función, número de intento). Es independiente de las funciones
        # activas, así que varios fallos simultáneos no se pisan ni se relanza un hijo que sigue vivo.
        self.reintentos_pendientes = []
        self.intentos = []  # historial de intentos: función, pid, veredicto y duración
        self.fase = ""  # fase actual del FSM, la lee el monitoreo de recursos
        self.recorder = None
        # Se activa cuando el monitoreo de contadores ya está muestreando
        self.metrics_ready = asyncio.Event()
        if not METRICS_ENABLED:
            self.metrics_ready.set()

        # Valores por defecto (main.py puede sobrescribirlos antes de start)
        if not hasattr(self, "max_children"):
            self.max_children = 1
        if not hasattr(self, "demo_mode"):
            self.demo_mode = False
        if not hasattr(self, "child_behaviors"):
            self.child_behaviors = []

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
        fsm.add_transition(source=STATE_MONITORING, dest=STATE_SPAWNING)  # reintento o más trabajo
        fsm.add_transition(source=STATE_SPAWNING, dest=STATE_IDLE)       # sin más trabajo

        self.add_behaviour(fsm)

        # Monitoreo de recursos en paralelo al FSM
        if METRICS_ENABLED:
            self.add_behaviour(ResourceMonitorBehaviour())
