@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
start http://127.0.0.1:589
python -m uvicorn backend.main:app --host 127.0.0.1 --port 589
