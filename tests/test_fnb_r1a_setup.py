import uuid

from conftest import (
    auth,
    create_fnb_area,
    create_fnb_table,
    enable_fnb,
    new_staff,
    seller_with_shop,
)
from fselling import models


def _operation(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _floor(client, ctx: dict, **params):
    return client.get(
        "/api/fnb/floor",
        params={"shop_id": ctx["shop_id"], **params},
        headers=auth(ctx["token"]),
    )


def test_fnb_is_off_by_default_and_only_owner_can_enable(client):
    ctx = seller_with_shop(client)
    off = _floor(client, ctx)
    assert off.status_code == 409
    assert off.json()["detail"]["code"] == "FNB_DISABLED"

    _, cashier = new_staff(client, ctx, "CASHIER")
    denied = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={
            "enabled": True,
            "expected_revision": 0,
            "operation_id": "enable-fnb-staff-0001",
        },
        headers=auth(cashier),
    )
    assert denied.status_code in {403, 404}

    enabled = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={
            "enabled": True,
            "expected_revision": 0,
            "operation_id": "enable-fnb-owner-0001",
        },
        headers=auth(ctx["token"]),
    )
    assert enabled.status_code == 200
    assert enabled.json() == {
        "shop_id": ctx["shop_id"],
        "fnb_enabled": True,
        "fnb_revision": 1,
    }


def test_area_table_floor_is_tenant_scoped_and_stably_sorted(client):
    first = seller_with_shop(client)
    second = seller_with_shop(client)
    enable_fnb(client, first)
    enable_fnb(client, second)
    patio = create_fnb_area(client, first, "Ngoài sân", sort_order=20)
    hall = create_fnb_area(client, first, "Trong nhà", sort_order=10)
    table_2 = create_fnb_table(client, first, hall["id"], "Bàn 2", sort_order=20)
    table_1 = create_fnb_table(client, first, hall["id"], "Bàn 1", sort_order=10)

    body = _floor(client, first).json()
    assert [area["id"] for area in body["areas"]] == [hall["id"], patio["id"]]
    assert [row["id"] for row in body["areas"][0]["tables"]] == [
        table_1["id"],
        table_2["id"],
    ]
    assert body["areas"][0]["tables"][0]["state"] == "EMPTY"
    assert "cost_price" not in str(body)

    cross = client.get(
        "/api/fnb/floor",
        params={"shop_id": first["shop_id"]},
        headers=auth(second["token"]),
    )
    assert cross.status_code == 403


def test_setup_normalizes_names_and_omits_inactive_rows_without_deleting_them(
    client, db
):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx, "  Trong   nhà  ")
    assert area["name"] == "Trong nhà"

    duplicate_area = client.post(
        "/api/fnb/areas",
        json={
            "shop_id": ctx["shop_id"],
            "name": "TRONG NHÀ",
            "expected_revision": area["fnb_revision"],
            "operation_id": _operation("duplicate-area"),
        },
        headers=auth(ctx["token"]),
    )
    assert duplicate_area.status_code == 409
    assert duplicate_area.json()["detail"]["code"] == "FNB_NAME_EXISTS"

    table = create_fnb_table(client, ctx, area["id"], "  Bàn   1  ")
    duplicate_table = client.post(
        "/api/fnb/tables",
        json={
            "shop_id": ctx["shop_id"],
            "area_id": area["id"],
            "name": "BÀN 1",
            "expected_revision": table["fnb_revision"],
            "operation_id": _operation("duplicate-table"),
        },
        headers=auth(ctx["token"]),
    )
    assert duplicate_table.status_code == 409
    assert duplicate_table.json()["detail"]["code"] == "FNB_NAME_EXISTS"

    hidden_table = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json={
            "active": False,
            "expected_revision": table["fnb_revision"],
            "expected_state_version": table["state_version"],
            "operation_id": _operation("hide-table"),
        },
        headers=auth(ctx["token"]),
    )
    assert hidden_table.status_code == 200, hidden_table.text
    hidden_area = client.patch(
        f"/api/fnb/areas/{area['id']}",
        json={
            "active": False,
            "expected_revision": hidden_table.json()["fnb_revision"],
            "operation_id": _operation("hide-area"),
        },
        headers=auth(ctx["token"]),
    )
    assert hidden_area.status_code == 200, hidden_area.text
    assert _floor(client, ctx).json()["areas"] == []
    db.expire_all()
    assert db.get(models.FnbArea, area["id"]) is not None
    assert db.get(models.FnbTable, table["id"]) is not None


