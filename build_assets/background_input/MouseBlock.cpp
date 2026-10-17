#define WIN32_LEAN_AND_MEAN
#include <windows.h>

// 与桌面分身相同，WH_MOUSE 在应用预处理前拦截输入队列，
// SendMessage / PostMessage 不经过此钩子。外部进程要求原生 DLL 回调。
namespace {
constexpr LONG MaxOwners = 32;
constexpr LONG MaxWindows = 128;
struct Target { HWND window; DWORD process; DWORD thread; };
struct Owner {
    volatile LONG process;
    FILETIME created;
    volatile LONG count;
    volatile LONG generation;
    Target targets[MaxWindows];
};
#pragma data_seg(".lcamouse")
Owner owners[MaxOwners] = {};
#pragma data_seg()
#pragma comment(linker, "/SECTION:.lcamouse,RWS")

HMODULE module = nullptr;
HHOOK hook = nullptr;
LONG slot = -1;

bool IsOwnerAlive(const Owner& owner, DWORD process) {
    HANDLE handle = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, process);
    if (!handle) return false;
    FILETIME created, exited, kernel, user;
    bool alive = WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        && GetProcessTimes(handle, &created, &exited, &kernel, &user)
        && CompareFileTime(&created, &owner.created) == 0;
    CloseHandle(handle);
    return alive;
}

bool IsProcessRunning(DWORD process) {
    HANDLE handle = OpenProcess(SYNCHRONIZE, FALSE, process);
    if (!handle) return GetLastError() == ERROR_ACCESS_DENIED;
    bool running = WaitForSingleObject(handle, 0) == WAIT_TIMEOUT;
    CloseHandle(handle);
    return running;
}

LRESULT CALLBACK MouseProc(int code, WPARAM wparam, LPARAM lparam) {
    if (code >= 0 && lparam) {
        HWND receiver = reinterpret_cast<MOUSEHOOKSTRUCT*>(lparam)->hwnd;
        for (const Owner& owner : owners) {
            LONG process = owner.process;
            LONG count = owner.count;
            LONG generation = owner.generation;
            if (generation & 1) continue;
            if (process <= 0 || count < 0 || count > MaxWindows) continue;
            for (LONG index = 0; index < count; ++index) {
                const Target target = owner.targets[index];
                if (!target.window || (receiver != target.window && !IsChild(target.window, receiver))) continue;
                DWORD pid = 0;
                DWORD tid = GetWindowThreadProcessId(target.window, &pid);
                if (pid == target.process && tid == target.thread
                    && IsOwnerAlive(owner, process) && owner.process == process
                    && owner.generation == generation) return 1;
            }
        }
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}

DWORD IntegrityLevel(HANDLE process, DWORD& level) {
    HANDLE token = nullptr;
    if (!OpenProcessToken(process, TOKEN_QUERY, &token)) return GetLastError();
    BYTE buffer[512];
    DWORD size = 0;
    DWORD error = ERROR_SUCCESS;
    if (!GetTokenInformation(token, TokenIntegrityLevel, buffer, sizeof(buffer), &size)) {
        error = GetLastError();
    } else {
        PSID sid = reinterpret_cast<TOKEN_MANDATORY_LABEL*>(buffer)->Label.Sid;
        level = *GetSidSubAuthority(sid, *GetSidSubAuthorityCount(sid) - 1);
    }
    CloseHandle(token);
    return error;
}

DWORD ValidateTargets(const HWND* windows, LONG count, Target* targets) {
    if (!windows || count <= 0 || count > MaxWindows) return ERROR_INVALID_PARAMETER;
    WCHAR desktop[256];
    DWORD required = 0;
    if (!GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()), UOI_NAME,
        desktop, sizeof(desktop), &required)) return GetLastError();
    DWORD currentLevel = 0;
    DWORD error = IntegrityLevel(GetCurrentProcess(), currentLevel);
    if (error) return error;
    for (LONG index = 0; index < count; ++index) {
        DWORD process = 0;
        DWORD thread = GetWindowThreadProcessId(windows[index], &process);
        if (!thread || !IsWindow(windows[index])) return ERROR_INVALID_WINDOW_HANDLE;
        WCHAR targetDesktop[256];
        if (!GetUserObjectInformationW(GetThreadDesktop(thread), UOI_NAME,
            targetDesktop, sizeof(targetDesktop), &required)) return GetLastError();
        if (lstrcmpW(desktop, targetDesktop)) return ERROR_ACCESS_DENIED;
        HANDLE handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, process);
        if (!handle) return GetLastError();
        DWORD targetLevel = 0;
        error = IntegrityLevel(handle, targetLevel);
        CloseHandle(handle);
        if (error) return error;
        if (targetLevel > currentLevel) return ERROR_ACCESS_DENIED;
        targets[index] = {windows[index], process, thread};
    }
    return ERROR_SUCCESS;
}

