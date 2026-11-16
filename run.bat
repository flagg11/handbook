@echo off
rem ============================================================
rem  Handbook: запуск. Сначала один раз нужен setup.bat.
rem  Настройки сети (HANDBOOK_HOST, HANDBOOK_PASSWORD и т.д.)
rem  можно записать строками set в файл handbook.env.bat рядом
rem  с этим скриптом, он подхватится сам.
rem  HANDBOOK_NO_BROWSER=1 отключает открытие браузера.
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Handbook

set PYTHONUTF8=1
if exist "handbook.env.bat" call "handbook.env.bat"
if not defined HANDBOOK_PORT set "HANDBOOK_PORT=5000"

if not exist ".venv\Scripts\python.exe" goto noenv

if defined HANDBOOK_NO_BROWSER goto start
if defined HANDBOOK_HOST if not "%HANDBOOK_HOST%"=="127.0.0.1" goto start
start "" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:%HANDBOOK_PORT%"

:start
echo Handbook запускается: http://127.0.0.1:%HANDBOOK_PORT%
echo Остановить: Ctrl+C или закрыть это окно.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto crash
exit /b 0

:noenv
echo Окружение не найдено. Сначала запусти setup.bat.
echo.
pause
exit /b 1

:crash
echo.
echo Сервер остановился с ошибкой, см. сообщение выше.
pause
exit /b 1
