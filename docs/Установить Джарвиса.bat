@echo off
chcp 65001 >nul
title Установка Джарвиса
echo.
echo   Сейчас начнётся установка голосового помощника Джарвиса.
echo   Это займёт около 15 минут. Нужен интернет.
echo.
echo   Если на компьютере нет Python, установщик поставит его сам.
echo   Если Windows спросит разрешение — нажмите "Да".
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Join-Path $env:TEMP 'jarvis-install.ps1'; try { Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/Wels112/jarvis/main/install.ps1' -OutFile $t } catch { Write-Host '    Не удалось скачать установщик — проверьте интернет.' -ForegroundColor Yellow; exit 1 }; & $t -Simple; Remove-Item $t -Force -ErrorAction SilentlyContinue"
echo.
echo   Если выше написано "Готово" — установка завершена.
echo   На рабочем столе появятся ярлыки "Джарвис", "Планировщик"
echo   и "Настройка умного режима".
echo.
echo   Это окно можно закрыть.
pause
