"""One resident per session, and a way to knock on its window.

Two named kernel objects:
  a mutex, so a second launch bows out instead of fighting for the device;
  an event, so `--show` can surface the window of a resident that is running
  hidden (the Arkanoid supervisor starts it with --no-tray and no window).
"""
import ctypes
import threading
import time

MUTEX_NAME = "Local\\QuadcastLight.Gui"
SHOW_EVENT_NAME = "Local\\QuadcastLight.ShowWindow"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

_mutex = None


def acquire():
    """True if this process is now the resident; False if one already runs."""
    global _mutex
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError()
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex = handle
    return True


def request_show(timeout_seconds=8.0, poll_interval=0.25):
    """Ask a running resident to show its window. False if nobody answered.

    Waits rather than checking once: the supervisor can fire `--show` while the
    resident is still starting up.
    """
    kernel32 = ctypes.windll.kernel32
    deadline = time.monotonic() + timeout_seconds
    while True:
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if handle:
            try:
                kernel32.SetEvent(handle)
            finally:
                kernel32.CloseHandle(handle)
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


def listen_for_show(callback):
    """Run `callback` whenever someone calls request_show().

    Returns the event handle, which must stay referenced for the name to stay
    registered. The callback runs on a worker thread; marshal it yourself.
    """
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    if not handle:
        return None

    def worker():
        while True:
            if kernel32.WaitForSingleObject(handle, INFINITE) != WAIT_OBJECT_0:
                return
            try:
                callback()
            except RuntimeError:
                return

    threading.Thread(target=worker, name="ShowWindowListener", daemon=True).start()
    return handle
