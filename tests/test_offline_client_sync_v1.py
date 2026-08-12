"""I09-F2: durable offline receipt sync client contract v1."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_node_fake_indexeddb_sync_harness():
    """ACK/retry/auth/reclaim/restart/stale-lock contracts execute in Node."""

    completed = subprocess.run(
        ["node", "tests/js/offline-ban-sync-v1.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "offline-ban-sync-v1 harness: 8 passed" in completed.stdout


def test_sync_uses_dedicated_transport_and_exact_lease_header():
    js = _read("static/js/offline-ban.js")
    start = js.index("// ---------- Sync engine v1 (I09-F2) ----------")
    end = js.index("// ---------- Contract v0 giữ nguyên ----------")
    sync = js[start:end]
    assert "global.getToken" in sync
    assert "X-Offline-Lease-Token" in sync
    assert "apiCall(" not in sync
    assert "clearAuthState" not in sync
    assert "redirectToLogin" not in sync


def test_v1_sync_is_wired_without_replacing_v0_sync():
    js = _read("static/js/pos.js")
    assert "OfflineBan.batTuDongBoV1(" in js
    assert "OfflineBan.batTuDongBo(" in js
    html = _read("static/pos.html")
    assert "/js/offline-ban.js?v=20260813-i09-f2" in html
    assert "/js/pos.js?v=20260813-i09-f2" in html


def test_v1_state_and_lock_contract_are_explicit():
    js = _read("static/js/offline-ban.js")
    for state in (
        "DRAFT",
        "READY",
        "SYNCING",
        "ACKED",
        "RETRYABLE",
        "BLOCKED_RECOVERABLE",
        "QUARANTINED",
    ):
        assert f"'{state}'" in js
    assert "sync_lock_v1" in js
    assert "owner_tab_id" in js
    assert "fence" in js
    assert "expires_at" in js
    assert "SYNC_LOCK_HEARTBEAT_MS = 5 * 1000" in js
    assert "SYNC_LOCK_TTL_MS = 15 * 1000" in js
    assert "SYNC_STALE_MS = 60 * 1000" in js
