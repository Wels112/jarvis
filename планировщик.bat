@echo off
rem Pure ASCII on purpose, see jarvis.bat. Opens the weekly planner window (skills\planner.py)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo [Jarvis] Python environment not found: %~dp0.venv
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m skills.planner
