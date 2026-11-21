## 1. Introducción

### 1.1 Qué es

Es un prototipo de laboratorio que modela un sistema de **procesos padre e hijo** con:

1. **Comunicación periódica** (heartbeats y ACK).
2. **Detección de ausencia** (watchdog).
3. **Recuperación adaptativa** tras terminaciones simuladas.
4. **Evolución de parámetros** mediante algoritmos genéticos.

Se centra en el **componente secundario (proceso hijo)**: cómo se representan genéticamente sus parámetros de comportamiento y cómo se evalúa su “calidad” con una función de fitness orientada a persistencia adaptativa.

Todo ocurre con `multiprocessing` de Python, colas locales y un simulador discreto. La “presión de laboratorio” consiste en **terminar procesos hijo de forma controlada** para estudiar recuperación, no en ocultarse del sistema.

### 1.3 Objetivo académico

Analizar cómo un conjunto de **parámetros evolutivos** (genes) afecta la capacidad de un proceso hijo de:

- Mantenerse observable y vivo frente a un padre supervisor.
- Recuperarse tras fallos inducidos.
- Comunicarse de forma fiable.
- No consumir recursos de forma excesiva (eficiencia simulada).

Los resultados alimentan el informe de tesis y el diseño de contramedidas o métricas de detección de comportamientos resilientes multi-proceso.

---

## 2. Arquitectura general

```
                    ┌─────────────────────────────────────┐
                    │           main.py                   │
                    │   --demo  |  --evolve               │
                    └─────────────┬───────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
   ┌─────────────┐        ┌──────────────┐        ┌──────────────┐
   │ ParentAgent │◄──────►│   run_child  │        │  evolution   │
   │  (parent)   │  Queue │   (hijos)    │        │  + simulator │
   └─────────────┘        └──────────────┘        └──────┬───────┘
          │                       │                       │
          │                       │                       ▼
          │                       │               ┌──────────────┐
          └───────────┬───────────┘               │   fitness    │
                      │                           │   + genes    │
                      ▼                           └──────────────┘
                 ipc.Message
```

### 2.1 Dos modos de ejecución

| Modo           | Qué hace                                                     | Para qué sirve                                       |
| -------------- | ------------------------------------------------------------ | ---------------------------------------------------- |
| **`--demo`**   | Lanza procesos reales (padre + N hijos) con colas y watchdog | Demostrar comunicación viva y recuperación           |
| **`--evolve`** | Evalúa genomas en un **simulador** rápido y corre el AG      | Optimizar parámetros sin el coste de procesos reales |

El simulador replica la lógica de supervivencia/recuperación del demo, de modo que el AG pueda evaluar cientos de individuos por generación.

### 2.2 Mapa de módulos

| Archivo        | Responsabilidad                                       |
| -------------- | ----------------------------------------------------- |
| `genes.py`     | Punto 1: cromosoma, bounds, `ChildGenome`, `decode()` |
| `fitness.py`   | Punto 2: pesos, `EpisodeStats`, `evaluate_stats()`    |
| `ipc.py`       | Tipos de mensaje padre ↔ hijo                         |
| `child.py`     | Bucle del proceso hijo                                |
| `parent.py`    | Agente padre: spawn, ACK, watchdog, recover           |
| `simulator.py` | Episodio discreto para evaluación del AG              |
| `evolution.py` | Algoritmo genético (DEAP)                             |
| `main.py`      | CLI de entrada                                        |

---

## 3. Punto 1 — Representación genética (`genes.py`)

### 3.1 Idea central

Cada **proceso hijo** se modela como un **individuo** del algoritmo genético.  
El cromosoma es un vector de **10 números reales**.  
Al decodificarlo se obtiene un objeto `ChildGenome` con tipos y restricciones válidas.

Los genes **no** codifican payloads ni rutas de persistencia del SO. Codifican **comportamiento de watchdog**: ritmo de comunicación, tolerancia a fallos, reintentos y coste de recursos simulado.

### 3.2 Orden del cromosoma (`GENE_ORDER`)

| Índice | Nombre                  | Tipo efectivo | Rango        |
| -----: | ----------------------- | ------------- | ------------ |
|      0 | `heartbeat_interval`    | float (s)     | 0.40 – 3.00  |
|      1 | `watchdog_timeout`      | float (s)     | 1.00 – 8.00  |
|      2 | `parent_check_interval` | float (s)     | 0.50 – 4.00  |
|      3 | `recovery_attempts`     | int           | 1 – 6        |
|      4 | `backoff`               | float (s)     | 0.10 – 2.00  |
|      5 | `jitter`                | float         | 0.00 – 0.25  |
|      6 | `cpu_budget`            | float         | 0.05 – 0.80  |
|      7 | `memory_mb`             | float         | 8.00 – 48.00 |
|      8 | `recovery_strategy`     | int {0,1,2}   | 0 – 2        |
|      9 | `promotion_eligible`    | int {0,1}     | 0 – 1        |

