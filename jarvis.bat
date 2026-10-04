@echo off
rem Keep this file pure ASCII: cmd.exe re-reads a .bat after "chcp 65001"
rem and misparses any multibyte (Cyrillic) bytes that follow.
chcp 65001 >nul
title Jarvis
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [Jarvis] Python environment not found: %~dp0.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u jarvis.py %*
if errorlevel 1 pause
