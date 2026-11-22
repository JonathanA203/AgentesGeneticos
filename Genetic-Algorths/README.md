# Agents — sistema multi-agente con SPADE y algoritmos genéticos

Prototipo de una arquitectura multi-agente en la que un **Monitor** coordina la optimización de funciones matemáticas. Para cada función, un **Spawner** de un solo uso evoluciona el mejor individuo con un algoritmo genético (**DEAP**) y lanza un **Hijo** que corre como **proceso independiente del sistema operativo**, valida el resultado y lo reporta. El Monitor vigila el proceso de cada hijo y distingue entre éxito, muerte y cuelgue, reintentando cuando falla.

Todos los agentes se comunican por **XMPP** a través de un servidor **Prosody** que corre en un contenedor Docker local.

## Alcance

**Qué hace**
- Optimiza (minimiza o maximiza) funciones de prueba: `sphere`, `rastrigin` y `peaks` (ver `functions.py`).
- Delega la evolución genética al Spawner (DEAP) y la validación a un hijo por función.
- Supervisa a cada hijo por su PID (éxito, muerto, colgado o sin arranque) y reintenta hasta `MAX_ATTEMPTS`.
- Soporta varios hijos concurrentes con `--children N`.
- Modo `--demo` (inyector de fallos) vs entorno real (EDR u otro supervisor externo).
- Capa extensible de comportamientos de laboratorio en los hijos (`behaviors.py`) para que el equipo de la tesis añada simulaciones de supervivencia.
- Mide el consumo de CPU, RAM y red del sistema, del proceso de Python, de los hijos y del contenedor, y lo guarda en un CSV.

**Qué no hace (todavía)**
- El Monitor y los Spawners comparten un proceso; solo los hijos están aislados. Si ese proceso muere, se pierde el estado del Monitor.
- No hay tests automáticos; la prueba es ejecutar el sistema y la inyección de fallos (`tools/`).
- El servidor XMPP es solo para desarrollo: registro abierto de cuentas y autenticación sin cifrar. No exponerlo a una red.

## Elementos que necesita

| Elemento | Para qué | Versión probada |
|---|---|---|
| Python | Ejecutar los agentes (necesita 3.10 o superior por la sintaxis de tipos) | 3.13 |
| Docker + Docker Compose | Ejecutar el servidor XMPP (Prosody) en un contenedor | Docker 29.8 |
| Contenedor `xmpp-prosody` | Servidor XMPP: reparte los mensajes entre agentes. Imagen `prosody/prosody` en `localhost:5222`, dominio `localhost` | — |
| Librerías de Python | Ver `requirements.txt`: SPADE (agentes), DEAP (algoritmo genético), NumPy, psutil | — |

## Arquitectura y flujo

```
        ┌───────────────────────────────────────────────────────┐
        │  Contenedor Docker: Prosody (servidor XMPP)           │
        │  localhost:5222 — todos los mensajes pasan por aquí   │
        └──────▲─────────────▲──────────────────▲───────────────┘
               │             │                  │
   1. orden    │             │ 2. launched      │ 3. started / result
   (función,   │             │    (PID)         │    (PID, resultado)
    genoma,    │             │                  │
    run_id)    │       ┌─────┴──────┐           │
        ┌──────┴────┐  │  SPAWNER   │     ┌─────┴──────────┐
        │  MONITOR  │  │  one-shot  │     │     HIJO       │
        │  (FSM)    │  │ (DEAP)     │     │ proceso propio │
        │           │  └─────┬──────┘     │ child_main.py  │
        └─────┬─────┘        │            └────────▲───────┘
              │              └─ lanza el proceso ──┘
              │
              └─ consulta al sistema operativo si el PID del hijo sigue vivo
```

Monitor y Spawners viven en el mismo proceso de Python. El Hijo es un proceso aparte y el servidor XMPP es un contenedor.

**Ciclo, repetido por cada función pendiente:**

1. **Monitor → Spawner:** el Monitor levanta un Spawner y le envía una orden con la función, un genoma base aleatorio y un `run_id` que identifica el intento.
2. **Spawner:** siembra una población alrededor del genoma base y corre DEAP (selección, cruza y mutación). Se queda con el mejor individuo.
3. **Spawner → Hijo:** lanza el hijo como proceso independiente (`python child_main.py`), avisa su PID al Monitor (`launched`) y se apaga.
4. **Hijo → Monitor:** el hijo conecta a XMPP, confirma su arranque (`started`), evalúa la función con su genoma, envía el resultado (`result`) y termina.
5. **Monitor:** mientras tanto vigila al hijo por mensajes y por el estado de su proceso, y emite un veredicto.

### Máquina de estados del Monitor

```
IDLE ──► SPAWNING ──► MONITORING ──► IDLE
             ▲              │
             └── reintento ─┘   (hijo muerto, colgado o que no arrancó)
```

