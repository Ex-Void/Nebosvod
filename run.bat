@echo off
chcp 65001 >nul
title Небосвод - сайт погоды
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [!] Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
  echo     и при установке отметьте "Add python.exe to PATH".
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo [!] Нужен Python 3.10 или новее. Сейчас установлен:
  %PY% --version
  pause
  exit /b 1
)

echo Запуск сайта... Браузер откроется автоматически.
%PY% app.py
echo.
echo Сервер остановлен.
pause
