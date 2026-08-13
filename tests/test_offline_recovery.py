"""I09-G1 owner recovery, tombstone, export/import and atomicity regressions."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event

from conftest import (
    _TEST_MIGRATIONS,
    _unique,
    admin_token,
    auth,
    create_category,
    create_product,
    create_shop,
    new_seller,
    new_staff,
    seller_with_shop,
)
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import offline_lease_service, offline_recovery_service


@pytest.fixture(autouse=True)
def lease_enabled(monkeypatch):
    monkeypatch.setattr(
        offline_lease_service.config, "OFFLINE_LEASE_ISSUANCE_ENABLED", True
    )
    monkeypatch.setattr(
        offline_lease_service.subscription_service,
        "require_pro",
        lambda *_args, **_kwargs: {"can_use_pro": True},
    )
    monkeypatch.setattr(
        offline_lease_service.subscription_service,
        "get_subscription_state",
        lambda *_args, **_kwargs: {"can_use_pro": True},
    )


def _v0_receipt(*, product_id: int, name: str = "Hàng cũ", quantity: int = 1):
    return {
        "contract_version": 0,
        "offline_uuid": f"legacy-{uuid.uuid4()}",
        "sold_at_utc": "2026-08-12T03:00:00+00:00",
        "items": [
            {
                "product_id": product_id,
                "product_name": name,
                "unit_price_vnd": 100_000,
                "quantity": quantity,
            }
        ],
        "cash_tendered_vnd": 100_000 * quantity,
    }


def _export(client, ctx, receipt, *, token=None, shop_id=None):
    response = client.post(
        f"/api/offline/recovery/{shop_id or ctx['shop_id']}/export",
        headers=auth(token or ctx["token"]),
        json={"receipt": receipt},
    )
    return response


def _import(client, ctx, document, *, token=None, shop_id=None):
    return client.post(
        f"/api/offline/recovery/{shop_id or ctx['shop_id']}/import",
        headers=auth(token or ctx["token"]),
        content=json.dumps(document, ensure_ascii=False).encode("utf-8"),
    )


def _resolve(
    client,
    ctx,
    document,
    *,
    state_version=0,
    reason="Owner xác nhận phục hồi đúng chứng từ",
    line_resolutions=None,
    sold_at_effective_utc=None,
    token=None,
):
    receipt_uuid = document["payload"]["receipt"]["offline_uuid"]
    body = {
        "document": document,
        "state_version": state_version,
        "reason": reason,
        "line_resolutions": line_resolutions or [],
    }
    if sold_at_effective_utc is not None:
        body["sold_at_effective_utc"] = sold_at_effective_utc
    return client.post(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt_uuid}/resolve",
        headers=auth(token or ctx["token"]),
        json=body,
    )


def _resolve_ingested_direct(
    client,
    ctx,
    offline_uuid,
    *,
    state_version=0,
    reason="Owner xác nhận phục hồi đúng chứng từ",
    line_resolutions=None,
    token=None,
):
    return client.post(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates/{offline_uuid}/resolve",
        headers=auth(token or ctx["token"]),
        json={
            "state_version": state_version,
            "reason": reason,
            "line_resolutions": line_resolutions or [],
        },
    )


def _recompute_file_hash(document: dict) -> None:
    core = {key: document[key] for key in ("format", "payload", "version")}
    encoded = json.dumps(
        core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    document["sha256"] = hashlib.sha256(encoded).hexdigest()


def _db_counts(shop_id: int):
    session = SessionLocal()
    try:
        order_ids = [
            row[0]
            for row in session.query(models.Order.id)
            .filter(models.Order.shop_id == shop_id)
            .all()
        ]
        return {
            "orders": len(order_ids),
            "payments": (
                session.query(models.OrderPayment)
                .filter(models.OrderPayment.order_id.in_(order_ids or [-1]))
                .count()
            ),
            "correct": (
                session.query(models.OfflineRecoveryAction)
                .filter(
                    models.OfflineRecoveryAction.shop_id == shop_id,
                    models.OfflineRecoveryAction.action_kind == "CORRECT",
                )
                .count()
            ),
        }
    finally:
        session.close()


def _normal_v0_payload(receipt: dict) -> dict:
    return {
        "offline_uuid": receipt["offline_uuid"],
        "sold_at": receipt["sold_at_utc"],
        "items": [
            {
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "unit_price": item["unit_price_vnd"],
                "quantity": item["quantity"],
            }
            for item in receipt["items"]
        ],
        "cash_tendered": receipt["cash_tendered_vnd"],
    }


def _normal_ingest_v0(client, ctx, receipt):
    response = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        headers=auth(ctx["token"]),
        json=_normal_v0_payload(receipt),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _known_cost_product(client, ctx, *, quantity=5, unit_cost=30_000):
    product = create_product(
        client,
        ctx["token"],
        ctx["shop_id"],
        _unique("Recovery known"),
        100_000,
        0,
        ctx["category_id"],
    )
    adjusted = client.post(
        f"/api/products/{product['id']}/stock",
        headers=auth(ctx["token"]),
        json={
            "delta": quantity,
            "unit_cost": unit_cost,
            "reason": "Tạo pool cost phục hồi",
        },
    )
    assert adjusted.status_code == 200, adjusted.text
    return product


def test_export_deterministic_import_list_read_owner_admin_and_no_leak(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=999_999_001)
    first = _export(client, ctx, receipt)
    second = _export(client, ctx, receipt)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    document = first.json()
    serialized = first.text.lower()
    assert document["format"] == "FS-OFFLINE-RECOVERY"
    assert document["version"] == 1
    assert len(document["sha256"]) == 64
    assert "device_label" not in serialized
    assert "lease_token" not in serialized
    assert "client_fingerprint" not in serialized
    assert "secret_sha256" not in serialized

    imported = _import(client, ctx, document)
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] is True
    assert imported.json()["state"] == "ABANDONED"
    retry = _import(client, ctx, document)
    assert retry.status_code == 200
    assert retry.json()["created"] is False

    listed = client.get(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates?limit=1&offset=0",
        headers=auth(ctx["token"]),
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["offline_uuid"] == receipt["offline_uuid"]
    read = client.get(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt['offline_uuid']}",
        headers=auth(ctx["token"]),
    )
    assert read.status_code == 200
    assert set(read.json()) == {
        "offline_uuid",
        "contract_version",
        "state",
        "state_version",
        "content_sha256",
        "replacement_offline_uuid",
        "order_id",
        "created_at",
        "updated_at",
    }

    _staff_name, staff_token = new_staff(client, ctx, "MANAGER")
    other = seller_with_shop(client)
    before_denied = _db_counts(ctx["shop_id"])
    denied_paths = [
        ("get", f"/api/offline/recovery/{ctx['shop_id']}/candidates", None),
        (
            "get",
            f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt['offline_uuid']}",
            None,
        ),
        ("post", f"/api/offline/recovery/{ctx['shop_id']}/export", {"receipt": receipt}),
        ("post", f"/api/offline/recovery/{ctx['shop_id']}/import", document),
        (
            "post",
            f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt['offline_uuid']}/resolve",
            {
                "document": document,
                "state_version": 0,
                "reason": "Không được dùng actor sai shop",
                "line_resolutions": [
                    {"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}
                ],
            },
        ),
    ]
    for denied_token in (staff_token, other["token"]):
        for method, path, body in denied_paths:
            if method == "get":
                response = client.get(path, headers=auth(denied_token))
            else:
                response = client.post(
                    path,
                    headers=auth(denied_token),
                    json=body,
                )
            assert response.status_code == 404
            assert response.json()["detail"]["code"] == "OFFLINE_RECOVERY_NOT_FOUND"
    assert _db_counts(ctx["shop_id"]) == before_denied

    admin = admin_token(client)
    admin_read = client.get(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt['offline_uuid']}",
        headers=auth(admin),
    )
    assert admin_read.status_code == 200
    admin_export = _export(client, ctx, receipt, token=admin)
    assert admin_export.status_code == 200
    admin_import = _import(client, ctx, admin_export.json(), token=admin)
    assert admin_import.status_code == 200
    assert admin_import.json()["created"] is False
    admin_resolve = _resolve(
        client,
        ctx,
        document,
        token=admin,
        reason="ADMIN xác nhận chi phí chưa biết để phục hồi",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert admin_resolve.status_code == 200, admin_resolve.text
    assert admin_resolve.json()["created"] is True
    _TEST_MIGRATIONS.verify()


def test_candidate_pagination_is_one_bounded_stable_query_without_issue_duplicates(client):
    """The mixed staged/direct feed must page in SQL, not after an .all()."""
    ctx = seller_with_shop(client)
    candidate_uuids = []
    for ordinal in range(4):
        receipt = _v0_receipt(product_id=999_990_000 + ordinal)
        document = _export(client, ctx, receipt).json()
        assert _import(client, ctx, document).status_code == 200
        candidate_uuids.append(receipt["offline_uuid"])
    for ordinal in range(4):
        receipt = _v0_receipt(product_id=999_991_000 + ordinal)
        if ordinal == 0:
            # Two open issues must still yield one candidate (EXISTS, no join fanout).
            receipt["items"].append(
                {
                    "product_id": 999_992_000,
                    "product_name": "Hàng cũ thứ hai",
                    "unit_price_vnd": 100_000,
                    "quantity": 1,
                }
            )
            receipt["cash_tendered_vnd"] = 200_000
        _normal_ingest_v0(client, ctx, receipt)
        candidate_uuids.append(receipt["offline_uuid"])

    session = SessionLocal()
    try:
        (
            session.query(models.OfflineReceiptRegistry)
            .filter(models.OfflineReceiptRegistry.offline_uuid.in_(candidate_uuids))
            .update({"updated_at": "2026-08-13 08:00:00.000000"}, synchronize_session=False)
        )
        session.commit()
        engine = session.get_bind()
    finally:
        session.close()

    statements = []

    def record_sql(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM offline_receipt_registry" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        first = client.get(
            f"/api/offline/recovery/{ctx['shop_id']}/candidates?limit=3&offset=0",
            headers=auth(ctx["token"]),
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)
    assert first.status_code == 200, first.text
    assert len(statements) == 1
    assert " LIMIT " in statements[0].upper()
    assert " OFFSET " in statements[0].upper()

    pages = [first.json()]
    while pages[-1]["next_offset"] is not None:
        page = client.get(
            f"/api/offline/recovery/{ctx['shop_id']}/candidates?limit=3&offset={pages[-1]['next_offset']}",
            headers=auth(ctx["token"]),
        )
        assert page.status_code == 200, page.text
        pages.append(page.json())
    received = [item["offline_uuid"] for page in pages for item in page["items"]]
    assert received == sorted(candidate_uuids)
    assert len(received) == len(set(received)) == 8
    assert [page["next_offset"] for page in pages] == [3, 6, None]


def test_map_creates_new_artifact_tombstone_and_exact_known_cost(client):
    ctx = seller_with_shop(client)
    target = _known_cost_product(client, ctx)
    receipt = _v0_receipt(product_id=999_999_002, quantity=2)
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200

    recovered = _resolve(
        client,
        ctx,
        document,
        line_resolutions=[
            {"item_ordinal": 1, "action": "MAP", "product_id": target["id"]}
        ],
    )
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["created"] is True
    assert result["replacement_offline_uuid"] != receipt["offline_uuid"]

    session = SessionLocal()
    try:
        original = session.get(models.OfflineReceiptRegistry, receipt["offline_uuid"])
        replacement = session.get(
            models.OfflineReceiptRegistry, result["replacement_offline_uuid"]
        )
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == result["order_id"])
            .one()
        )
        product = session.get(models.Product, target["id"])
        receipt_row = (
            session.query(models.OfflineReceipt)
            .filter(models.OfflineReceipt.order_id == result["order_id"])
            .one()
        )
        assert (original.state, original.order_id, original.state_version) == (
            "SUPERSEDED",
            None,
            1,
        )
        assert original.superseded_by_offline_uuid == replacement.offline_uuid
        assert replacement.server_fingerprint != original.server_fingerprint
        assert receipt_row.attribution_kind == "LEGACY_UNKNOWN"
        assert receipt_row.time_confidence == "LEGACY"
        assert receipt_row.lease_id is receipt_row.sequence is None
        assert (line.product_id, line.cost_known_qty, line.cost_unknown_qty) == (
            target["id"],
            2,
            0,
        )
        assert line.cost_basis_vnd == 60_000
        assert product.stock == 3
        assert (
            session.query(models.OrderPayment)
            .filter(models.OrderPayment.order_id == result["order_id"])
            .count()
            == 1
        )
        action = (
            session.query(models.OfflineRecoveryAction)
            .filter(
                models.OfflineRecoveryAction.original_offline_uuid
                == receipt["offline_uuid"],
                models.OfflineRecoveryAction.action_kind == "CORRECT",
            )
            .one()
        )
        log = session.get(models.SystemLog, action.system_log_id)
        shop = session.get(models.Shop, ctx["shop_id"])
        assert log.user_id == action.performed_by_user_id == shop.owner_id
        assert log.shop_id == ctx["shop_id"]
    finally:
        session.close()

    # Lost response/double submit returns the durable winner only.
    retry = _resolve(
        client,
        ctx,
        document,
        line_resolutions=[
            {"item_ordinal": 1, "action": "MAP", "product_id": target["id"]}
        ],
    )
    assert retry.status_code == 200
    assert retry.json()["created"] is False
    assert retry.json()["order_id"] == result["order_id"]
    import_retry = _import(client, ctx, document)
    assert import_retry.status_code == 200
    assert import_retry.json()["created"] is False
    assert import_retry.json()["state"] == "SUPERSEDED"
    normal_original = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        headers=auth(ctx["token"]),
        json={
            "offline_uuid": receipt["offline_uuid"],
            "sold_at": receipt["sold_at_utc"],
            "items": [
                {
                    "product_id": 999_999_002,
                    "product_name": "Hàng cũ",
                    "unit_price": 100_000,
                    "quantity": 2,
                }
            ],
            "cash_tendered": 200_000,
        },
    )
    assert normal_original.status_code == 409
    assert normal_original.json()["detail"]["code"] == "OFFLINE_RECEIPT_UUID_UNAVAILABLE"
    assert _db_counts(ctx["shop_id"])["correct"] == 1
    _TEST_MIGRATIONS.verify()


def test_accept_unknown_requires_reason_and_persists_unknown_cost_audit(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=999_999_003, quantity=2)
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200

    too_short = _resolve(
        client,
        ctx,
        document,
        reason="ngắn",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert too_short.status_code == 422
    recovered = _resolve(
        client,
        ctx,
        document,
        reason="Chủ shop chấp nhận chưa biết giá vốn",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert recovered.status_code == 200, recovered.text

    session = SessionLocal()
    try:
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == recovered.json()["order_id"])
            .one()
        )
        issue = (
            session.query(models.OfflineReceiptIssue)
            .filter(models.OfflineReceiptIssue.order_id == recovered.json()["order_id"])
            .filter(models.OfflineReceiptIssue.issue_code == "SP_KHONG_CON")
            .one()
        )
        assert line.product_id is None
        assert (line.cost_known_qty, line.cost_unknown_qty, line.cost_basis_vnd) == (
            0,
            2,
            0,
        )
        assert issue.state == "RESOLVED"
        assert issue.resolution_kind == "OWNER_ACCEPT_UNKNOWN_COST"
        assert issue.reason == "Chủ shop chấp nhận chưa biết giá vốn"
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()


def _issue_staff_lease(client, ctx):
    _name, staff_token = new_staff(client, ctx, "CASHIER")
    response = client.post(
        "/api/offline/leases",
        headers=auth(staff_token),
        json={"shop_id": ctx["shop_id"], "device_id": f"dev-{uuid.uuid4().hex[:8]}"},
    )
    assert response.status_code == 200, response.text
    return staff_token, response.json()


def _recovery_v1_receipt(lease, product):
    return {
        "contract_version": 1,
        "lease_id": lease["lease_id"],
        "device_id": lease["device_id"],
        "offline_session_id": lease["lease_id"],
        "sequence": 1,
        "offline_uuid": f"v1-{uuid.uuid4()}",
        "sold_at_client_utc": lease["anchor_server_time_utc"],
        "client_monotonic_ms": 0,
        "monotonic_valid": True,
        "server_anchor_id": lease["server_anchor_id"],
        "catalog_version": lease["catalog_version"],
        "catalog_snapshot_digest": lease["catalog_snapshot_digest"],
        "items": [
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "unit_price_vnd": product["price"],
                "quantity": 1,
            }
        ],
        "cash_tendered_vnd": product["price"],
    }


def test_revoked_v1_owner_recovery_attribution_and_normal_original_blocked(client):
    ctx = seller_with_shop(client)
    staff_token, lease = _issue_staff_lease(client, ctx)
    receipt = _recovery_v1_receipt(lease, ctx["product"])
    revoked = client.request(
        "DELETE",
        f"/api/offline/leases/{lease['lease_id']}",
        headers=auth(ctx["token"]),
        json={"reason": "Máy bán bị mất cần thu hồi ngay"},
    )
    assert revoked.status_code == 200

    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    recovered = _resolve(client, ctx, document)
    assert recovered.status_code == 200, recovered.text

    session = SessionLocal()
    try:
        row = (
            session.query(models.OfflineReceipt)
            .filter(models.OfflineReceipt.order_id == recovered.json()["order_id"])
            .one()
        )
        order = session.get(models.Order, recovered.json()["order_id"])
        payment = (
            session.query(models.OrderPayment)
            .filter(models.OrderPayment.order_id == order.id)
            .one()
        )
        assert row.attribution_kind == "OWNER_RECOVERY"
        assert row.time_confidence == "RECOVERED"
        assert row.sold_by_claimed_user_id == lease["user_id"]
        assert row.synced_by_user_id != row.sold_by_claimed_user_id
        assert order.created_by_user_id == payment.created_by_user_id == lease["user_id"]
        assert row.lease_id == lease["lease_id"]
        assert row.sequence == 1
        assert row.client_fingerprint is None
        assert row.client_fingerprint_mismatch == 0
    finally:
        session.close()

    normal_payload = {
        "offline_contract_version": 1,
        **{key: value for key, value in receipt.items() if key != "contract_version"},
        "cash_tendered": receipt["cash_tendered_vnd"],
        "client_fingerprint": "fsofr1:" + "0" * 64,
    }
    normal_payload.pop("cash_tendered_vnd")
    normal = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        headers={**auth(staff_token), "X-Offline-Lease-Token": lease["lease_token"]},
        json=normal_payload,
    )
    assert normal.status_code == 409
    assert normal.json()["detail"]["code"] == "OFFLINE_LEASE_REVOKED"
    assert _db_counts(ctx["shop_id"])["orders"] == 1
    _TEST_MIGRATIONS.verify()


def test_beyond_grace_v1_recovery_keeps_original_time_evidence(client):
    ctx = seller_with_shop(client)
    staff_token, lease = _issue_staff_lease(client, ctx)
    old_anchor = "2026-01-01 00:00:00.000000"
    old_expiry = "2026-01-01 12:00:00.000000"
    session = SessionLocal()
    try:
        row = session.get(models.OfflineLease, lease["lease_id"])
        row.anchor_server_time_utc = old_anchor
        row.issued_at = old_anchor
        row.expires_at = old_expiry
        session.commit()
    finally:
        session.close()
    lease["anchor_server_time_utc"] = old_anchor
    lease["issued_at"] = old_anchor
    lease["expires_at"] = old_expiry
    receipt = _recovery_v1_receipt(lease, ctx["product"])
    receipt["monotonic_valid"] = False
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    recovered = _resolve(client, ctx, document)
    assert recovered.status_code == 200, recovered.text

    session = SessionLocal()
    try:
        recovered_receipt = (
            session.query(models.OfflineReceipt)
            .filter(models.OfflineReceipt.order_id == recovered.json()["order_id"])
            .one()
        )
        assert recovered_receipt.time_confidence == "RECOVERED"
        assert recovered_receipt.sold_at_client_utc == old_anchor
        assert recovered_receipt.client_monotonic_ms == 0
        # Equality encodes original monotonic_valid=False without claiming a
        # trusted bound; OWNER_RECOVERY/RECOVERED carries the trust semantics.
        assert recovered_receipt.sold_at_upper_bound == old_anchor
    finally:
        session.close()

    normal_payload = {
        "offline_contract_version": 1,
        **{key: value for key, value in receipt.items() if key != "contract_version"},
        "cash_tendered": receipt["cash_tendered_vnd"],
        "client_fingerprint": "fsofr1:" + "0" * 64,
    }
    normal_payload.pop("cash_tendered_vnd")
    normal = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        headers={**auth(staff_token), "X-Offline-Lease-Token": lease["lease_token"]},
        json=normal_payload,
    )
    assert normal.status_code == 409
    assert normal.json()["detail"]["code"] == "OFFLINE_LEASE_EXPIRED"
    _TEST_MIGRATIONS.verify()


def test_tamper_then_recompute_hash_is_not_trusted_after_import(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=999_999_004)
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    tampered = json.loads(json.dumps(document))
    tampered["payload"]["receipt"]["items"][0]["product_name"] = "Đã bị sửa"
    _recompute_file_hash(tampered)
    attempt = _resolve(
        client,
        ctx,
        tampered,
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert attempt.status_code == 409
    assert attempt.json()["detail"]["code"] == "OFFLINE_RECOVERY_CONTENT_CONFLICT"
    assert _db_counts(ctx["shop_id"])["orders"] == 0


@pytest.mark.parametrize("fault_point", ["financial_rows_flushed", "original_tombstoned", "before_recovery_commit"])
def test_crash_checkpoints_rollback_everything(client, monkeypatch, fault_point):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=ctx["product"]["id"])
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    before = _db_counts(ctx["shop_id"])

    def crash(name):
        if name == fault_point:
            raise RuntimeError("injected recovery crash")

    monkeypatch.setattr(offline_recovery_service, "_recovery_checkpoint", crash)
    with pytest.raises(RuntimeError, match="injected recovery crash"):
        _resolve(client, ctx, document)
    after = _db_counts(ctx["shop_id"])
    assert after == before
    session = SessionLocal()
    try:
        registry = session.get(models.OfflineReceiptRegistry, receipt["offline_uuid"])
        assert (registry.state, registry.state_version, registry.order_id) == (
            "ABANDONED",
            0,
            None,
        )
    finally:
        session.close()


def test_audit_inventory_failure_and_stale_cas_are_atomic(client, monkeypatch):
    ctx = seller_with_shop(client)

    def staged(suffix):
        receipt = _v0_receipt(product_id=ctx["product"]["id"], name=suffix)
        document = _export(client, ctx, receipt).json()
        assert _import(client, ctx, document).status_code == 200
        return receipt, document

    receipt_a, doc_a = staged("audit")
    original_add = offline_recovery_service._add_recovery_action

    def fail_correct(*args, **kwargs):
        if kwargs.get("action_kind") == "CORRECT":
            raise RuntimeError("audit unavailable")
        return original_add(*args, **kwargs)

    monkeypatch.setattr(offline_recovery_service, "_add_recovery_action", fail_correct)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _resolve(client, ctx, doc_a)
    monkeypatch.setattr(offline_recovery_service, "_add_recovery_action", original_add)

    receipt_b, doc_b = staged("inventory")
    original_deduct = offline_recovery_service.offline_service._tru_ton_chiu_thieu

    def fail_inventory(*_args, **_kwargs):
        raise RuntimeError("inventory unavailable")

    monkeypatch.setattr(
        offline_recovery_service.offline_service,
        "_tru_ton_chiu_thieu",
        fail_inventory,
    )
    with pytest.raises(RuntimeError, match="inventory unavailable"):
        _resolve(client, ctx, doc_b)
    monkeypatch.setattr(
        offline_recovery_service.offline_service,
        "_tru_ton_chiu_thieu",
        original_deduct,
    )

    receipt_c, doc_c = staged("cas")
    stale = _resolve(client, ctx, doc_c, state_version=1)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "OFFLINE_RECOVERY_STATE_CONFLICT"
    assert _db_counts(ctx["shop_id"])["orders"] == 0
    session = SessionLocal()
    try:
        for original_uuid in (
            receipt_a["offline_uuid"],
            receipt_b["offline_uuid"],
            receipt_c["offline_uuid"],
        ):
            row = session.get(models.OfflineReceiptRegistry, original_uuid)
            assert row.state == "ABANDONED" and row.state_version == 0
    finally:
        session.close()


def test_concurrent_double_submit_one_financial_winner(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=ctx["product"]["id"])
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _n: _resolve(client, ctx, document), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    bodies = [response.json() for response in responses]
    assert sorted(body["created"] for body in bodies) == [False, True]
    assert len({body["order_id"] for body in bodies}) == 1
    counts = _db_counts(ctx["shop_id"])
    assert counts == {"orders": 1, "payments": 1, "correct": 1}


def test_import_validation_caps_and_cross_shop_fail_before_mutation(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=999_999_005)
    document = _export(client, ctx, receipt).json()
    before = _db_counts(ctx["shop_id"])

    malformed = client.post(
        f"/api/offline/recovery/{ctx['shop_id']}/import",
        headers=auth(ctx["token"]),
        content=b"{",
    )
    assert malformed.status_code == 422

    bad_hash = json.loads(json.dumps(document))
    bad_hash["sha256"] = "0" * 64
    assert _import(client, ctx, bad_hash).status_code == 422

    unknown = json.loads(json.dumps(document))
    unknown["version"] = 99
    _recompute_file_hash(unknown)
    version_response = _import(client, ctx, unknown)
    assert version_response.status_code == 422
    assert version_response.json()["detail"]["code"] == "OFFLINE_RECOVERY_VERSION_UNSUPPORTED"

    oversized = client.post(
        f"/api/offline/recovery/{ctx['shop_id']}/import",
        headers={**auth(ctx["token"]), "Content-Type": "application/json"},
        content=b"{" + b" " * (64 * 1024) + b"}",
    )
    assert oversized.status_code == 413

    too_many_lines = client.post(
        f"/api/offline/recovery/{ctx['shop_id']}/import",
        headers=auth(ctx["token"]),
        content=("\n" * 200 + "{}").encode(),
    )
    assert too_many_lines.status_code == 422

    too_many_items = json.loads(json.dumps(receipt))
    too_many_items["offline_uuid"] = f"many-{uuid.uuid4()}"
    too_many_items["items"] = too_many_items["items"] * 201
    over_items = _export(client, ctx, too_many_items)
    assert over_items.status_code == 422

    other = seller_with_shop(client)
    cross = _import(client, ctx, document, shop_id=other["shop_id"], token=other["token"])
    assert cross.status_code == 404
    assert _db_counts(ctx["shop_id"]) == before


def test_cross_shop_map_rejected_and_ton_am_cannot_acknowledge(client):
    ctx = seller_with_shop(client)
    other = seller_with_shop(client)
    missing = _v0_receipt(product_id=999_999_006)
    document = _export(client, ctx, missing).json()
    assert _import(client, ctx, document).status_code == 200
    cross_map = _resolve(
        client,
        ctx,
        document,
        line_resolutions=[
            {
                "item_ordinal": 1,
                "action": "MAP",
                "product_id": other["product"]["id"],
            }
        ],
    )
    assert cross_map.status_code == 409
    assert cross_map.json()["detail"]["code"] == "OFFLINE_RECOVERY_MAP_INVALID"

    shortage = _v0_receipt(
        product_id=ctx["product"]["id"], name=ctx["product"]["name"], quantity=11
    )
    shortage["cash_tendered_vnd"] = 1_100_000
    shortage_doc = _export(client, ctx, shortage).json()
    assert _import(client, ctx, shortage_doc).status_code == 200
    recovered = _resolve(client, ctx, shortage_doc)
    assert recovered.status_code == 200, recovered.text
    session = SessionLocal()
    try:
        issue = (
            session.query(models.OfflineReceiptIssue)
            .filter(
                models.OfflineReceiptIssue.order_id == recovered.json()["order_id"],
                models.OfflineReceiptIssue.issue_code == "TON_AM",
            )
            .one()
        )
        issue_id = issue.id
        version = issue.state_version
    finally:
        session.close()
    acknowledge = client.post(
        f"/api/orders/{ctx['shop_id']}/offline-issues/{issue_id}/acknowledge",
        headers=auth(ctx["token"]),
        json={"reason": "Không được click clear tồn âm", "state_version": version},
    )
    assert acknowledge.status_code == 409
    assert acknowledge.json()["detail"]["code"] == "OFFLINE_ISSUE_EVIDENCE_REQUIRED"
    _TEST_MIGRATIONS.verify()


def test_pre_registry_legacy_order_fences_import_without_second_financial_write(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(
        product_id=ctx["product"]["id"], name=ctx["product"]["name"]
    )
    _normal_ingest_v0(client, ctx, receipt)

    session = SessionLocal()
    try:
        durable_receipt = (
            session.query(models.OfflineReceipt)
            .filter(models.OfflineReceipt.offline_uuid == receipt["offline_uuid"])
            .one()
        )
        durable_registry = session.get(
            models.OfflineReceiptRegistry, receipt["offline_uuid"]
        )
        session.delete(durable_receipt)
        session.delete(durable_registry)
        session.commit()
        stock_after_sale = session.get(models.Product, ctx["product"]["id"]).stock
    finally:
        session.close()

    before = _db_counts(ctx["shop_id"])
    document = _export(client, ctx, receipt).json()

    def attempt(_n):
        return _import(client, ctx, document)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(attempt, range(2)))
    retry = _import(client, ctx, document)
    for response in [*attempts, retry]:
        assert response.status_code == 409
        assert (
            response.json()["detail"]["code"]
            == "OFFLINE_RECOVERY_PREEXISTING_ORDER"
        )
    direct_resolve = _resolve(client, ctx, document)
    assert direct_resolve.status_code == 409
    assert (
        direct_resolve.json()["detail"]["code"]
        == "OFFLINE_RECOVERY_PREEXISTING_ORDER"
    )
    assert _db_counts(ctx["shop_id"]) == before
    session = SessionLocal()
    try:
        assert session.get(models.Product, ctx["product"]["id"]).stock == stock_after_sale
        assert session.get(models.OfflineReceiptRegistry, receipt["offline_uuid"]) is None
    finally:
        session.close()


def test_pre_registry_legacy_mismatch_and_cross_shop_fail_closed(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(
        product_id=ctx["product"]["id"], name=ctx["product"]["name"]
    )
    _normal_ingest_v0(client, ctx, receipt)
    session = SessionLocal()
    try:
        session.query(models.OfflineReceipt).filter(
            models.OfflineReceipt.offline_uuid == receipt["offline_uuid"]
        ).delete()
        session.query(models.OfflineReceiptRegistry).filter(
            models.OfflineReceiptRegistry.offline_uuid == receipt["offline_uuid"]
        ).delete()
        session.commit()
    finally:
        session.close()

    mismatch = json.loads(json.dumps(receipt))
    mismatch["items"][0]["unit_price_vnd"] += 1
    mismatch["cash_tendered_vnd"] += 1
    mismatch_doc = _export(client, ctx, mismatch).json()
    blocked = _import(client, ctx, mismatch_doc)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "OFFLINE_RECOVERY_PREEXISTING_ORDER"

    other = seller_with_shop(client)
    cross = _import(
        client,
        other,
        mismatch_doc,
        shop_id=other["shop_id"],
        token=other["token"],
    )
    assert cross.status_code == 404
    assert cross.json()["detail"]["code"] == "OFFLINE_RECOVERY_NOT_FOUND"


def test_v1_inactive_same_shop_accept_unknown_preserves_scope_without_stock_or_cost(client):
    ctx = seller_with_shop(client)
    staff_token, lease = _issue_staff_lease(client, ctx)
    receipt = _recovery_v1_receipt(lease, ctx["product"])
    session = SessionLocal()
    try:
        product = session.get(models.Product, ctx["product"]["id"])
        before_stock = product.stock
        product.is_active = False
        session.commit()
    finally:
        session.close()

    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    recovered = _resolve(
        client,
        ctx,
        document,
        reason="Owner chấp nhận giá vốn chưa biết cho hàng inactive",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert recovered.status_code == 200, recovered.text
    session = SessionLocal()
    try:
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == recovered.json()["order_id"])
            .one()
        )
        snapshot = (
            session.query(models.OfflineReceiptItem)
            .filter(models.OfflineReceiptItem.order_item_id == line.id)
            .one()
        )
        product = session.get(models.Product, ctx["product"]["id"])
        assert line.product_id == snapshot.claimed_product_id == product.id
        assert (line.cost_known_qty, line.cost_unknown_qty, line.cost_basis_vnd) == (
            0,
            1,
            0,
        )
        assert product.stock == before_stock
        assert product.is_active is False
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()
    _TEST_MIGRATIONS.verify()


@pytest.mark.parametrize("identity_kind", ["missing", "deleted", "cross_shop"])
def test_v1_accept_unknown_missing_deleted_cross_shop_keeps_unverified_fk_null(
    client, identity_kind
):
    ctx = seller_with_shop(client)
    staff_token, lease = _issue_staff_lease(client, ctx)
    if identity_kind == "cross_shop":
        other = seller_with_shop(client)
        claimed = other["product"]
    elif identity_kind == "deleted":
        claimed = create_product(
            client,
            ctx["token"],
            ctx["shop_id"],
            _unique("Deleted recovery"),
            100_000,
            0,
            ctx["category_id"],
        )
        session = SessionLocal()
        try:
            session.delete(session.get(models.Product, claimed["id"]))
            session.commit()
        finally:
            session.close()
    else:
        claimed = {"id": 999_999_777, "name": "Never existed", "price": 100_000}
    receipt = _recovery_v1_receipt(lease, claimed)
    document = _export(client, ctx, receipt).json()
    assert _import(client, ctx, document).status_code == 200
    recovered = _resolve(
        client,
        ctx,
        document,
        reason="Owner chấp nhận identity chưa xác minh và giá vốn chưa biết",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert recovered.status_code == 200, recovered.text
    session = SessionLocal()
    try:
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == recovered.json()["order_id"])
            .one()
        )
        snapshot = (
            session.query(models.OfflineReceiptItem)
            .filter(models.OfflineReceiptItem.order_item_id == line.id)
            .one()
        )
        assert line.product_id is None
        assert snapshot.claimed_product_id == claimed["id"]
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()


def test_ingested_v0_catalog_map_is_in_place_idempotent_and_exact_once(client):
    ctx = seller_with_shop(client)
    target = _known_cost_product(client, ctx, quantity=5, unit_cost=30_000)
    receipt = _v0_receipt(product_id=999_999_880, quantity=2)
    original = _normal_ingest_v0(client, ctx, receipt)
    listed = client.get(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates",
        headers=auth(ctx["token"]),
    )
    assert listed.status_code == 200
    candidate = next(item for item in listed.json()["items"] if item["offline_uuid"] == receipt["offline_uuid"])
    assert candidate["direct_legacy_resolution"] is True
    assert candidate["issues"][0]["item_ordinal"] == 1
    assert "digest" not in str(candidate).lower()
    detail = client.get(
        f"/api/offline/recovery/{ctx['shop_id']}/candidates/{receipt['offline_uuid']}",
        headers=auth(ctx["token"]),
    )
    assert detail.status_code == 200
    assert detail.json()["direct_legacy_resolution"] is True
    before = _db_counts(ctx["shop_id"])

    def attempt(_n):
        return _resolve_ingested_direct(
            client,
            ctx,
            receipt["offline_uuid"],
            line_resolutions=[
                {"item_ordinal": 1, "action": "MAP", "product_id": target["id"]}
            ],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, range(2)))
    retry = attempt(3)
    assert all(response.status_code == 200 for response in [*responses, retry])
    assert {response.json()["order_id"] for response in [*responses, retry]} == {
        original["order_id"]
    }
    assert sorted(response.json()["created"] for response in responses) == [False, False]
    conflicting_retry = _resolve_ingested_direct(
        client,
        ctx,
        receipt["offline_uuid"],
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert conflicting_retry.status_code == 409
    assert (
        conflicting_retry.json()["detail"]["code"]
        == "OFFLINE_RECOVERY_STATE_CONFLICT"
    )
    assert _db_counts(ctx["shop_id"]) == {
        **before,
        "correct": before["correct"],
    }
    session = SessionLocal()
    try:
        product = session.get(models.Product, target["id"])
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == original["order_id"])
            .one()
        )
        issue = (
            session.query(models.OfflineReceiptIssue)
            .filter(
                models.OfflineReceiptIssue.order_id == original["order_id"],
                models.OfflineReceiptIssue.issue_code == "SP_KHONG_CON",
            )
            .one()
        )
        actions = (
            session.query(models.OfflineRecoveryAction)
            .filter(
                models.OfflineRecoveryAction.original_offline_uuid
                == receipt["offline_uuid"],
                models.OfflineRecoveryAction.action_kind == "LEGACY_INGEST",
            )
            .count()
        )
        assert product.stock == 3
        assert (line.product_id, line.cost_known_qty, line.cost_unknown_qty) == (
            target["id"],
            2,
            0,
        )
        assert line.cost_basis_vnd == 60_000
        assert issue.state == "RESOLVED"
        assert issue.resolution_kind == "OWNER_MAP_PRODUCT"
        assert actions == 1
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()


def test_ingested_v0_catalog_accept_unknown_is_nonfinancial_and_audited(client):
    ctx = seller_with_shop(client)
    receipt = _v0_receipt(product_id=999_999_881, quantity=2)
    original = _normal_ingest_v0(client, ctx, receipt)
    before = _db_counts(ctx["shop_id"])
    accepted = _resolve_ingested_direct(
        client,
        ctx,
        receipt["offline_uuid"],
        reason="Owner chấp nhận giá vốn chưa biết trên đơn đã ghi",
        line_resolutions=[{"item_ordinal": 1, "action": "ACCEPT_UNKNOWN"}],
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["order_id"] == original["order_id"]
    assert accepted.json()["created"] is False
    assert _db_counts(ctx["shop_id"]) == before
    session = SessionLocal()
    try:
        issue = (
            session.query(models.OfflineReceiptIssue)
            .filter(
                models.OfflineReceiptIssue.order_id == original["order_id"],
                models.OfflineReceiptIssue.issue_code == "SP_KHONG_CON",
            )
            .one()
        )
        action = (
            session.query(models.OfflineRecoveryAction)
            .filter(
                models.OfflineRecoveryAction.original_offline_uuid
                == receipt["offline_uuid"],
                models.OfflineRecoveryAction.action_kind == "LEGACY_INGEST",
            )
            .one()
        )
        assert issue.state == "RESOLVED"
        assert issue.resolution_kind == "OWNER_ACCEPT_UNKNOWN_COST"
        assert session.get(models.SystemLog, action.system_log_id) is not None
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()


@pytest.mark.parametrize(
    "fault_kind", ["audit", "inventory", "ingested_catalog_registry_cas"]
)
def test_ingested_v0_catalog_faults_rollback_and_retry_exact_once(
    client, monkeypatch, fault_kind
):
    ctx = seller_with_shop(client)
    target = _known_cost_product(client, ctx, quantity=4, unit_cost=25_000)
    receipt = _v0_receipt(product_id=999_999_882, quantity=2)
    original = _normal_ingest_v0(client, ctx, receipt)
    before_counts = _db_counts(ctx["shop_id"])
    session = SessionLocal()
    try:
        before_stock = session.get(models.Product, target["id"]).stock
    finally:
        session.close()

    original_action = offline_recovery_service._add_recovery_action
    original_inventory = offline_recovery_service.offline_service._tru_ton_chiu_thieu
    original_checkpoint = offline_recovery_service._recovery_checkpoint
    if fault_kind == "audit":
        def fail_action(*_args, **_kwargs):
            raise RuntimeError("injected ingested audit failure")

        monkeypatch.setattr(
            offline_recovery_service, "_add_recovery_action", fail_action
        )
        expected = "injected ingested audit failure"
    elif fault_kind == "inventory":
        def fail_inventory(*_args, **_kwargs):
            raise RuntimeError("injected ingested inventory failure")

        monkeypatch.setattr(
            offline_recovery_service.offline_service,
            "_tru_ton_chiu_thieu",
            fail_inventory,
        )
        expected = "injected ingested inventory failure"
    else:
        def fail_checkpoint(name):
            if name == fault_kind:
                raise RuntimeError("injected ingested CAS failure")

        monkeypatch.setattr(
            offline_recovery_service, "_recovery_checkpoint", fail_checkpoint
        )
        expected = "injected ingested CAS failure"

    decisions = [{"item_ordinal": 1, "action": "MAP", "product_id": target["id"]}]
    with pytest.raises(RuntimeError, match=expected):
        _resolve_ingested_direct(
            client,
            ctx,
            receipt["offline_uuid"],
            line_resolutions=decisions,
        )

    session = SessionLocal()
    try:
        line = (
            session.query(models.OrderItem)
            .filter(models.OrderItem.order_id == original["order_id"])
            .one()
        )
        issue = (
            session.query(models.OfflineReceiptIssue)
            .filter(
                models.OfflineReceiptIssue.order_id == original["order_id"],
                models.OfflineReceiptIssue.issue_code == "SP_KHONG_CON",
            )
            .one()
        )
        registry = session.get(models.OfflineReceiptRegistry, receipt["offline_uuid"])
        assert session.get(models.Product, target["id"]).stock == before_stock
        assert line.product_id is None
        assert issue.state == "OPEN" and issue.state_version == 0
        assert registry.state == "INGESTED" and registry.state_version == 0
        assert (
            session.query(models.OfflineRecoveryAction)
            .filter(
                models.OfflineRecoveryAction.original_offline_uuid
                == receipt["offline_uuid"],
                models.OfflineRecoveryAction.action_kind == "LEGACY_INGEST",
            )
            .count()
            == 0
        )
    finally:
        session.close()
    assert _db_counts(ctx["shop_id"]) == before_counts

    monkeypatch.setattr(
        offline_recovery_service, "_add_recovery_action", original_action
    )
    monkeypatch.setattr(
        offline_recovery_service.offline_service,
        "_tru_ton_chiu_thieu",
        original_inventory,
    )
    monkeypatch.setattr(
        offline_recovery_service, "_recovery_checkpoint", original_checkpoint
    )
    retry = _resolve_ingested_direct(
        client,
        ctx,
        receipt["offline_uuid"],
        line_resolutions=decisions,
    )
    assert retry.status_code == 200, retry.text
    session = SessionLocal()
    try:
        assert session.get(models.Product, target["id"]).stock == before_stock - 2
    finally:
        session.close()
    _TEST_MIGRATIONS.verify()
