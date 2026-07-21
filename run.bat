@echo off
REM ===== F-Selling: script chay live tren Windows =====
cd /d "%~dp0"

echo [1/3] Tao moi truong ao (venv)...
if not exist ".venv" (
    python -m venv .venv
)

echo [2/3] Cai dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] Khoi dong server tai http://127.0.0.1:8000 ...
REM Chay truc tiep bang uvicorn de bo qua buoc hoi ngrok trong app.py
uvicorn app:app --host 127.0.0.1 --port 8000

pause
