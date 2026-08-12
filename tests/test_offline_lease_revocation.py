"""I09-D: heartbeat state, reclaim CAS, revoke và atomic audit."""

from __future__ import annotations

import datetime
import hashlib

import pytest
from fastapi import HTTPException

from conftest import admin_token, auth, new_staff, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import offline_lease_service


@pytest.fixture(autouse=True)
def lease_enabled(monkeypatch):
    monkeypatch.setattr(
        offline_lease_service.config,
        "OFFLINE_LEASE_ISSUANCE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        offline_lease_service.subscription_service,
        "require_pro",
        lambda *_args, **_kwargs: {"can_use_pro": True},
    )


def _issue(client, ctx, *, token=None, device_id="device-revoke"):
    response = client.post(
        "/api/offline/leases",
        json={"shop_id": ctx["shop_id"], "device_id": device_id},
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _heartbeat(client, jwt_token, lease, raw_token=None):
    return client.post(
        f"/api/offline/leases/{lease['lease_id']}/heartbeat",
        headers={
            **auth(jwt_token),
            "X-Offline-Lease-Token": raw_token or lease["lease_token"],
        },
    )


def _expiry(lease: dict) -> datetime.datetime:
    return datetime.datetime.strptime(
        lease["expires_at"], "%Y-%m-%d %H:%M:%S.%f"
    )


def test_heartbeat_active_sync_only_expired_and_revoked_with_fake_clock(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    now = datetime.datetime.utcnow().replace(microsecond=123456)
    monkeypatch.setattr(offline_lease_service, "_utcnow", lambda: now)

    active = _issue(client, ctx, device_id="device-active")
    assert _heartbeat(client, ctx["token"], active).json()["status"] == "ACTIVE"

    grace = _issue(client, ctx, device_id="device-grace")
    monkeypatch.setattr(
        offline_lease_service,
        "_utcnow",
        lambda: _expiry(grace) + datetime.timedelta(hours=1),
    )
    grace_response = _heartbeat(client, ctx["token"], grace)
    assert grace_response.status_code == 200
    assert grace_response.json()["status"] == "SYNC_ONLY"

    expired = _issue(client, ctx, device_id="device-expired")
    monkeypatch.setattr(
        offline_lease_service,
        "_utcnow",
        lambda: _expiry(expired) + datetime.timedelta(hours=73),
    )
    expired_response = _heartbeat(client, ctx["token"], expired)
    assert expired_response.status_code == 403
    assert expired_response.json()["detail"]["code"] == offline_lease_service.ERROR_EXPIRED

    revoked = _issue(client, ctx, device_id="device-revoked")
    revoke_response = client.request(
        "DELETE",
        f"/api/offline/leases/{revoked['lease_id']}",
        json={"reason": "Thiết bị đã bị thất lạc tại cửa hàng"},
        headers=auth(ctx["token"]),
    )
    assert revoke_response.status_code == 200
    heartbeat = _heartbeat(client, ctx["token"], revoked)
    assert heartbeat.status_code == 403
    assert heartbeat.json()["detail"]["code"] == offline_lease_service.ERROR_REVOKED


def test_reclaim_rotates_active_and_grace_old_token_dies(client, monkeypatch):
    ctx = seller_with_shop(client)
    active = _issue(client, ctx, device_id="device-reclaim-active")
    reclaimed = client.post(
        f"/api/offline/leases/{active['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert reclaimed.status_code == 200, reclaimed.text
    body = reclaimed.json()
    assert body["status"] == "ACTIVE"
    assert body["state_version"] == 1
    assert body["lease_token"] != active["lease_token"]
    assert _heartbeat(
        client, ctx["token"], active, active["lease_token"]
    ).status_code == 403
    assert _heartbeat(client, ctx["token"], body).status_code == 200

    grace = _issue(client, ctx, device_id="device-reclaim-grace")
    monkeypatch.setattr(
        offline_lease_service,
        "_utcnow",
        lambda: _expiry(grace) + datetime.timedelta(hours=1),
    )
    grace_reclaim = client.post(
        f"/api/offline/leases/{grace['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert grace_reclaim.status_code == 200
    assert grace_reclaim.json()["status"] == "SYNC_ONLY"


def test_reclaim_denied_for_revoked_expired_other_user_and_stale_cas(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    lease = _issue(client, ctx, device_id="device-reclaim-denied")
    _, other_staff = new_staff(client, ctx, "CASHIER")
    other = client.post(
        f"/api/offline/leases/{lease['lease_id']}/reclaim",
        headers=auth(other_staff),
    )
    assert other.status_code == 403
    assert other.json()["detail"]["code"] == offline_lease_service.ERROR_NOT_YOURS

    expired = _issue(client, ctx, device_id="device-reclaim-expired")
    monkeypatch.setattr(
        offline_lease_service,
        "_utcnow",
        lambda: _expiry(expired) + datetime.timedelta(hours=73),
    )
    denied = client.post(
        f"/api/offline/leases/{expired['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == offline_lease_service.ERROR_RECLAIM_DENIED

    revoked = _issue(client, ctx, device_id="device-reclaim-revoked")
    client.request(
        "DELETE",
        f"/api/offline/leases/{revoked['lease_id']}",
        json={"reason": "Credential đã thu hồi không được reclaim"},
        headers=auth(ctx["token"]),
    )
    revoked_denied = client.post(
        f"/api/offline/leases/{revoked['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert revoked_denied.status_code == 403
    assert revoked_denied.json()["detail"]["code"] == (
        offline_lease_service.ERROR_RECLAIM_DENIED
    )

    monkeypatch.setattr(offline_lease_service, "_utcnow", datetime.datetime.utcnow)
    stale = _issue(client, ctx, device_id="device-reclaim-stale")
    real_lock = offline_lease_service.order_service._lock_shop_for_order

    def inject_stale(db, shop_id):
        with SessionLocal() as winner:
            winner.execute(
                offline_lease_service.text(
                    "UPDATE offline_leases SET secret_sha256=:digest, "
                    "state_version=state_version+1 WHERE lease_id=:lease_id"
                ),
                {
                    "digest": hashlib.sha256(b"concurrent-winner").hexdigest(),
                    "lease_id": stale["lease_id"],
                },
            )
            winner.commit()
        real_lock(db, shop_id)

    monkeypatch.setattr(
        offline_lease_service.order_service,
        "_lock_shop_for_order",
        inject_stale,
    )
    conflict = client.post(
        f"/api/offline/leases/{stale['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == offline_lease_service.ERROR_STATE_CONFLICT
    with SessionLocal() as session:
        winner = session.get(models.OfflineLease, stale["lease_id"])
        assert winner.state_version == 1
        assert winner.secret_sha256 == hashlib.sha256(b"concurrent-winner").hexdigest()


def test_owner_admin_revoke_no_token_staff_denied_and_retry_idempotent(client):
    ctx = seller_with_shop(client)
    lease = _issue(client, ctx)
    _, staff_token = new_staff(client, ctx, "MANAGER")
    denied = client.request(
        "DELETE",
        f"/api/offline/leases/{lease['lease_id']}",
        json={"reason": "Nhân viên không được tự thu hồi lease"},
        headers=auth(staff_token),
    )
    assert denied.status_code == 403

    first = client.request(
        "DELETE",
        f"/api/offline/leases/{lease['lease_id']}",
        json={"reason": "Thiết bị quầy chính đã bị thất lạc"},
        headers=auth(ctx["token"]),
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "REVOKED"
    assert "lease_token" not in first.json()

    repeated = client.request(
        "DELETE",
        f"/api/offline/leases/{lease['lease_id']}",
        json={"reason": "Lý do mới không được ghi đè lịch sử cũ"},
        headers=auth(ctx["token"]),
    )
    assert repeated.status_code == 200
    assert repeated.json()["state_version"] == first.json()["state_version"]
    with SessionLocal() as session:
        stored = session.get(models.OfflineLease, lease["lease_id"])
        assert stored.revoke_reason == "Thiết bị quầy chính đã bị thất lạc"
        assert (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == offline_lease_service.AUDIT_REVOKE,
                models.SystemLog.details.contains(lease["lease_id"]),
            )
            .count()
            == 1
        )

    admin_lease = _issue(client, ctx, device_id="device-admin-revoke")
    admin_revoke = client.request(
        "DELETE",
        f"/api/offline/leases/{admin_lease['lease_id']}",
        json={"reason": "ADMIN thu hồi thiết bị bị báo mất"},
        headers=auth(admin_token(client)),
    )
    assert admin_revoke.status_code == 200


def test_revoked_capability_ignores_backdated_claim(client):
    ctx = seller_with_shop(client)
    lease = _issue(client, ctx, device_id="device-backdate")
    client.request(
        "DELETE",
        f"/api/offline/leases/{lease['lease_id']}",
        json={"reason": "Thu hồi trước khi thử receipt backdate"},
        headers=auth(ctx["token"]),
    )
    heartbeat = _heartbeat(client, ctx["token"], lease)
    assert heartbeat.status_code == 403
    assert heartbeat.json()["detail"]["code"] == offline_lease_service.ERROR_REVOKED
    reclaim = client.post(
        f"/api/offline/leases/{lease['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert reclaim.status_code == 403
    assert reclaim.json()["detail"]["code"] == (
        offline_lease_service.ERROR_RECLAIM_DENIED
    )
    with SessionLocal() as session:
        user = session.query(models.User).filter(models.User.username == ctx["username"]).one()
        # Seam cố ý không nhận sold_at; state revoked hiện tại quyết định trước
        # mọi time-contract/financial write của I09-E+B2.
        with pytest.raises(HTTPException) as exc:
            offline_lease_service.authorize_normal_v1_capability(
                session,
                user,
                shop_id=ctx["shop_id"],
                lease_id=lease["lease_id"],
                lease_token=lease["lease_token"],
                device_id="device-backdate",
                offline_session_id=lease["lease_id"],
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == offline_lease_service.ERROR_REVOKED


def test_beyond_grace_normal_seam_is_409_while_endpoints_keep_403(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    lease = _issue(client, ctx, device_id="device-normal-expired")
    monkeypatch.setattr(
        offline_lease_service,
        "_utcnow",
        lambda: _expiry(lease) + datetime.timedelta(hours=73),
    )

    heartbeat = _heartbeat(client, ctx["token"], lease)
    assert heartbeat.status_code == 403
    assert heartbeat.json()["detail"]["code"] == offline_lease_service.ERROR_EXPIRED
    reclaim = client.post(
        f"/api/offline/leases/{lease['lease_id']}/reclaim",
        headers=auth(ctx["token"]),
    )
    assert reclaim.status_code == 403
    assert reclaim.json()["detail"]["code"] == (
        offline_lease_service.ERROR_RECLAIM_DENIED
    )

    with SessionLocal() as session:
        user = (
            session.query(models.User)
            .filter(models.User.username == ctx["username"])
            .one()
        )
        with pytest.raises(HTTPException) as exc:
            offline_lease_service.authorize_normal_v1_capability(
                session,
                user,
                shop_id=ctx["shop_id"],
                lease_id=lease["lease_id"],
                lease_token=lease["lease_token"],
                device_id="device-normal-expired",
                offline_session_id=lease["lease_id"],
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == offline_lease_service.ERROR_EXPIRED


@pytest.mark.parametrize("operation", ["issue", "reclaim", "revoke"])
def test_audit_failure_rolls_back_every_mutation(client, monkeypatch, operation):
    ctx = seller_with_shop(client)
    lease = None if operation == "issue" else _issue(client, ctx, device_id=f"fault-{operation}")
    before_count = None
    before_digest = None
    if lease is not None:
        with SessionLocal() as session:
            stored = session.get(models.OfflineLease, lease["lease_id"])
            before_digest = stored.secret_sha256
            before_count = int(stored.state_version)

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("injected offline lease audit failure")

    monkeypatch.setattr(offline_lease_service, "_add_audit", fail_audit)
    with pytest.raises(RuntimeError, match="injected offline lease audit failure"):
        if operation == "issue":
            with SessionLocal() as session:
                user = session.query(models.User).filter(
                    models.User.username == ctx["username"]
                ).one()
                offline_lease_service.issue_lease(
                    session,
                    user,
                    shop_id=ctx["shop_id"],
                    device_id="fault-issue",
                )
        elif operation == "reclaim":
            with SessionLocal() as session:
                user = session.query(models.User).filter(
                    models.User.username == ctx["username"]
                ).one()
                offline_lease_service.reclaim(
                    session, user, lease_id=lease["lease_id"]
                )
        else:
            with SessionLocal() as session:
                user = session.query(models.User).filter(
                    models.User.username == ctx["username"]
                ).one()
                offline_lease_service.revoke(
                    session,
                    user,
                    lease_id=lease["lease_id"],
                    reason="Fault injection phải rollback revoke",
                )

    with SessionLocal() as session:
        if operation == "issue":
            assert (
                session.query(models.OfflineLease)
                .filter(models.OfflineLease.device_id == "fault-issue")
                .count()
                == 0
            )
        else:
            stored = session.get(models.OfflineLease, lease["lease_id"])
            assert int(stored.state_version) == before_count
            assert stored.secret_sha256 == before_digest
            assert stored.revoked_at is None
