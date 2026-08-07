@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8000"

if not exist "%PYTHON_EXE%" (
    echo Virtual environment not found.
    echo Run scripts\setup_local.ps1 first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo .env file not found.
    echo Run scripts\setup_local.ps1 first and configure DATABASE_URL.
    pause
    exit /b 1
)

findstr /C:"CHANGE_ME" ".env" >nul
if %ERRORLEVEL% EQU 0 (
    echo DATABASE_URL still contains CHANGE_ME.
    echo Edit .env and replace CHANGE_ME with your local PostgreSQL password.
    pause
    exit /b 1
)

echo Starting Funding Arbitrage Terminal...
echo URL: %APP_URL%
echo.
start "" "%APP_URL%"
"%PYTHON_EXE%" -m funding_terminal run

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
)

pause
exit /b %ERRORLEVEL%