### 3.3 Significado de cada gen

#### `heartbeat_interval`

Intervalo base entre mensajes `heartbeat` del hijo al padre.

- **Bajo**: el padre detecta caídas pronto, pero hay más tráfico y “coste”.
- **Alto**: menos tráfico, pero el watchdog tarda más en reaccionar.

#### `watchdog_timeout`

Tiempo máximo sin heartbeat antes de que el padre declare al hijo **ausente**.  
Debe ser **mayor** que el intervalo de heartbeat (con margen por jitter).  
Si no se cumple, `decode()` **repara** el valor.

#### `parent_check_interval`

Cada cuánto el hijo envía `parent_ping` para comprobar que el padre sigue vivo.  
Útil para escenarios de **promoción** (un hijo elegible puede asumir el rol de padre si el original desaparece; en esta versión la promoción se modela a nivel de mensajes/diseño).

#### `recovery_attempts`

Número máximo de reintentos de recuperación tras terminaciones de laboratorio.

#### `backoff`

Segundos de espera antes de cada reintento. Evita relanzamientos en ráfaga.

#### `jitter`

Fracción de variación aleatoria sobre el intervalo de heartbeat:

\[
\text{intervalo real} = \text{heartbeat_interval} \times (1 + \text{jitter} \times U(-1,1))
\]

Evita que todos los hijos pulsen en el mismo instante (sincronización artificial).

#### `cpu_budget` y `memory_mb`

Presupuestos **simulados** de recurso. No limitan el proceso real del SO; solo intervienen en la **fitness de eficiencia** (valores altos penalizan).

#### `recovery_strategy`

| Valor | Nombre            | Comportamiento                                           |
| ----: | ----------------- | -------------------------------------------------------- |
|     0 | `restart_self`    | El padre relanza al hijo con el mismo genoma             |
|     1 | `wait_parent`     | Espera / recuperación probabilística guiada por el padre |
|     2 | `report_and_idle` | Reporta el fallo y no se recupera activamente            |

#### `promotion_eligible`

- `0`: no puede asumir el rol de padre.
- `1`: marcado como elegible (diseño de resiliencia jerárquica).

## 4. Punto 2 — Función de fitness (`fitness.py`)

### 4.1 Objetivo

Asignar a cada genoma un score en **[0, 1]** que refleje qué tan bien se comporta un hijo bajo presión de laboratorio, privilegiando:

1. Permanecer vivo el mayor tiempo posible.
2. Recuperarse cuando lo terminan.
3. Comunicarse de forma fiable.
4. Consumir poco recurso simulado.
5. Mantener sincronía con el padre.

### 4.2 Pesos (`WEIGHTS`)

| Componente    | Peso | Descripción                              |
| ------------- | ---: | ---------------------------------------- |
| Supervivencia | 0.40 | Fracción de tiempo vivo                  |
| Recuperación  | 0.25 | Éxitos de recuperación / intentos        |
| Heartbeat     | 0.20 | Calidad de latidos y ACK                 |
| Eficiencia    | 0.10 | Inverso del uso de CPU/memoria simulados |
| Sync          | 0.05 | Chequeos al padre respondidos            |

### 4.3 Estructura `EpisodeStats`

Métricas que alimentan la fitness:

| Campo                  | Significado                                          |
| ---------------------- | ---------------------------------------------------- |
| `duration`             | Duración del episodio                                |
| `alive_time`           | Tiempo acumulado en estado vivo                      |
| `expected_heartbeats`  | Heartbeats esperados ≈ duration / heartbeat_interval |
| `heartbeats_sent`      | Heartbeats efectivamente enviados                    |
| `heartbeats_acked`     | Heartbeats con ACK (en simulación ≈ enviados)        |
| `missed_watchdogs`     | Veces que se perdió el latido por presión/caída      |
| `pressure_events`      | Terminaciones simuladas                              |
| `recoveries_attempted` | Intentos de recuperación                             |
| `recoveries_ok`        | Recuperaciones exitosas                              |
| `parent_checks`        | `parent_ping` enviados                               |
| `parent_seen_alive`    | Respuestas de padre vivo                             |
| `invalid_genome`       | Flag de genoma inválido                              |

### 4.4 Cálculo detallado (`evaluate_stats`)

Sea \(r(a,b) = \mathrm{clip}(a/b, 0, 1)\) (0 si \(b \le 0\)).

**Supervivencia**

\[
S = r(\text{alive_time}, \text{duration})
\]

**Recuperación**

\[
R = r(\text{recoveries_ok}, \max(1, \text{recoveries_attempted}))
\]

