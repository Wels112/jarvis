@echo off
rem Pure ASCII on purpose, see jarvis.bat
chcp 65001 >nul
title Jarvis - voice
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Python environment not found: %~dp0.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u docs\voices.py
pause
