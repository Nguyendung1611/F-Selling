"""I09-F1: durable client receipt/persistence contract v1."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fselling.services.offline_fingerprint import fingerprint_offline_receipt_v1


ROOT = Path(__file__).resolve().parents[1]
KNOWN_VECTOR = (
    "fsofr1:8fdaa734e0088f5b23c40ad1d411f56e07836fb4114613400230762f54320e22"
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_node_fake_indexeddb_persistence_harness():
    """Executable v1 upgrade/identity/sequence/crash/fingerprint coverage."""

    completed = subprocess.run(
        ["node", "tests/js/offline-ban-v1.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "offline-ban-v1 harness: 1 passed" in completed.stdout


def test_node_auth_identity_seal_harness():
    """Old identity is sealed across same-tab, cross-tab and unloaded module."""

    completed = subprocess.run(
        ["node", "tests/js/auth-offline-seal.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "auth-offline-seal harness: 1 passed" in completed.stdout


def test_server_known_vector_matches_executable_client_vector():
    """The Node harness asserts the same constant from independent JS bytes."""

    result = fingerprint_offline_receipt_v1(
        shop_id=1,
        sold_at_client_utc="2025-07-15 09:30:00.123456",
        client_monotonic_ms=5000,
        monotonic_valid=True,
        server_anchor_id="anc_abc123",
        lease_id="lease-001",
        device_id="dev-001",
        offline_session_id="session-001",
        sequence=1,
        offline_uuid="uuid-test-001",
        catalog_version=1,
        catalog_snapshot_digest="sha256:deadbeef",
        items=[
            {
                "product_id": 10,
                "product_name": "Su\u0301a  ",
                "unit_price_vnd": 15000,
                "quantity": 2,
            },
            {
                "product_id": 5,
                "product_name": "Ba\u0301nh",
                "unit_price_vnd": 25000,
                "quantity": 1,
            },
        ],
        cash_tendered_vnd=55000,
    )
    assert result.digest == KNOWN_VECTOR


def test_pos_awaits_durable_v1_or_v0_before_cleanup():
    pos = _read("static/js/pos.js")
    start = pos.index("async function luuBanOffline(")
    end = pos.index("async function thuTaoDonDangDo(")
    body = pos[start:end]
    write = body.index("await OfflineBan.luuPhieuTuPOS(")
    cleanup = body.index("xoaCheckoutDangDo()")
    assert write < cleanup
    assert "payment_method: state.payment_method" in body
    assert "voucher_code: payload.voucher_code" in body
    assert "loyalty_points_to_use:" in body


def test_all_touched_static_files_have_i09_f1_correction_cache_buster():
    html_files = sorted((ROOT / "static").glob("*.html"))
    api_consumers = [path for path in html_files if '/js/api.js?v=' in path.read_text(encoding="utf-8")]
    assert {path.name for path in api_consumers} == {
        "admin.html", "index.html", "pos.html", "register.html", "seller.html", "verify.html"
    }
    for path in api_consumers:
        assert '/js/api.js?v=20260812-i09-f1-c1' in path.read_text(encoding="utf-8")

    index = _read("static/index.html")
    pos = _read("static/pos.html")
    assert '/js/auth.js?v=20260812-i09-f1-c1' in index
    assert '/js/offline-ban.js?v=20260812-i09-f1-c1' in pos
    assert '/js/pos.js?v=20260812-i09-f1-c1' in pos


def test_same_tab_login_seals_previous_identity_before_overwrite():
    auth = _read("static/js/auth.js")
    seal = auth.index("await prepareAuthIdentityChangeV1(username)")
    token_write = auth.index("localStorage.setItem('token', data.access_token)")
    username_write = auth.index("localStorage.setItem('username', username)")
    assert seal < token_write < username_write


def test_f1_does_not_add_v1_sync_or_touch_v0_payload_shape():
    js = _read("static/js/offline-ban.js")
    v0_sync = js[js.index("async function dongBo(") : js.index("function luuAnhChupSanPham(")]
    assert "receipt_v1" not in v0_sync
    assert "X-Offline-Lease-Token" not in v0_sync
    assert "offline_contract_version" not in v0_sync
    assert "client_fingerprint" not in v0_sync
