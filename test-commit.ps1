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

# ---------- 1. Chay test ----------
Write-Host ""
Write-Host "==> Dang chay test..." -ForegroundColor Cyan

if ($WithConcurrency) { $env:RUN_CONCURRENCY_TESTS = "1" }
& .\.venv\Scripts\python.exe -m pytest -q -p no:warnings
$testExit = $LASTEXITCODE
if ($WithConcurrency) { Remove-Item Env:\RUN_CONCURRENCY_TESTS -ErrorAction SilentlyContinue }

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
