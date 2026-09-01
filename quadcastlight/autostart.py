"""Start with Windows, via a launcher in the user's Startup folder.

A .cmd in Startup rather than a Run registry value: it is visible, the user can
delete it by hand, and it needs no elevation. The launcher points at
miclight_gui.pyw, which stays as an entry point so existing installs keep
working after the package restructure.
"""
import os
import sys

LAUNCHER_NAME = "QuadcastLight.cmd"
ENTRY_SCRIPT = "miclight_gui.pyw"


def project_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launcher_path():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not available; the Startup folder cannot be located.")
    return os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", LAUNCHER_NAME
    )


def interpreter():
    """The windowed interpreter to launch with, preferring the project venv."""
    candidates = [
        os.path.join(project_dir(), ".venv", "Scripts", "pythonw.exe"),
        os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
        sys.executable,
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def launch_command():
    """The command that starts this app, as a list.

    A frozen build has no interpreter and no .pyw beside it: sys.executable is
    the application itself. Both the Startup launcher and the tray's restart go
    through here so neither has to know which build it is running in.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [interpreter(), os.path.join(project_dir(), ENTRY_SCRIPT)]


def enabled():
    try:
        return os.path.isfile(launcher_path())
    except RuntimeError:
        return False


def set_enabled(value):
    path = launcher_path()
    if not value:
        if os.path.exists(path):
            os.remove(path)
        return
    command = " ".join(f'"{part}"' for part in launch_command())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\r\n") as launcher:
        launcher.write(f'@start "" {command}\n')
