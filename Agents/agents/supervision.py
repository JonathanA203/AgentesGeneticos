import psutil

# Tolerancia (s) al comparar la hora de creación de un proceso, para detectar PIDs reutilizados
CREATE_TIME_TOLERANCE = 1.0


def _same_process(pid: int, create_time: float):
    """Devuelve el proceso solo si el PID sigue siendo el del hijo original."""
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - create_time) > CREATE_TIME_TOLERANCE:
            return None  # el PID fue reutilizado por otro proceso: el hijo original ya no existe
        return proc
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def child_alive(pid: int, create_time: float) -> bool:
    """¿Sigue vivo el proceso del hijo? Consulta al sistema operativo, no depende de que el hijo coopere."""
    proc = _same_process(pid, create_time)
    if proc is None:
        return False
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def kill_child(pid: int, create_time: float) -> bool:
    """Termina el proceso de un hijo colgado. Devuelve True si lo terminó."""
    proc = _same_process(pid, create_time)
    if proc is None:
        return False
    try:
        proc.kill()
        proc.wait(timeout=5)
        return True
    except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
        return False