Si no hubo presión ni intentos: \(R = 1\) si \(S > 0.8\), si no \(R = 0.5\).

**Heartbeat**

\[
H = r(\text{sent}, \max(1, \text{expected})) \times r(\text{acked}, \max(1, \text{sent}))
\]

Si hubo `missed_watchdogs`:

\[
H \leftarrow H \times \max(0.2,\ 1 - 0.15 \times \text{missed_watchdogs})
\]

**Eficiencia**

Se normalizan CPU y memoria al rango de sus bounds:

\[
E = 1 - (0.65 \cdot \mathrm{cpu_norm} + 0.35 \cdot \mathrm{mem_norm})
\]

**Sync**

\[
Y = r(\text{parent_seen_alive}, \max(1, \text{parent_checks}))
\]

**Penalización**

Si el watchdog queda por debajo del mínimo teórico o `invalid_genome`:

\[
P = 0.35
\]

(en caso contrario \(P = 0\)).

**Total**

\[
F = 0.40 S + 0.25 R + 0.20 H + 0.10 E + 0.05 Y - P
\]

\[
F \leftarrow \mathrm{clip}(F, 0, 1)
\]

---

## 5. Comunicación e IPC (`ipc.py`, `child.py`, `parent.py`)

### 5.1 Mensajes (`Message`)

Campos: `kind`, `sender`, `target`, `ts`, `payload`.

| kind                    | Dirección    | Uso                                    |
| ----------------------- | ------------ | -------------------------------------- |
| `heartbeat`             | hijo → padre | “Sigo vivo” (+ datos de boot/recursos) |
| `ack`                   | padre → hijo | Confirmación de recepción              |
| `parent_ping`           | hijo → padre | ¿El padre sigue vivo?                  |
| `parent_alive`          | padre → hijo | Respuesta afirmativa                   |
| `child_down`            | (log padre)  | Watchdog detectó ausencia              |
| `recover` / `recovered` | varios       | Flujo de recuperación / promoción      |
| `promote`               | padre → hijo | Señal de promoción (diseño)            |
| `shutdown`              | padre → hijo | Apagado ordenado del laboratorio       |

### 5.2 Proceso hijo (`run_child`)

1. Decodifica el cromosoma.
2. Envía un heartbeat de **boot** con el genoma.
3. Bucle hasta `stop_event`:
   - Calcula intervalo con jitter.
   - Envía `heartbeat`.
   - Si toca, envía `parent_ping`.
   - Durante la espera, lee la cola del padre (`ack`, `shutdown`, `promote`).

### 5.3 Proceso padre (`ParentAgent`)

**Spawn**  
Crea `Process` daemon, cola de entrada del hijo, registra `ChildRecord` (último beat, reintentos, contadores).

**Poll**

- Lee mensajes de la cola compartida.
- En `heartbeat`: actualiza `last_beat`, marca vivo, incrementa beats, envía `ack`.
- En `parent_ping`: responde `parent_alive`.
- Ejecuta **watchdog**.

**Watchdog**  
Si `now - last_beat > watchdog_timeout` → hijo ausente → `_recover`.

**Recover**

- Decrementa `recoveries_left`.
- Termina el proceso si sigue vivo.
- Estrategia 2 (`report_and_idle`): no relanza.
- Otras: espera `backoff` y hace `spawn` con el **mismo id y genoma**, heredando contadores.

**Snapshot**  
Lista JSON-friendly del estado de cada hijo (pid, alive, beats, genoma, etc.).

**Shutdown**  
Señal global, `shutdown` a cada hijo, `terminate` + `join`.

### 5.4 Flujo temporal (resumen)

```
t0  Padre spawnea hijo-1 … hijo-N
t1  Hijo envía heartbeat (boot)
t2  Padre ACK
…
tk  Laboratorio hace terminate(hijo-k)   [solo en --demo con presión]
tk+δ  Padre no recibe beats → child_down
tk+backoff  Padre relanza hijo-k (si strategy y attempts lo permiten)
```

---

## 6. Ejecución

### 6.1 Demo

```bash
python -m main --demo --seconds 20 --children 4
```

- Crea 4 genomas aleatorios.
- Arranca `ParentAgent`.
- Cada ~2 s imprime un `snapshot` JSON.
- Con presión activa (por defecto), con cierta probabilidad hace `terminate` a un hijo vivo (`lab_pressure`).
- Al terminar: `shutdown`.

Sin presión:

```bash
python -m main --demo --seconds 15 --children 3 --no-pressure
```

### 6.2 Evolución

```bash
python -m main --evolve --generations 12 --population 24
```

Imprime el motor usado y el JSON completo de resultados.

### 6.3 Dependencias

```text
deap>=1.4.0
numpy>=1.24.0
```

---
