# Direct Syscalls + Process Injection

## Objetivo

Este proyecto implementa y documenta una prueba de concepto (PoC) que combina dos técnicas:

1. **Direct Syscalls**: ejecutar la instrucción `syscall` desde un stub propio ubicado en el módulo del ejecutable, sin invocar la función exportada de `ntdll.dll` para esa operación.
2. **Process Injection**: inyectar un shellcode que ejecuta el syscall directo dentro de un proceso remoto (por ejemplo, `mspaint.exe`), de modo que la instrucción `syscall` se ejecute en el contexto de otro proceso.

El objetivo es **describir el mecanismo, la estructura del proyecto y los comandos necesarios** para compilar, ejecutar y observar ambas variantes. Esta PoC **no evalúa EDRs reales, no mide tasas de detección y no pretende demostrar evasión**. Su alcance es exclusivamente el estudio del mecanismo de invocación y la observación de las evidencias en modo usuario.

## Estructura del proyecto

```text
BEHAVIOUR-EDR/
├── README.md
├── src/
│   ├── baseline.c           # Ruta convencional: ntdll!NtAllocateVirtualMemory
│   ├── direct_syscall.c     # Direct Syscall clásico (stub propio + SSN extraído)
│   ├── injector.c           # Direct Syscall + Process Injection (loader)
│   └── syscall_stub.asm     # Stub en ensamblador con la instrucción syscall
├── build/
│   └── build_windows.bat    # Script de compilación para x64
├── out/                     # Binarios y
```

Los archivos generados en `out/` no deben versionarse, salvo que el proyecto tenga una razón documentada para conservarlos.

## Requisitos

- **Windows 10 de 64 bits (x64)**. Es el entorno utilizado en el experimento. Las versiones exactas del sistema operativo deben registrarse junto con las evidencias de cada ejecución.
- **Visual Studio** con las herramientas de compilación de C/C++ para x64.
- **Herramientas MASM** (`ml64.exe`) para ensamblar el stub.
- **x64 Native Tools Command Prompt for VS** para compilar y ejecutar.
- **WinDbg** para inspeccionar el desensamblado y las pilas de llamadas.
- Para la variante de inyección: un proceso objetivo abierto (por ejemplo, `mspaint.exe`).

## Compilación

Abre **x64 Native Tools Command Prompt for VS** y, desde el directorio raíz del proyecto, ejecuta:

```bat
build\build_windows.bat
dir out
```

