// baseline.c — asigna memoria mediante la funcion exportada de ntdll.dll
// Ruta convencional: kernel32 -> kernelbase -> ntdll -> syscall -> kernel
#include <windows.h>
#include <stdio.h>

typedef NTSTATUS (NTAPI *pNtAllocateVirtualMemory)(
    HANDLE, PVOID*, ULONG_PTR, PSIZE_T, ULONG, ULONG
);

int main(void) {
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    pNtAllocateVirtualMemory NtAlloc =
        (pNtAllocateVirtualMemory)GetProcAddress(ntdll, "NtAllocateVirtualMemory");

    PVOID base = NULL;
    SIZE_T size = 4096;
    NTSTATUS st = NtAlloc(GetCurrentProcess(), &base, 0, &size,
                          MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);

    printf("Baseline: status=0x%08X base=%p\n", st, base);
    if (base) VirtualFree(base, 0, MEM_RELEASE);
    return 0;
}