// Electron exports the Node API from its executable, whose packaged name differs
// from node.exe. Resolve that delayed import against the current host image.
// https://www.electronjs.org/docs/latest/tutorial/using-native-node-modules
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <delayimp.h>
#include <cstring>

static FARPROC WINAPI electronHost(unsigned event, DelayLoadInfo* import) {
  if (event == dliNotePreLoadLibrary && _stricmp(import->szDll, "node.exe") == 0)
    return reinterpret_cast<FARPROC>(GetModuleHandleW(nullptr));
  return nullptr;
}

decltype(__pfnDliNotifyHook2) __pfnDliNotifyHook2 = electronHost;