def test_role_permissions_and_cross_tenant_ids_do_not_leak(client):
    ctx = seller_with_shop(client)
    other = seller_with_shop(client)
    enable_fnb(client, ctx)
    enable_fnb(client, other)
    area = create_fnb_area(client, ctx)
    _, cashier = new_staff(client, ctx, "CASHIER")
    _, manager = new_staff(client, ctx, "MANAGER")
    _, warehouse = new_staff(client, ctx, "WAREHOUSE")

    assert _floor(client, {**ctx, "token": cashier}).status_code == 200
    floor = _floor(client, ctx).json()
    cashier_create = client.post(
        "/api/fnb/areas",
        json={
            "shop_id": ctx["shop_id"],
            "name": "Quầy",
            "expected_revision": floor["fnb_revision"],
            "operation_id": _operation("cashier-area"),
        },
        headers=auth(cashier),
    )
    assert cashier_create.status_code == 403

    manager_create = client.post(
        "/api/fnb/areas",
        json={
            "shop_id": ctx["shop_id"],
            "name": "Lầu",
            "expected_revision": floor["fnb_revision"],
            "operation_id": _operation("manager-area"),
        },
        headers=auth(manager),
    )
    assert manager_create.status_code == 200, manager_create.text
    assert _floor(client, {**ctx, "token": warehouse}).status_code == 403

    cross_update = client.patch(
        f"/api/fnb/areas/{area['id']}",
        json={
            "name": "Đoán ID",
            "expected_revision": 0,
            "operation_id": _operation("cross-area"),
        },
        headers=auth(other["token"]),
    )
    assert cross_update.status_code == 404
    own_floor = _floor(client, other).json()
    cross_area_table = client.post(
        "/api/fnb/tables",
        json={
            "shop_id": other["shop_id"],
            "area_id": area["id"],
            "name": "Bàn lạ",
            "expected_revision": own_floor["fnb_revision"],
            "operation_id": _operation("cross-table"),
        },
        headers=auth(other["token"]),
    )
    assert cross_area_table.status_code == 404


def test_floor_poll_no_change_and_stale_revision_is_atomic(client, db):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx, "Khu cũ")
    unchanged = _floor(client, ctx, after_revision=area["fnb_revision"])
    assert unchanged.status_code == 200
    assert unchanged.json() == {
        "changed": False,
        "fnb_revision": area["fnb_revision"],
    }

    stale = client.patch(
        f"/api/fnb/areas/{area['id']}",
        json={
            "name": "Tên không được ghi",
            "expected_revision": area["fnb_revision"] - 1,
            "operation_id": _operation("stale-area"),
        },
        headers=auth(ctx["token"]),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "FNB_FLOOR_CHANGED",
        "message": "Sơ đồ bàn vừa được cập nhật",
        "revision": area["fnb_revision"],
    }
    db.expire_all()
    assert db.get(models.FnbArea, area["id"]).name == "Khu cũ"


def test_committed_operation_retry_is_stable_and_reuse_is_rejected(client):
    ctx = seller_with_shop(client)
    payload = {
        "enabled": True,
        "expected_revision": 0,
        "operation_id": _operation("stable-enable"),
    }
    first = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == 200
    create_fnb_area(client, ctx)

    retry = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()

    reused = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={**payload, "enabled": False},
        headers=auth(ctx["token"]),
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "FNB_OPERATION_REUSED"


