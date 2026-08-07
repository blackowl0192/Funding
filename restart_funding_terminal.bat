@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Virtual environment not found.
    echo Run scripts\setup_local.ps1 first.
    pause
    exit /b 1
)

"%PYTHON_EXE%" scripts\runtime_manager.py restart

if errorlevel 1 (
    echo.
    echo Operation failed.
    pause
    exit /b 1
)

echo.
echo Funding Terminal is running in background.
echo You may close this window.
ping -n 3 127.0.0.1 >nul
exit /b 0
