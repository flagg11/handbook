@echo off
rem ============================================================
rem  Handbook: install and first start.
rem  Put into the project root, next to app.py and requirements.txt.
rem  Finds Python 3.10+, creates .venv, installs packages, starts app.
rem  setup.bat --no-run   install only, do not start
rem  (this file is ASCII only on purpose: cmd breaks on UTF-8 text)
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Handbook setup

set "NORUN=0"
if /i "%~1"=="--no-run" set "NORUN=1"

if not exist "app.py" goto noproject
if not exist "requirements.txt" goto noproject

echo [1/4] Looking for Python 3.10 or newer...
set "PY="
call :chk py -3
if defined PY goto found
call :chk py -3.13
if defined PY goto found
call :chk py -3.12
if defined PY goto found
call :chk py -3.11
if defined PY goto found
call :chk py -3.10
if defined PY goto found
call :chk python
if defined PY goto found
call :chk python3
if defined PY goto found
rem Python is installed but not in PATH: look in the usual places
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do call :chk "%%~D\python.exe"
if defined PY goto found
goto nopy

:chk
%* -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set PY=%*
exit /b 0

:found
echo      Found:
%PY% --version
echo.

if exist ".venv\Scripts\python.exe" goto havevenv
echo [2/4] Creating virtual environment .venv ...
%PY% -m venv .venv
if errorlevel 1 goto fail
goto venvok
:havevenv
echo [2/4] Virtual environment .venv already exists.
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto badvenv
:venvok
echo.

fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if not errorlevel 1 goto depsok
echo [3/4] Installing packages, this may take a few minutes...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
copy /y requirements.txt ".venv\requirements.installed" >nul
goto depsdone
:depsok
echo [3/4] Packages are already installed.
:depsdone
echo.

echo [4/4] Checking Tesseract (needed only for scanned pages)...
set "TESS="
where tesseract >nul 2>&1
if not errorlevel 1 set "TESS=1"
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS=1"
if defined TESSERACT_CMD set "TESS=1"
if defined TESS goto tessok
echo      Tesseract not found. This is not an error: text documents work as usual,
echo      scanned pages are shown as images and are not searchable.
echo      To read scans install https://github.com/UB-Mannheim/tesseract/wiki
echo      and tick Russian in Additional language data.
goto tessdone
:tessok
echo      Tesseract found.
:tessdone
echo.

echo Setup finished.
if "%NORUN%"=="1" goto done
echo Starting Handbook...
echo.
call "%~dp0run.bat"
goto done

:noproject
echo app.py and requirements.txt are not next to this script.
echo Put setup.bat and run.bat into the Handbook project root.
goto fail

:nopy
echo.
echo Python 3.10 or newer was not found.
echo Download it from https://www.python.org/downloads/windows/
echo During install tick "Add python.exe to PATH", then run setup.bat again.
goto fail

:badvenv
echo.
echo Folder .venv is broken or was created on another computer.
echo Delete the .venv folder by hand and run setup.bat again.
goto fail

:pipfail
echo.
echo Could not install packages. Check the internet connection and the pip message above.
goto fail

:fail
echo.
pause
exit /b 1

:done
endlocal
exit /b 0
