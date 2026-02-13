@echo off
title Block-In Studio
cd /d "%~dp0"

echo === Block-In Studio ===
echo.

:: Create venv if missing
if not exist "venv" (
    echo Creating virtual environment...
    py -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python 3.11+ is installed.
        pause
        exit /b 1
    )
)

:: Activate and install deps
echo Installing/checking dependencies...
call venv\Scripts\activate.bat
pip install -r backend\requirements.txt --quiet

echo.
echo Starting server at http://127.0.0.1:589
echo Press Ctrl+C to stop.
echo.

:: Open browser after a 2-second delay so server can start
start /b cmd /c "timeout /t 2 /nobreak >NUL & start http://127.0.0.1:589"

:: Run server (blocking)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 589

pause
