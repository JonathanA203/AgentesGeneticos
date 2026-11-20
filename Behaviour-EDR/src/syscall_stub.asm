; syscall_stub.asm — stub de syscall directo (x64 MASM)
; La instruccion syscall vive en el modulo del ejecutable, no en ntdll.dll
; Requiere MASM (ml64.exe) del toolchain de Visual Studio
option prologue:none
option epilogue:none

.data
    g_ssn DWORD 0

.code
    DirectSyscall PROC
        mov r10, rcx
        mov eax, g_ssn
        syscall
        ret
    DirectSyscall ENDP

    SetSSN PROC
        mov g_ssn, ecx
        ret
    SetSSN ENDP
END