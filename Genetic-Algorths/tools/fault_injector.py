"""Inyector de fallos para probar la supervisión de hijos. Solo para pruebas.

Vigila los procesos hijo (`child_main.py`) y les aplica una acción desde fuera, igual que lo haría un
EDR u otro proceso del sistema: no hay ningún cambio en el código del proyecto.

  --kill    función:N|all   termina el proceso (TerminateProcess), como un bloqueo del EDR
  --suspend función:N|all   congela el proceso: queda vivo pero no avanza (simula un cuelgue)

Ejemplo: python tools/fault_injector.py --kill sphere:1 --kill rastrigin:all --duration 90
"""
import argparse
import time

import psutil


def parse_rules(specs, action):
    rules = {}
    for s in specs or []:
        fn, n = s.split(":")
        rules[fn] = {"action": action, "left": float("inf") if n == "all" else int(n)}
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kill", action="append")
    ap.add_argument("--suspend", action="append")
    ap.add_argument("--delay", type=float, default=0.0, help="segundos a esperar tras ver el proceso antes de actuar")
    ap.add_argument("--duration", type=float, default=120.0)
    a = ap.parse_args()
    rules = {**parse_rules(a.suspend, "suspend"), **parse_rules(a.kill, "kill")}
    seen = set()
    t_end = time.time() + a.duration
    print(f"[inyector] reglas: { {k: (v['action'], v['left']) for k, v in rules.items()} }", flush=True)

    while time.time() < t_end:
        for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
            cmd = p.info["cmdline"] or []
            if not any("child_main.py" in c for c in cmd):
                continue
            key = (p.info["pid"], p.info["create_time"])
            if key in seen:
                continue
            seen.add(key)
            fn = cmd[cmd.index("--function") + 1] if "--function" in cmd else "?"
            rule = rules.get(fn)
            if not rule or rule["left"] <= 0:
                print(f"[inyector] {time.strftime('%H:%M:%S')} hijo de '{fn}' (PID {p.info['pid']}): se deja pasar", flush=True)
                continue
            time.sleep(a.delay)
            try:
                p.kill() if rule["action"] == "kill" else p.suspend()
                rule["left"] -= 1
                print(f"[inyector] {time.strftime('%H:%M:%S')} hijo de '{fn}' (PID {p.info['pid']}): "
                      f"{rule['action'].upper()}", flush=True)
            except psutil.NoSuchProcess:
                print(f"[inyector] hijo de '{fn}' ya había terminado", flush=True)
        time.sleep(0.02)


if __name__ == "__main__":
    main()