void Publish(const Target* targets, LONG count) {
    Owner& owner = owners[slot];
    InterlockedIncrement(&owner.generation);
    InterlockedExchange(&owner.count, 0);
    CopyMemory(owner.targets, targets, sizeof(Target) * count);
    InterlockedExchange(&owner.count, count);
    InterlockedIncrement(&owner.generation);
}
}

extern "C" __declspec(dllexport) DWORD StartMouseBlock(const HWND* windows, LONG count) {
    if (hook || slot >= 0) return ERROR_ALREADY_EXISTS;
    Target targets[MaxWindows];
    DWORD error = ValidateTargets(windows, count, targets);
    if (error) return error;
    DWORD process = GetCurrentProcessId();
    for (LONG index = 0; index < MaxOwners; ++index) {
        LONG previous = owners[index].process;
        if ((previous < 0 && IsProcessRunning(static_cast<DWORD>(-previous)))
            || (previous > 0 && IsOwnerAlive(owners[index], previous))) continue;
        if (InterlockedCompareExchange(&owners[index].process, -static_cast<LONG>(process), previous) != previous) continue;
        slot = index;
        InterlockedExchange(&owners[slot].generation, 0);
        FILETIME exited, kernel, user;
        if (!GetProcessTimes(GetCurrentProcess(), &owners[slot].created, &exited, &kernel, &user)) {
            error = GetLastError();
            InterlockedExchange(&owners[slot].process, 0);
            slot = -1;
            return error;
        }
        Publish(targets, count);
        InterlockedExchange(&owners[slot].process, static_cast<LONG>(process));
        hook = SetWindowsHookExW(WH_MOUSE, MouseProc, module, 0);
        if (!hook) {
            error = GetLastError();
            InterlockedExchange(&owners[slot].count, 0);
            InterlockedExchange(&owners[slot].process, 0);
            slot = -1;
            return error;
        }
        return ERROR_SUCCESS;
    }
    return ERROR_NOT_ENOUGH_QUOTA;
}

extern "C" __declspec(dllexport) DWORD UpdateMouseBlock(const HWND* windows, LONG count) {
    if (!hook || slot < 0) return ERROR_INVALID_HANDLE;
    Target targets[MaxWindows];
    DWORD error = ValidateTargets(windows, count, targets);
    if (!error) Publish(targets, count);
    return error;
}

extern "C" __declspec(dllexport) DWORD StopMouseBlock() {
    if (hook && !UnhookWindowsHookEx(hook)) {
        DWORD error = GetLastError();
        // 安装线程退出后 Windows 已移除钩子，仍须清除共享目标和 DLL 引用。
        if (error != ERROR_INVALID_HOOK_HANDLE) return error;
    }
    hook = nullptr;
    if (slot >= 0) {
        InterlockedExchange(&owners[slot].count, 0);
        InterlockedExchange(&owners[slot].process, 0);
        slot = -1;
    }
    return ERROR_SUCCESS;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