El script debe generar los siguientes ejecutables en `out\`:

- `out\baseline.exe`
- `out\direct_syscall.exe`
- `out\injector.exe`

Según la configuración de compilación, también pueden generarse archivos de símbolos y objetos, como `.pdb` y `.obj`.

### Detalle de los pasos de compilación

El script `build_windows.bat` ejecuta cuatro pasos:

1. **`[1/4]` Compilación del baseline**:

   ```bat
   cl /nologo /O2 src\baseline.c /Fe:out\baseline.exe
   ```

2. **`[2/4]` Ensamblado del stub de syscall**:

   ```bat
   ml64 /c /nologo /Foout\syscall_stub.obj src\syscall_stub.asm
   ```

3. **`[3/4]` Compilación del Direct Syscall clásico**:

   ```bat
   cl /nologo /O2 src\direct_syscall.c out\syscall_stub.obj /Fe:out\direct_syscall.exe
   ```

4. **`[4/4]` Compilación del inyector combinado**:

   ```bat
   cl /nologo /O2 src\injector.c /Fe:out\injector.exe
   ```

## Ejecución

### 1. Baseline (ruta convencional)

```bat
out\baseline.exe
```

Este programa invoca `NtAllocateVirtualMemory` a través de la función exportada de `ntdll.dll`. La llamada atraviesa el stub de `ntdll.dll`, que prepara los parámetros y ejecuta la transición al kernel.

### 2. Direct Syscall clásico

```bat
out\direct_syscall.exe
```

Este programa extrae el SSN del stub de `ntdll!NtAllocateVirtualMemory`, lo inyecta en el stub propio (`syscall_stub.asm`) y ejecuta la instrucción `syscall` desde el módulo del ejecutable, sin invocar la función exportada de `ntdll.dll`.

### 3. Direct Syscall + Process Injection (combinado)

1. Abre el proceso objetivo (por ejemplo, Paint):

   ```text
   Menú Inicio → Paint
   ```

2. Ejecuta el inyector desde la consola x64:

   ```bat
   out\injector.exe mspaint.exe
   ```

El inyector realiza los siguientes pasos:

1. Extrae el SSN del stub de `ntdll!NtAllocateVirtualMemory` (misma lógica que `direct_syscall.c`).
2. Parchea el SSN en la plantilla de shellcode (`shellcode_template`) en el offset 6.
3. Localiza el PID del proceso objetivo (`FindProcessId`).
4. Abre el proceso con `OpenProcess` (`PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD`).
5. Reserva memoria remota con `VirtualAllocEx` (`PAGE_EXECUTE_READWRITE`).
6. Escribe el shellcode parcheado con `WriteProcessMemory`.
7. Crea un hilo remoto con `CreateRemoteThread` que ejecuta el shellcode.

El shellcode inyectado ejecuta:

```asm
mov r10, rcx
mov eax, <SSN parcheado>
syscall
ret
```

Por tanto, la instrucción `syscall` se ejecuta **dentro del proceso objetivo**, no en el proceso del inyector.

## Salidas esperadas (referencia)

Las siguientes salidas son ilustrativas. Las direcciones de memoria, los bytes del stub y el número de servicio del sistema (SSN) dependen del entorno y deben verificarse con los resultados reales.

**Baseline:**

```text
Baseline: status=0x00000000 base=0x000001XXXXXXXXXX
```

**Direct Syscall clásico:**

```text
Stub bytes: 4C 8B D1 B8 XX XX XX XX
Extracted SSN: 0x2X
Direct: status=0x00000000 base=0x000001XXXXXXXXXX
```

**Inyector combinado:**

```text
SSN extraido: 0x2X
Shellcode parcheado con SSN 0x2X en offset 6
Proceso objetivo: mspaint.exe (PID XXXX)
Inyeccion de Direct Syscall completada en mspaint.exe (PID XXXX)
```

## Qué observar en WinDbg

Durante la depuración, registra los siguientes elementos:

- **Bytes del stub:** inspecciona los bytes de `ntdll!NtAllocateVirtualMemory` impresos por el binario o consultados en WinDbg.
- **SSN extraído:** registra el valor obtenido en el entorno probado y verifica que corresponda al stub analizado.
- **Breakpoint en `ntdll`:** comprueba si se activa un punto de interrupción en `ntdll!NtAllocateVirtualMemory` durante la ejecución de `direct_syscall.exe` y de `injector.exe`.
- **Ubicación de `syscall`:** identifica el módulo que contiene la instrucción mediante el desensamblado. En la compilación documentada, la instrucción `syscall` del stub propio se encontró en `DirectSyscall+9`. Este desplazamiento es específico de esa compilación y debe verificarse nuevamente si cambia el código.
- **Pila de llamadas:** utiliza `k` para observar los frames presentes en el punto de captura. La presencia o ausencia de frames depende del punto de interrupción, del momento de la captura y de la forma en que se representa la pila.
- **Resultado de la operación:** compara el estado devuelto y la dirección base asignada.
- **Llamadas internas del runtime:** distingue la llamada estudiada de las operaciones que el runtime de MSVC pueda realizar por separado.

Para las capturas de WinDbg, registra el contexto exacto de cada breakpoint y evita comparar pilas obtenidas en puntos de ejecución diferentes.

## Evidencias

Guarda las transcripciones completas en el directorio `observacion/`:

| Archivo | Evidencia |
|---|---|
| `salida_baseline.txt` | Salida completa de la ejecución convencional. |
| `salida_direct.txt` | Salida completa de la ejecución directa. |
| `windbg_baseline.txt` | Inspección de la ruta convencional en WinDbg. |
| `windbg_direct_positivo.txt` | Captura con el breakpoint en el stub propio. |
| `windbg_direct_negativo.txt` | Captura del breakpoint en `ntdll` durante la ejecución del programa directo, asociado en el experimento a una llamada del CRT. |
