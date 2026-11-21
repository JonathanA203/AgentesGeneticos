# Nombres de los estados del FSM del agente monitor
STATE_IDLE = "IDLE"
STATE_MONITORING = "MONITORING"
STATE_SPAWNING = "SPAWNING"

# Configuración del servidor XMPP local
XMPP_SERVER = "localhost"
PASSWORD = "password_segura_123"

# Funciones (functions.py) que el monitor mandará optimizar
FUNCTIONS_TO_OPTIMIZE = ["sphere", "rastrigin", "peaks"]

import os


def _env_float(name, default):
    """Permite sobrescribir un valor por variable de entorno (útil para pruebas de fallos)."""
    return float(os.environ.get(name, default))


# --- Supervisión de hijos (cada hijo es un proceso del sistema operativo independiente) ---
# Segundos que espera el monitor a que el hijo avise de su arranque (PID) antes de darlo por perdido
START_TIMEOUT = _env_float("AGENTES_START_TIMEOUT", 30)
# Segundos máximos que puede vivir un hijo sin entregar resultado antes de considerarlo colgado
CHILD_TIMEOUT = _env_float("AGENTES_CHILD_TIMEOUT", 60)
# Segundos de gracia tras detectar que el proceso del hijo ya no existe (el resultado podría ir en camino)
DEATH_GRACE = 2.0
# Cada cuántos segundos revisa el monitor el estado del proceso del hijo
POLL_INTERVAL = 0.5
# Intentos máximos por función (el primero cuenta; un hijo muerto o colgado se reintenta)
MAX_ATTEMPTS = int(_env_float("AGENTES_MAX_ATTEMPTS", 2))

# Segundos que espera el spawner la orden del monitor antes de apagarse
SPAWNER_TIMEOUT = 20

# Monitoreo de recursos
from pathlib import Path
METRICS_ENABLED = True
METRICS_INTERVAL = 0.5  # segundos entre muestras (0.2) POC
# AGENTES_METRICS_CSV permite guardar el CSV de una corrida en otra ruta
METRICS_CSV_PATH = Path(os.environ.get("AGENTES_METRICS_CSV", Path(__file__).parent / "logs" / "metricas.csv"))
DOCKER_CONTAINER = "xmpp-prosody"  # contenedor del servidor XMPP a incluir en el monitoreo
