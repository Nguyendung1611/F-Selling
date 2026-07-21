@echo off
REM ===== Chay F-Selling + mo link cong khai bang ngrok =====
cd /d "%~dp0"

REM Bao dam da co venv (chay run.bat truoc neu chua co)
if not exist ".venv" (
    echo Chua co .venv. Dang tao va cai dependencies...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

REM Khoi dong server trong mot cua so rieng
start "F-Selling Server" cmd /k ".venv\Scripts\activate.bat && uvicorn app:app --host 127.0.0.1 --port 8000"

REM Cho server san sang roi mo tunnel
timeout /t 6 >nul

call ".venv\Scripts\activate.bat"
python ngrok_tunnel.py

pause
