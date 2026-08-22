param(
    [ValidateSet("start", "status", "stop")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $PSScriptRoot
$AppUrl = "http://127.0.0.1:8000/"
$ReadyUrl = "http://127.0.0.1:8000/api/health/ready"
$PythonPath = Join-Path $AppRoot ".venv\Scripts\python.exe"

function Test-FSellingReady {
    try {
        $result = Invoke-RestMethod -Uri $ReadyUrl -TimeoutSec 2
        return $result.ready -eq $true
    }
    catch {
        return $false
    }
}

function Get-LocalListener {
    return Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort 8000 `
        -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-OwnedServerProcess {
    param([int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if (-not $process) {
        return $null
    }

    $expectedPython = [System.IO.Path]::GetFullPath($PythonPath)
    $commandLine = [string]$process.CommandLine
    $actualPython = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
    $isExpectedPython = $actualPython.Equals(
            $expectedPython,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or $commandLine.IndexOf(
            $expectedPython,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0
    $isExpectedCommand = $commandLine -match `
        "-m\s+uvicorn\s+(app|fselling\.main):app"

    if ($isExpectedPython -and $isExpectedCommand) {
        return $process
    }
    return $null
}

if ($Action -eq "status") {
    if (Test-FSellingReady) {
        Write-Host "F-Selling is READY at $AppUrl" -ForegroundColor Green
        exit 0
    }
    if (Get-LocalListener) {
        Write-Error "Port 8000 is occupied, but F-Selling is not ready."
    }
    Write-Error "F-Selling is stopped. Run run.bat to start it."
}

if ($Action -eq "stop") {
    $listener = Get-LocalListener
    if (-not $listener) {
        Write-Host "F-Selling is already stopped."
        exit 0
    }

    $serverProcess = Get-OwnedServerProcess -ProcessId $listener.OwningProcess
    if (-not $serverProcess) {
        Write-Error "Refusing to stop process $($listener.OwningProcess): it is not the F-Selling local server."
    }

    Stop-Process -Id $serverProcess.ProcessId
    Write-Host "F-Selling stopped."
    exit 0
}

if (Test-FSellingReady) {
    Write-Host "F-Selling is already READY. Opening $AppUrl" -ForegroundColor Green
    Write-Host "Stop later with: run.bat stop"
    Start-Process $AppUrl
    exit 0
}

if (Get-LocalListener) {
    Write-Error "Port 8000 is occupied by another or unhealthy process. Stop it before starting F-Selling."
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        Write-Error "Python is not installed or not available on PATH."
    }
    Write-Host "Creating the local Python environment..."
    & $systemPython.Source -m venv (Join-Path $AppRoot ".venv")
}

& $PythonPath -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing project dependencies once..."
    & $PythonPath -m pip install -r (Join-Path $AppRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Dependency installation failed."
    }
}

$env:GEMINI_ENABLED = "false"
$env:TTS_SERVER_ENABLED = "false"

$server = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $AppRoot `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    if (Test-FSellingReady) {
        Write-Host "F-Selling is READY at $AppUrl" -ForegroundColor Green
        Write-Host "Stop later with: run.bat stop"
        Start-Process $AppUrl
        exit 0
    }
    if ($server.HasExited) {
        Write-Error "F-Selling stopped during startup (exit $($server.ExitCode))."
    }
    Start-Sleep -Milliseconds 500
}

Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
Write-Error "F-Selling did not become ready within 30 seconds."
