"""Punto de entrada del sistema multi-agente.

Banderas CLI:
  --children N   Número máximo de hijos concurrentes (default: 1, o AGENTES_MAX_CHILDREN).
  --demo         Activa el modo demo (permite/espera el uso del inyector de fallos).
                 Sin esta bandera se asume entorno real con EDR u otro supervisor externo.
  --behaviors    Lista separada por comas de comportamientos de laboratorio que
                 ejecutarán los hijos (ver behaviors.py). Ejemplo: low_profile,lab_artifact
"""
import argparse
import asyncio
import os
import time

from config import XMPP_SERVER, PASSWORD, MAX_CHILDREN, DEMO_MODE, DEFAULT_CHILD_BEHAVIORS
from log_config import get_logger
from agents.parent_agent import ParentAgent

log = get_logger("main")


def parse_args():
    ap = argparse.ArgumentParser(
        description="Sistema multi-agente con algoritmos genéticos (DEAP) y supervisión de hijos."
    )
    ap.add_argument(
        "--children",
        type=int,
        default=None,
        metavar="N",
        help=f"Número máximo de hijos concurrentes (default: {MAX_CHILDREN}). "
             "Con N>1 el monitor puede tener varios procesos hijo activos a la vez.",
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        default=None,
        help="Modo demo: se asume el uso del inyector de fallos (tools/fault_injector.py). "
             "Sin esta bandera se trabaja contra el entorno real (EDR u otro).",
    )
    ap.add_argument(
        "--behaviors",
        type=str,
        default=None,
        help="Comportamientos de laboratorio para los hijos, separados por comas "
             "(ej: low_profile,lab_artifact,heartbeat). Ver behaviors.py.",
    )
    return ap.parse_args()


async def main():
    args = parse_args()

    # Resolver configuración efectiva (CLI > env > default de config)
    max_children = args.children if args.children is not None else MAX_CHILDREN
    demo = args.demo if args.demo is not None else DEMO_MODE
    if args.behaviors is not None:
        behaviors = [b.strip() for b in args.behaviors.split(",") if b.strip()]
    else:
        behaviors = list(DEFAULT_CHILD_BEHAVIORS)

    # Propagar a variables de entorno para que los subprocesos hijo las lean
    os.environ["AGENTES_MAX_CHILDREN"] = str(max_children)
    os.environ["AGENTES_DEMO"] = "1" if demo else "0"
    os.environ["AGENTES_BEHAVIORS"] = ",".join(behaviors)

    log.info("Iniciando Sistema Multi-Agente v2 (DEAP)...")
    log.info(f"  max_children = {max_children}")
    log.info(f"  demo_mode    = {demo}  ({'inyector de fallos permitido' if demo else 'entorno real / EDR'})")
    log.info(f"  behaviors    = {behaviors or '(ninguno)'}")

    if demo:
        log.info("  [demo] Recuerda lanzar el inyector en otra terminal si quieres simular muertes/cuelgues:")
        log.info("         python tools/fault_injector.py --kill sphere:1 --duration 90")
    else:
        log.info("  [real] No se usará el inyector. La supervivencia depende del entorno real (EDR, etc.).")

    padre_jid = f"padre_orquestador_{int(time.time())}@{XMPP_SERVER}"
    padre = ParentAgent(padre_jid, PASSWORD)
    # Atributos de configuración que el FSM y los spawners pueden leer
    padre.max_children = max_children
    padre.demo_mode = demo
    padre.child_behaviors = behaviors

    await padre.start(auto_register=True)

    # Mantener el script vivo mientras el padre siga activo
    while padre.is_alive():
        try:
            await asyncio.sleep(1)
        except KeyboardInterrupt:
            break

    log.info("Apagando motor SPADE...")
    await padre.stop()


if __name__ == "__main__":
    # SPADE requiere que se ejecute el loop asíncrono
    asyncio.run(main())
