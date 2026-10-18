@echo off
rem Pure ASCII on purpose, see jarvis.bat. UI lives in skills\setup_brain.py
chcp 65001 >nul
title Настройка умного режима Джарвиса
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Python environment not found: %~dp0.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m skills.setup_brain
