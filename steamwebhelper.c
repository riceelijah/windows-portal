// steamwebhelper.exe stand-in: runs steamwebhelper_real.exe with --in-process-gpu appended.
#include <windows.h>
void start(void) {
    static WCHAR exe[MAX_PATH], cmd[32768];
    DWORD n = GetModuleFileNameW(0, exe, MAX_PATH);
    lstrcpyW(exe + n - 4, L"_real.exe");
    WCHAR *a = GetCommandLineW();  // skip argv[0]
    if (*a == L'"') { a++; while (*a && *a != L'"') a++; if (*a) a++; } else while (*a && *a != L' ') a++;
    cmd[0] = L'"'; lstrcpyW(cmd + 1, exe); lstrcatW(cmd, L"\""); lstrcatW(cmd, a); lstrcatW(cmd, L" --in-process-gpu");
    HANDLE job = CreateJobObjectW(0, 0);  // child dies with us when Steam kills the webhelper
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION li = {0};
    li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    SetInformationJobObject(job, JobObjectExtendedLimitInformation, &li, sizeof li);
    STARTUPINFOW si = {sizeof si}; PROCESS_INFORMATION pi;
    if (!CreateProcessW(exe, cmd, 0, 0, TRUE, CREATE_SUSPENDED, 0, 0, &si, &pi)) ExitProcess(1);
    AssignProcessToJobObject(job, pi.hProcess); ResumeThread(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD rc = 1; GetExitCodeProcess(pi.hProcess, &rc);
    ExitProcess(rc);
}
