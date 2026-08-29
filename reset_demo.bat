@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [LOI] Chua co moi truong .venv. Hay chay run.bat truoc.
    pause
    exit /b 1
)

echo Lenh nay se thay database hien tai bang du lieu demo.
echo Mot backup da kiem chung se duoc tao truoc khi thay doi.
set /p "CONFIRM=Go RESET de tiep tuc: "
if /I not "%CONFIRM%"=="RESET" (
    echo Da huy. Khong co du lieu nao bi thay doi.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" seed_full_demo.py --yes-reset
if errorlevel 1 (
    echo.
    echo Reset that bai. Neu server dang chay, hay dung server roi thu lai.
    pause
    exit /b 1
)

echo.
echo Reset demo thanh cong. Bay gio co the chay run_ngrok.bat.
pause
