@echo off
rem ============================================================
rem  Handbook: установка и первый запуск
rem  Кладётся в корень проекта (рядом с app.py и requirements.txt).
rem  Ищет Python 3.10+, создаёт .venv, ставит зависимости, запускает.
rem  setup.bat --no-run   только установить, без запуска
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Handbook - установка

set "NORUN=0"
if /i "%~1"=="--no-run" set "NORUN=1"

if not exist "app.py" goto noproject
if not exist "requirements.txt" goto noproject

echo [1/4] Ищу Python 3.10 или новее...
set "PY="
call :chk py -3
if defined PY goto found
call :chk python
if defined PY goto found
call :chk python3
if defined PY goto found
rem Python стоит, но не прописан в PATH: смотрим обычные места установки
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do call :chk "%%~D\python.exe"
if defined PY goto found
goto nopy

:chk
%* -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set PY=%*
exit /b 0

:found
echo      Найден:
%PY% --version
echo.

if exist ".venv\Scripts\python.exe" goto havevenv
echo [2/4] Создаю виртуальное окружение .venv...
%PY% -m venv .venv
if errorlevel 1 goto fail
goto venvok
:havevenv
echo [2/4] Окружение .venv уже есть.
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto badvenv
:venvok
echo.

fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if not errorlevel 1 goto depsok
echo [3/4] Ставлю зависимости, это может занять несколько минут...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
copy /y requirements.txt ".venv\requirements.installed" >nul
goto depsdone
:depsok
echo [3/4] Зависимости уже установлены.
:depsdone
echo.

echo [4/4] Проверяю Tesseract, он нужен только для распознавания сканов...
set "TESS="
where tesseract >nul 2>&1
if not errorlevel 1 set "TESS=1"
if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" set "TESS=1"
if defined TESSERACT_CMD set "TESS=1"
if defined TESS goto tessok
echo      Tesseract не найден. Это не ошибка: документы с текстом читаются как обычно,
echo      а страницы-сканы будут показываться картинкой без поиска по ним.
echo      Чтобы читать сканы: https://github.com/UB-Mannheim/tesseract/wiki
echo      При установке отметь Russian в Additional language data.
goto tessdone
:tessok
echo      Tesseract найден.
:tessdone
echo.

echo Установка завершена.
if "%NORUN%"=="1" goto done
echo Запускаю Handbook...
echo.
call "%~dp0run.bat"
goto done

:noproject
echo Не вижу app.py и requirements.txt рядом со скриптом.
echo Положи setup.bat и run.bat в корень проекта Handbook.
goto fail

:nopy
echo.
echo Python 3.10 или новее не найден.
echo Скачай с https://www.python.org/downloads/windows/
echo При установке поставь галочку "Add python.exe to PATH" и запусти setup.bat снова.
goto fail

:badvenv
echo.
echo Папка .venv повреждена или создана на другом компьютере.
echo Удали папку .venv вручную и запусти setup.bat снова.
goto fail

:pipfail
echo.
echo Не удалось установить зависимости. Проверь интернет и сообщение pip выше.
goto fail

:fail
echo.
pause
exit /b 1

:done
endlocal
exit /b 0
