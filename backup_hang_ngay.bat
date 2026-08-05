@echo off
REM ===== F-Selling: sao luu database len Cloudflare R2 =====
REM
REM File nay danh cho Windows Task Scheduler goi tu dong hang ngay.
REM Chay tay cung duoc: bam dup vao file.
REM
REM Dong `cd /d "%~dp0"` la BAT BUOC, khong duoc bo:
REM   config.py doc file .env theo THU MUC LAM VIEC HIEN TAI. Task Scheduler
REM   chay voi thu muc mac dinh la C:\Windows\System32, khong quay ve day thi
REM   khong thay .env -> tuong la chua cau hinh R2 -> thoat ma 2, va khong ai
REM   biet vi no chay luc 12 gio trua khong ai nhin.
cd /d "%~dp0"

set LOG=%~dp0backup_log.txt

echo.>> "%LOG%"
echo ==================================================>> "%LOG%"
echo [%date% %time%] Bat dau sao luu>> "%LOG%"

".venv\Scripts\python.exe" "scripts\backup_thu.py" >> "%LOG%" 2>&1

if errorlevel 1 (
    echo [%date% %time%] *** THAT BAI *** xem chi tiet phia tren>> "%LOG%"
) else (
    echo [%date% %time%] Xong, thanh cong>> "%LOG%"
)
