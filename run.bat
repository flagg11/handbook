@echo off
rem ============================================================
rem  Handbook: start. Run setup.bat once before the first start.
rem  Network settings (HANDBOOK_HOST, HANDBOOK_PASSWORD, ...) can be
rem  put as "set" lines into handbook.env.bat next to this script.
rem  HANDBOOK_NO_BROWSER=1 turns off opening the browser.
rem  (ASCII only on purpose: cmd breaks on UTF-8 text)
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Handbook

set PYTHONUTF8=1
if exist "handbook.env.bat" call "handbook.env.bat"
if not defined HANDBOOK_PORT set "HANDBOOK_PORT=5000"

if not exist ".venv\Scripts\python.exe" goto noenv

if defined HANDBOOK_NO_BROWSER goto begin
if defined HANDBOOK_HOST if not "%HANDBOOK_HOST%"=="127.0.0.1" goto begin
start "" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:%HANDBOOK_PORT%"

:begin
echo Handbook is starting: http://127.0.0.1:%HANDBOOK_PORT%
echo To stop press Ctrl+C or close this window.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto crash
exit /b 0

:noenv
echo Virtual environment not found. Run setup.bat first.
echo.
pause
exit /b 1

:crash
echo.
echo The server stopped with an error, see the message above.
pause
exit /b 1