| Estado | Qué hace |
|---|---|
| `IDLE` | Si quedan funciones pendientes pasa a `SPAWNING`; si no, imprime el resumen final (resultados, intentos y consumo) y se detiene |
| `SPAWNING` | Toma la siguiente función (o repite la actual en un reintento), levanta un Spawner y le envía la orden |
| `MONITORING` | Espera al hijo, lo vigila por PID y decide el veredicto |

### Veredictos de la supervisión

| Veredicto | Condición | Acción |
|---|---|---|
| `exito` | Llegó el mensaje `result` | Guarda el resultado |
| `muerto` | El proceso ya no existe y no llegó resultado, pasados `DEATH_GRACE` (2 s) | Reintenta |
| `colgado` | El proceso sigue vivo tras `CHILD_TIMEOUT` (60 s) sin resultado | Lo termina y reintenta |
| `sin_arranque` | Pasaron `START_TIMEOUT` (30 s) sin PID, o el proceso vive pero nunca se conectó | Reintenta |

Si se agotan los intentos de una función, el Monitor lo registra y continúa con las demás. Los mensajes de otro intento se descartan por `run_id`, y la hora de creación del proceso evita confundirlo con otro si el sistema reutiliza el PID.

### Mensajes (XMPP, cuerpo en JSON)

| Emisor → Receptor | Tipo | Contenido |
|---|---|---|
| Monitor → Spawner | `request` | `function`, `genome`, `reply_to`, `run_id` |
| Spawner → Monitor | `launched` | `run_id`, `pid`, `create_time` |
| Hijo → Monitor | `started` | `run_id`, `pid`, `create_time`, `function` |
| Hijo → Monitor | `result` | `run_id`, `function`, `goal`, `best_solution`, `best_value`, `known_optimum` |

## Estructura

```
Agents/
├── main.py                 # Punto de entrada: crea el Monitor y espera a que termine
├── child_main.py           # Punto de entrada del proceso hijo (lo lanza el Spawner, no se ejecuta a mano)
├── config.py               # Estados, servidor XMPP, funciones, timeouts, monitoreo
├── functions.py            # Funciones matemáticas a optimizar y genoma base aleatorio
├── genetic.py              # Algoritmo genético con DEAP: evolve_best_genome()
├── behaviors.py            # Comportamientos de laboratorio extensibles de los hijos
├── requirements.txt        # Dependencias de Python
├── agents/
│   ├── parent_agent.py     # Monitor: arma la máquina de estados
│   ├── states.py           # Estados IDLE, SPAWNING y MONITORING (supervisión; multi-hijo)
│   ├── supervision.py      # child_alive() / kill_child(): estado del proceso por PID
│   ├── spawner_agent.py    # Spawner: evoluciona el mejor individuo y lanza el proceso hijo
│   └── optimizer_agent.py  # Hijo: avisa su PID, comportamientos, valida y reporta
├── monitoring/             # Monitoreo de recursos (corre en paralelo al Monitor)
│   ├── behaviour.py        # Muestreo periódico
│   ├── collectors.py       # Colectores: sistema, proceso Python, hijos, Docker, estado de agentes
│   └── recorder.py         # Escritura del CSV y resumen
├── tools/
│   └── fault_injector.py   # Solo pruebas (--demo): mata o congela procesos hijo desde fuera
└── container-server/       # Servidor XMPP local
    ├── docker-compose.yml
    └── prosody.cfg.lua
```

## Puesta en marcha

Todos los comandos se ejecutan desde la carpeta `Agents/`. Los de PowerShell sirven en Windows; en Linux/macOS use los de bash.

### 1. Instalar dependencias

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Levantar el servidor XMPP (contenedor)

```bash
docker compose -f container-server/docker-compose.yml up -d
docker ps --filter name=xmpp-prosody
```

Debe aparecer `xmpp-prosody` con estado `Up`. Para ver sus logs:

```bash
docker compose -f container-server/docker-compose.yml logs -f
```

### 3. Arrancar los agentes

```bash
python main.py
```

Banderas útiles:

```bash
# Hasta 3 hijos concurrentes, modo demo (inyector permitido) y comportamientos de laboratorio
python main.py --children 3 --demo --behaviors low_profile,lab_artifact

# Entorno real (sin inyector): no pasar --demo
python main.py --children 2
```

| Bandera | Significado |
|---|---|
| `--children N` | Máximo de procesos hijo concurrentes (default 1). Con N>1 el monitor vigila varios a la vez. |
| `--demo` | Modo demo: se asume/permite el uso de `tools/fault_injector.py`. Sin esta bandera se trabaja contra el entorno real (EDR u otro). |
| `--behaviors lista` | Comportamientos de laboratorio separados por comas (ver `behaviors.py`). Ejemplo: `low_profile,lab_artifact,heartbeat`. |

El sistema procesa las funciones de `FUNCTIONS_TO_OPTIMIZE` (en `config.py`) y termina solo, imprimiendo los resultados, una tabla de intentos por hijo y el consumo de recursos.

### Comportamientos de los hijos (capa de laboratorio)

El módulo `behaviors.py` permite registrar comportamientos que el hijo ejecuta antes de validar el genoma. Están pensados para el laboratorio de evasión/persistencia de la tesis:

