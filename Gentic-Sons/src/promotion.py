"""Gestión de bloqueos atómicos para la promoción a Padre."""
import os
try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

LOCK_FILE = "runtime/promotion.lock"

def acquire_promotion_lock() -> bool:
    """
    Intenta adquirir el candado de promoción.
    Devuelve True si este proceso ganó la carrera, False si ya hay un padre.
    """
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    try:
        # O_CREAT | O_EXCL falla si el archivo ya existe (es atómico en el SO)
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False

def release_promotion_lock() -> None:
    """Libera el candado (útil si el nuevo padre se apaga correctamente)."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def clean_stale_lock() -> None:
    """
    Elimina el lock si el proceso que lo creó ya no está vivo (Stale Lock).
    """
    if not os.path.exists(LOCK_FILE):
        return
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid_str = f.read().strip()
            if not pid_str:
                os.remove(LOCK_FILE)
                return
            pid = int(pid_str)
            # Si el proceso que creó el lock ya no existe, lo eliminamos
            if not psutil.pid_exists(pid):
                os.remove(LOCK_FILE)
    except Exception:
        # Si hay cualquier error leyendo el archivo, lo borramos por seguridad
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass