@echo off
rem Pure ASCII on purpose, see jarvis.bat. Russian messages live in skills\update.py
chcp 65001 >nul
title Jarvis - update
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Python environment not found: %~dp0.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u skills\update.py --apply
pause
