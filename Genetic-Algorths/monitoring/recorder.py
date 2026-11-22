import csv
import time
from collections import defaultdict
from pathlib import Path


class CsvRecorder:
    """Guarda cada muestra como una fila de CSV (con flush para no perder datos)
    y calcula un resumen por función al final."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = None
        self._t0 = time.time()
        self.rows = []

    def write(self, sample: dict) -> None:
        row = {"timestamp": time.strftime("%H:%M:%S"), "t_seg": round(time.time() - self._t0, 2), **sample}
        if self._writer is None:
            self._writer = csv.DictWriter(self._file, fieldnames=list(row))
            self._writer.writeheader()
        self._writer.writerow(row)
        self._file.flush()
        self.rows.append(row)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def summary(self) -> str:
        """Promedio y pico de los principales recursos, agrupados por función.

        Una muestra con varios hijos activos cuenta para cada una de sus funciones (por eso la suma
        de las filas por función puede superar al TOTAL, que cuenta cada muestra una sola vez)."""
        cols = [("sys_cpu_pct", "CPU sis %"), ("sys_ram_used_mb", "RAM sis MB"),
                ("proc_cpu_pct", "CPU py %"), ("proc_ram_mb", "RAM py MB"),
                ("hijos_proc", "procs hijo"), ("hijos_ram_mb", "RAM hijos MB"),
                ("docker_cpu_pct", "CPU docker %"), ("docker_ram_mb", "RAM docker MB")]
        groups = defaultdict(list)
        for r in self.rows:
            activas = [f for f in str(r.get("funciones_activas") or "").split("+") if f]
            for f in activas or ["(sin hijos)"]:
                groups[f].append(r)

        def stats(rows, key):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return f"{sum(vals) / len(vals):7.1f}/{max(vals):7.1f}" if vals else "      n/d      "

        lines = [f"Muestras: {len(self.rows)} | CSV: {self.path}",
                 "(cada celda: promedio/pico)",
                 f"{'grupo':<14}{'n':>4} " + " ".join(f"{label:>15}" for _, label in cols)]
        for name, rows in [("TOTAL", self.rows)] + sorted(groups.items()):
            lines.append(f"{name:<14}{len(rows):>4} " + " ".join(f"{stats(rows, k):>15}" for k, _ in cols))
        return "\n".join(lines)
