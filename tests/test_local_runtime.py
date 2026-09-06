from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_run_bat_delegates_to_the_idempotent_local_launcher():
    source = (APP_ROOT / "run.bat").read_text(encoding="utf-8").lower()

    assert "scripts\\local_runtime.ps1" in source
    assert "%~1" in source
    assert "pip install --upgrade pip" not in source


def test_local_launcher_forces_paid_providers_off_and_waits_for_readiness():
    source = (APP_ROOT / "scripts" / "local_runtime.ps1").read_text(
        encoding="utf-8"
    )

    assert "$env:GEMINI_ENABLED = \"false\"" in source
    assert "$env:TTS_SERVER_ENABLED = \"false\"" in source
    assert "/api/health/ready" in source
    assert "Start-Process" in source
    assert "-WindowStyle Hidden" in source


def test_local_launcher_exposes_start_status_and_safe_stop_actions():
    source = (APP_ROOT / "scripts" / "local_runtime.ps1").read_text(
        encoding="utf-8"
    )

    assert 'ValidateSet("start", "status", "stop")' in source
    assert "Get-NetTCPConnection" in source
    assert "netstat -ano -p tcp" in source
    assert ".fselling-local.pid" in source
    assert "savedProcessId -ne $ProcessId" in source
    assert "ExecutablePath" in source
    assert "Stop-Process" in source
