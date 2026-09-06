@echo off
REM ===== Chay F-Selling + mo link cong khai bang ngrok (kem tu dong ket noi lai) =====
cd /d "%~dp0"

if not exist ".venv" (
    echo Chua co .venv. Dang tao va cai dependencies...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

call ".venv\Scripts\activate.bat"
python serve_with_ngrok.py

pause
