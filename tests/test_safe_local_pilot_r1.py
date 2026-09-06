import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

import seed_full_demo


APP_ROOT = Path(__file__).resolve().parents[1]


def test_demo_reset_requires_confirmation_and_preserves_verified_backup(tmp_path):
    database = tmp_path / "pilot.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('kept')")
        connection.commit()

    with pytest.raises(ValueError, match="--yes-reset"):
        seed_full_demo._prepare_database_reset(database, confirmed=False)
    assert database.exists()

    backup = seed_full_demo._prepare_database_reset(
        database,
        confirmed=True,
        now=datetime(2026, 8, 29, 12, 0, tzinfo=seed_full_demo.VN),
    )

    assert not database.exists()
    assert backup is not None and backup.exists()
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("kept",)


def test_pilot_launcher_is_provider_off_ready_gated_and_demo_only():
    source = (APP_ROOT / "serve_with_ngrok.py").read_text(encoding="utf-8")

    assert source.index('os.environ["GEMINI_ENABLED"] = "false"') < source.index(
        "import uvicorn"
    )
    assert source.index('os.environ["TTS_SERVER_ENABLED"] = "false"') < source.index(
        "import uvicorn"
    )
    assert "/api/health/ready" in source
    assert "Demo@2026" in source
    assert "Tài khoản: admin" not in source
    assert "nhanvien" not in source
    assert "if local_ready():" in source
    assert "Cổng 8000 đã có F-Selling chạy" in source
    assert "URL_FILE.unlink(missing_ok=True)" in source


def test_demo_seed_rotates_privileged_passwords_and_reset_batch_is_explicit():
    seed = (APP_ROOT / "seed_full_demo.py").read_text(encoding="utf-8")
    reset = (APP_ROOT / "reset_demo.bat").read_text(encoding="utf-8")
    launcher = (APP_ROOT / "run_ngrok.bat").read_text(encoding="utf-8")

    assert "MAT_KHAU_NHAN_VIEN = secrets.token_urlsafe(32)" in seed
    assert "ADMIN_PW = secrets.token_urlsafe(32)" in seed
    assert '"password": MAT_KHAU_NHAN_VIEN' in seed
    assert 'print("     - Tài khoản: admin")' not in seed
    assert "--yes-reset" in reset
    assert 'not "%CONFIRM%"=="RESET"' in reset
    assert "python serve_with_ngrok.py" in launcher
