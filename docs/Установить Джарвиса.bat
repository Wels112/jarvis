@echo off
chcp 65001 >nul
title Установка Джарвиса
echo.
echo   Сейчас начнётся установка голосового помощника Джарвиса.
echo   Это займёт около 15 минут. Понадобится интернет.
echo.
echo   Если Windows спросит разрешение — нажмите "Да".
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Wels112/jarvis/main/install.ps1 | iex"
echo.
echo   Если выше написано "Готово" — установка завершена.
echo   На рабочем столе появились ярлыки "Джарвис" и "Планировщик".
echo.
pause
