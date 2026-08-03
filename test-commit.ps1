<#
.SYNOPSIS
    Chay test, chi commit khi TOAN BO test pass.

.EXAMPLE
    .\test-commit.ps1 "add order cancellation with stock and voucher restore"
    .\test-commit.ps1 -TestOnly
    .\test-commit.ps1 "them tinh nang X" -WithConcurrency
#>
param(
    [Parameter(Position = 0)]
    [string]$Message,

    # Chi chay test, khong commit
    [switch]$TestOnly,

    # Chay ca test da luong (mac dinh bi skip vi SQLite de nhieu)
    [switch]$WithConcurrency
)

Set-Location $PSScriptRoot

# Lock sot lai tu lan chay truoc se chan git add/commit
Remove-Item .git\index.lock -Force -ErrorAction SilentlyContinue

if (-not $TestOnly -and [string]::IsNullOrWhiteSpace($Message)) {
    Write-Host "Thieu commit message. Vi du:" -ForegroundColor Yellow
    Write-Host '   .\test-commit.ps1 "mo ta thay doi"'
    Write-Host '   .\test-commit.ps1 -TestOnly'
    exit 2
}

# ---------- 0. Kiem cu phap JS ----------
# File locale da vo cu phap HAI lan (chuoi bi xuong dong that thay vi hai ky tu
# \n). Mot file locale vo la TOAN BO ban dich cua trang do khong nap duoc, va
# nguoi dung nhin thay 'seller.page_title' thay vi chu tieng Viet.
# tests/test_i18n.py chi kiem 4 file locale; buoc nay kiem het moi file JS.
# Chay TRUOC pytest vi no mat chua toi mot giay.
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    Write-Host ""
    Write-Host "==> Kiem cu phap JS..." -ForegroundColor Cyan
    $jsLoi = @()
    Get-ChildItem -Path static\js -Recurse -Filter *.js | ForEach-Object {
        & node --check $_.FullName 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $jsLoi += $_.FullName }
    }
    if ($jsLoi.Count -gt 0) {
        Write-Host ""
        Write-Host "======================================" -ForegroundColor Red
        Write-Host " JS VO CU PHAP - KHONG commit:" -ForegroundColor Red
        $jsLoi | ForEach-Object {
            Write-Host "   $_" -ForegroundColor Red
            & node --check $_
        }
        Write-Host "======================================" -ForegroundColor Red
        exit 1
    }
    Write-Host "JS OK" -ForegroundColor Green
} else {
    Write-Host "(Khong tim thay node - bo qua buoc kiem cu phap JS)" -ForegroundColor DarkGray
}

# ---------- 1. Chay test ----------
Write-Host ""
Write-Host "==> Dang chay test..." -ForegroundColor Cyan

if ($WithConcurrency) { $env:RUN_CONCURRENCY_TESTS = "1" }
# Do thoi gian de thay bo test cham dan. Mot lan chay dot ngot lau gap 7 lan
# binh thuong la dau hieu co gi do sai (tien trinh khac tranh may, mot test moi
# goi mang, vong lap khong thoat) - khong in ra thi khong ai de y, va bo test
# cham la bo test bi bo qua.
$dongHo = [Diagnostics.Stopwatch]::StartNew()
& .\.venv\Scripts\python.exe -m pytest -q -p no:warnings
$testExit = $LASTEXITCODE
$dongHo.Stop()
if ($WithConcurrency) { Remove-Item Env:\RUN_CONCURRENCY_TESTS -ErrorAction SilentlyContinue }

# CO Y khong dat nguong canh bao. Nguong co dinh phai bao tri va de keu oan:
# 5 phut thi keu moi lan, 15 phut thi khong bao gio keu. In thang con so moi
# lan la du de nhan ra khi no nhay tu 650 len 1400 giay.
#
# Do duoc ngay 2026-08-03: 731 test / 653 giay, tuc ~0,9 giay moi test. KHONG
# co test nao cham ca - cham nhat moi 2,6 giay, va 15 test cham nhat cong lai
# chi chiem 4% tong thoi gian. Ca bo cham DEU, vi bcrypt: moi test tao tai
# khoan ton 2 lan bam mat khau (dang nhap + dang ky), moi lan ~0,4 giay o muc
# 12 vong mac dinh.
#
# Ha so vong bcrypt trong test se rut xuong con khoang 1-1,5 phut. DA CAN NHAC
# VA TU CHOI: chu du an chon chay dung tham so cua production hon la chay
# nhanh. Dung "toi uu" chuyen nay ma khong hoi lai.
Write-Host ("Thoi gian chay test: {0:N1} giay" -f $dongHo.Elapsed.TotalSeconds) -ForegroundColor DarkGray

if ($testExit -ne 0) {
    Write-Host ""
    Write-Host "======================================" -ForegroundColor Red
    Write-Host " TEST FAIL (exit code $testExit)" -ForegroundColor Red
    Write-Host " KHONG commit. Gui phan output o tren cho Claude." -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host " TEST PASS - toan bo test deu xanh" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green

if ($TestOnly) {
    Write-Host "(-TestOnly: bo qua buoc commit)" -ForegroundColor DarkGray
    exit 0
}

# ---------- 2. Stage ----------
git add -A
$staged = @(git diff --cached --name-only)

if ($staged.Count -eq 0) {
    Write-Host ""
    Write-Host "Khong co thay doi nao de commit." -ForegroundColor Yellow
    exit 0
}

# ---------- 3. Chan file nhay cam ----------
# Luoi an toan phong khi .gitignore bi sua nham: secret va DB that
# tuyet doi khong duoc vao Git.
$nguyHiem = $staged | Where-Object {
    $_ -match '(^|/)\.env$' -or
    $_ -match '\.db$' -or
    $_ -match 'request_log\.txt$' -or
    $_ -match '(^|/)\.venv/'
}

if ($nguyHiem) {
    Write-Host ""
    Write-Host "DUNG LAI - phat hien file nhay cam bi stage:" -ForegroundColor Red
    $nguyHiem | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
    Write-Host "Da bo stage toan bo. Kiem tra lai .gitignore truoc khi commit." -ForegroundColor Red
    git reset | Out-Null
    exit 1
}

# ---------- 4. Commit ----------
Write-Host ""
Write-Host "File se duoc commit:" -ForegroundColor Cyan
$staged | ForEach-Object { Write-Host "   $_" }

git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Host "Commit that bai." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==> Commit thanh cong:" -ForegroundColor Green
git --no-pager log --oneline -1
exit 0
