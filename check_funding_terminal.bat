@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Virtual environment not found.
    echo Run scripts\setup_local.ps1 first.
    pause
    exit /b 1
)

echo Checking database...
"%PYTHON_EXE%" -m funding_terminal check-db
echo.

echo Checking Binance public API...
"%PYTHON_EXE%" -m funding_terminal check-binance
echo.

echo Application status...
"%PYTHON_EXE%" -m funding_terminal status
echo.

pause

