Set-Location $PSScriptRoot
& venv\Scripts\activate.ps1
Start-Process http://127.0.0.1:589
python -m uvicorn backend.main:app --host 127.0.0.1 --port 589
