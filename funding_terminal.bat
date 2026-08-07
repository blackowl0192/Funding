@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8000"

:menu
cls
echo =================================
echo Funding Arbitrage Terminal
echo =================================
echo 1. Start
echo 2. Stop
echo 3. Restart
echo 4. Status
echo 5. Open Browser
echo 6. View Log
echo 0. Exit
echo.
set /p choice=Select option: 

if "%choice%"=="1" goto start_app
if "%choice%"=="2" goto stop_app
if "%choice%"=="3" goto restart_app
if "%choice%"=="4" goto status_app
if "%choice%"=="5" goto open_browser
if "%choice%"=="6" goto view_log
if "%choice%"=="0" exit /b 0
goto menu

:check_python
if not exist "%PYTHON_EXE%" (
    echo ERROR: Virtual environment not found.
    echo Run scripts\setup_local.ps1 first.
    pause
    goto menu
)
exit /b 0

:start_app
call :check_python
"%PYTHON_EXE%" scripts\runtime_manager.py start --open-browser
pause
goto menu

:stop_app
call :check_python
"%PYTHON_EXE%" scripts\runtime_manager.py stop
pause
goto menu

:restart_app
call :check_python
"%PYTHON_EXE%" scripts\runtime_manager.py restart --open-browser
pause
goto menu

:status_app
call :check_python
"%PYTHON_EXE%" scripts\runtime_manager.py status
pause
goto menu

:open_browser
start "" "%APP_URL%"
goto menu

:view_log
if exist "logs\funding_terminal.log" (
    notepad "logs\funding_terminal.log"
) else (
    echo Log file does not exist yet.
    pause
)
goto menu