def test_table_revision_idempotency_and_inactive_area_gate(client):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx)
    table = create_fnb_table(client, ctx, area["id"])
    operation_id = _operation("rename-table")
    payload = {
        "name": "Bàn mới",
        "expected_revision": table["fnb_revision"],
        "expected_state_version": table["state_version"],
        "operation_id": operation_id,
    }
    first = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == 200, first.text
    spare = create_fnb_area(client, ctx, "Khu đóng")
    retry = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()
    reused = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json={**payload, "name": "Tên khác"},
        headers=auth(ctx["token"]),
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "FNB_OPERATION_REUSED"

    current_revision = _floor(client, ctx).json()["fnb_revision"]
    stale_state = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json={
            "sort_order": 9,
            "expected_revision": current_revision,
            "expected_state_version": table["state_version"],
            "operation_id": _operation("stale-table-state"),
        },
        headers=auth(ctx["token"]),
    )
    assert stale_state.status_code == 409
    assert stale_state.json()["detail"]["code"] == "FNB_TABLE_CHANGED"

    hidden = client.patch(
        f"/api/fnb/areas/{spare['id']}",
        json={
            "active": False,
            "expected_revision": current_revision,
            "operation_id": _operation("hide-spare-area"),
        },
        headers=auth(ctx["token"]),
    )
    assert hidden.status_code == 200, hidden.text
    blocked = client.post(
        "/api/fnb/tables",
        json={
            "shop_id": ctx["shop_id"],
            "area_id": spare["id"],
            "name": "Không tạo",
            "expected_revision": hidden.json()["fnb_revision"],
            "operation_id": _operation("inactive-area-table"),
        },
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "FNB_AREA_INACTIVE"


def test_occupied_table_cannot_be_deactivated_or_moved(client, db):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    first_area = create_fnb_area(client, ctx, "Khu 1")
    second_area = create_fnb_area(client, ctx, "Khu 2")
    table = create_fnb_table(client, ctx, first_area["id"])
    user = db.query(models.User).filter(models.User.username == ctx["username"]).one()
    session = models.FnbServiceSession(
        shop_id=ctx["shop_id"], status="OPEN", opened_by_user_id=user.id
    )
    db.add(session)
    db.flush()
    db.add(models.FnbSessionTable(session_id=session.id, table_id=table["id"]))
    db.commit()
    revision = _floor(client, ctx).json()["fnb_revision"]

    for change in ({"active": False}, {"area_id": second_area["id"]}):
        blocked = client.patch(
            f"/api/fnb/tables/{table['id']}",
            json={
                **change,
                "expected_revision": revision,
                "expected_state_version": table["state_version"],
                "operation_id": _operation("occupied-table"),
            },
            headers=auth(ctx["token"]),
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "FNB_TABLE_OCCUPIED"


def test_disable_rejects_active_session_then_preserves_closed_history(client, db):
    ctx = seller_with_shop(client)
    enabled = enable_fnb(client, ctx)
    user = db.query(models.User).filter(models.User.username == ctx["username"]).one()
    session = models.FnbServiceSession(
        shop_id=ctx["shop_id"], status="OPEN", opened_by_user_id=user.id
    )
    db.add(session)
    db.commit()

    operation_id = _operation("disable-active")
    blocked = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={
            "enabled": False,
            "expected_revision": enabled["fnb_revision"],
            "operation_id": operation_id,
        },
        headers=auth(ctx["token"]),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "FNB_ACTIVE_SESSION"

    db.expire_all()
    session = db.get(models.FnbServiceSession, session.id)
    session.status = "CLOSED"
    db.commit()
    disabled = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={
            "enabled": False,
            "expected_revision": enabled["fnb_revision"],
            "operation_id": operation_id,
        },
        headers=auth(ctx["token"]),
    )
    assert disabled.status_code == 200, disabled.text
    db.expire_all()
    assert db.get(models.FnbServiceSession, session.id).status == "CLOSED"


def test_hard_delete_shop_is_blocked_after_fnb_history(client):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    create_fnb_area(client, ctx)
    denied = client.delete(
        f"/api/shops/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert denied.status_code == 409
    assert "Khóa" in denied.json()["detail"]


def test_hard_delete_product_is_blocked_after_fnb_line_history(client, db):
    ctx = seller_with_shop(client)
    user = db.query(models.User).filter(models.User.username == ctx["username"]).one()
    session = models.FnbServiceSession(
        shop_id=ctx["shop_id"], status="CLOSED", opened_by_user_id=user.id
    )
    db.add(session)
    db.flush()
    db.add(
        models.FnbSessionLine(
            session_id=session.id,
            product_id=ctx["product"]["id"],
            product_name=ctx["product"]["name"],
            unit_price_vnd=int(ctx["product"]["price"]),
            quantity=1,
            created_by_user_id=user.id,
        )
    )
    db.commit()

    denied = client.delete(
        f"/api/products/{ctx['product']['id']}", headers=auth(ctx["token"])
    )
    assert denied.status_code == 409
    assert "Ẩn" in denied.json()["detail"]
