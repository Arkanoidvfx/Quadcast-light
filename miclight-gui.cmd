@echo off
pushd "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "miclight_gui.pyw" %*
) else (
    start "" ".venv\Scripts\python.exe" "miclight_gui.pyw" %*
)
popd
