"""Configuración de logging del sistema: hora con milisegundos y nivel en cada línea.

Solo se configuran los loggers propios (`agentes.*`); los de las librerías (slixmpp, spade, ...)
no se tocan para no inundar la salida.

Variables de entorno opcionales:
  AGENTES_LOG_LEVEL  Nivel mínimo: DEBUG, INFO (default), WARNING, ERROR.
  AGENTES_LOG_FILE   Si se define, además de la consola se escribe en ese archivo.
                     (main.py lo usa; los procesos hijo lo ignoran: su stdout ya va a logs/hijos/.)
"""
import logging
import os
import sys
from pathlib import Path

_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"
_configured = False


def setup_logging(log_file: str | None = None) -> None:
    """Configura el logger raíz de la aplicación. Es idempotente."""
    global _configured
    if _configured:
        return
    _configured = True

    base = logging.getLogger("agentes")
    base.setLevel(os.environ.get("AGENTES_LOG_LEVEL", "INFO").upper())
    base.propagate = False  # no mezclar con los logs de las librerías

    formatter = logging.Formatter(_FORMAT, _DATEFMT)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    base.addHandler(console)

    log_file = log_file or os.environ.get("AGENTES_LOG_FILE")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setFormatter(formatter)
        base.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger `agentes.<name>` ya configurado."""
    setup_logging()
    return logging.getLogger(f"agentes.{name}")
