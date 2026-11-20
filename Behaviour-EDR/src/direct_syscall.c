// direct_syscall.c — resuelve el SSN desde el stub de ntdll y llama a DirectSyscall
// Ruta directa: direct_syscall.exe -> syscall -> kernel (sin ntdll en la pila)
#include <windows.h>
#include <stdio.h>

extern NTSTATUS DirectSyscall(HANDLE, PVOID*, ULONG_PTR, PSIZE_T, ULONG, ULONG);
extern void SetSSN(DWORD);

// Firma esperada del stub en ntdll (Windows 10 sin EDR):
//   4C 8B D1        mov r10, rcx
//   B8 XX XX XX XX  mov eax, SSN
//   ...             syscall
static DWORD ExtractSSN(void) {
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    BYTE *fn = (BYTE*)GetProcAddress(ntdll, "NtAllocateVirtualMemory");

    printf("Stub bytes: ");
    for (int i = 0; i < 8; i++) printf("%02X ", fn[i]);
    printf("\n");

    // Validar firma antes de extraer
    if (!(fn[0] == 0x4C && fn[1] == 0x8B && fn[2] == 0xD1 && fn[3] == 0xB8)) {
        printf("ERROR: firma del stub inesperada. Posible hook o version distinta.\n");
        return 0;
    }
    return *(DWORD*)(fn + 4);
}

int main(void) {
    DWORD ssn = ExtractSSN();
    if (ssn == 0) {
        printf("No se pudo extraer SSN, abortando.\n");
        return 1;
    }
    printf("Extracted SSN: 0x%X\n", ssn);
    SetSSN(ssn);

    PVOID base = NULL;
    SIZE_T size = 4096;
    NTSTATUS st = DirectSyscall(GetCurrentProcess(), &base, 0, &size,
                                MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);

    printf("Direct: status=0x%08X base=%p\n", st, base);
    if (base) VirtualFree(base, 0, MEM_RELEASE);
    return 0;
}