- Solo simulaciones inocuas (retardos, heartbeats, escritura de artefactos en `logs/lab_artifacts/`).
- **No** se incluyen técnicas reales de APT, persistencia o evasión de EDR.
- Para añadir uno nuevo: definir una función, decorarla con `@register("nombre")` y usarla con `--behaviors nombre`.

Comportamientos incluidos: `noop`, `low_profile`, `lab_artifact`, `heartbeat`.

### 4. Ver los logs

| Qué | Cómo |
|---|---|
| Salida del Monitor y los Spawners | Es la consola donde corre `python main.py`. Para guardarla además en un archivo, ver abajo |
| Logs de cada proceso hijo | Carpeta `logs/hijos/` (un archivo por hijo) |
| Métricas de consumo | `logs/metricas.csv` (una fila por muestra) |
| Logs del servidor XMPP | `docker compose -f container-server/docker-compose.yml logs -f` |

Ejecutar guardando la salida en `logs/ejecucion.log` y viéndola a la vez:

```powershell
New-Item -ItemType Directory -Force logs | Out-Null
python main.py 2>&1 | Tee-Object logs\ejecucion.log
```

```bash
mkdir -p logs
python main.py 2>&1 | tee logs/ejecucion.log
```

Ver los logs de los hijos:

```powershell
Get-Content logs\hijos\*.log
```

```bash
cat logs/hijos/*.log
```

### 5. Detener

```bash
docker compose -f container-server/docker-compose.yml down
```

## Configuración

Constantes en `config.py`:

| Constante | Significado | Valor |
|---|---|---|
| `XMPP_SERVER`, `PASSWORD` | Dominio XMPP y contraseña de las cuentas que crean los agentes (de laboratorio) | `localhost` |
| `FUNCTIONS_TO_OPTIMIZE` | Funciones que procesa el Monitor | `sphere`, `rastrigin`, `peaks` |
| `START_TIMEOUT` | Espera máxima a que el hijo arranque | 30 s |
| `CHILD_TIMEOUT` | Vida máxima de un hijo sin dar resultado | 60 s |
| `DEATH_GRACE` | Gracia tras detectar un proceso muerto | 2 s |
| `POLL_INTERVAL` | Cada cuánto se revisa el PID del hijo | 0.5 s |
| `MAX_ATTEMPTS` | Intentos máximos por función | 2 |
| `SPAWNER_TIMEOUT` | Espera del Spawner por la orden | 20 s |
| `METRICS_ENABLED`, `METRICS_INTERVAL` | Monitoreo de recursos y su periodo | activo, 0.5 s |
| `DOCKER_CONTAINER` | Contenedor que se incluye en el monitoreo | `xmpp-prosody` |

Variables de entorno opcionales: `AGENTES_START_TIMEOUT`, `AGENTES_CHILD_TIMEOUT`, `AGENTES_MAX_ATTEMPTS`, `AGENTES_METRICS_CSV` (ruta del CSV) y `AGENTES_CHILD_LOG_DIR` (carpeta de logs de los hijos).

Los parámetros del algoritmo genético están en `genetic.py` (`GA_PARAMS`: 100 generaciones, 40 individuos, 20 % de mutación aprox., cxpb/mutpb). La librería usada es DEAP (misma interfaz `evolve_best_genome`).

## Prueba de fallos

`tools/fault_injector.py` vigila los procesos hijo y los termina o congela desde fuera, sin modificar el código del proyecto. Sirve para comprobar la supervisión y los reintentos. En una terminal:

```bash
# termina el primer hijo de sphere y todos los de rastrigin
python tools/fault_injector.py --kill sphere:1 --kill rastrigin:all --duration 60
```

En otra terminal, mientras el inyector corre:

```bash
python main.py
```

Resultado esperado: el Monitor marca `MUERTO` al primer hijo de `sphere` y lo reintenta con éxito, y agota los 2 intentos de `rastrigin` antes de seguir con `peaks`.

Para un hijo colgado (con un timeout corto solo para la prueba):

```powershell
python tools/fault_injector.py --suspend peaks:1 --duration 90
$env:AGENTES_CHILD_TIMEOUT = 8; python main.py
```

```bash
python tools/fault_injector.py --suspend peaks:1 --duration 90 &
AGENTES_CHILD_TIMEOUT=8 python main.py
```

## Problemas frecuentes

- **El Monitor no puede conectar / `DisconnectedException`:** el contenedor no está arriba. Comprobar con `docker ps` y `docker compose ... logs`. En Windows, Docker Desktop debe estar iniciado.
- **`AuthenticationFailure`:** Prosody debe permitir el registro de cuentas (`allow_registration = true` en `container-server/prosody.cfg.lua`); los agentes se registran solos al arrancar.
- **Los logs de los hijos están vacíos o no existen:** un hijo que muere antes de escribir deja el log vacío; el veredicto `muerto` queda en la salida del Monitor.
- **No se muestra la salida de los hijos en la consola:** es normal. Cada hijo corre sin consola y su salida va a `logs/hijos/`.
