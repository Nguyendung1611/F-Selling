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


def op(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_send_is_atomic_idempotent_and_station_scoped(client, db):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx)
    table = create_fnb_table(client, ctx, area["id"])
    headers = auth(ctx["token"])

    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]}, headers=headers).json()
    station = client.patch(
        f"/api/fnb/menu-items/{ctx['product']['id']}/station",
        json={
            "station": "KITCHEN",
            "expected_revision": floor["fnb_revision"],
            "operation_id": op("station"),
        },
        headers=headers,
    )
    assert station.status_code == 200, station.text
    products = client.get(
        f"/api/products/{ctx['shop_id']}", headers=headers
    ).json()
    assert next(row for row in products if row["id"] == ctx["product"]["id"])[
        "fnb_station"
    ] == "KITCHEN"

    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]}, headers=headers).json()
    current_table = floor["areas"][0]["tables"][0]
    session = client.post(
        "/api/fnb/sessions",
        json={
            "shop_id": ctx["shop_id"],
            "table_id": table["id"],
            "expected_revision": floor["fnb_revision"],
            "expected_table_version": current_table["state_version"],
            "operation_id": op("open"),
        },
        headers=headers,
    ).json()
    session = client.post(
        f"/api/fnb/sessions/{session['id']}/lines",
        json={
            "product_id": ctx["product"]["id"],
            "quantity": 2,
            "note": "ít cay",
            "expected_revision": session["revision"],
            "operation_id": op("line"),
        },
        headers=headers,
    ).json()
    assert session["lines"][0]["station"] == "KITCHEN"
    send_operation = op("send")
    payload = {"expected_revision": session["revision"], "operation_id": send_operation}
    sent = client.post(
        f"/api/fnb/sessions/{session['id']}/send", json=payload, headers=headers
    )
    assert sent.status_code == 200, sent.text
    result = sent.json()
    assert result["unsent_quantity"] == 0
    assert result["lines"][0]["sent_quantity"] == 2
    assert len(result["tickets"]) == 1
    assert result["tickets"][0]["station"] == "KITCHEN"

    retry = client.post(
        f"/api/fnb/sessions/{session['id']}/send", json=payload, headers=headers
    )
    assert retry.status_code == 200
    assert retry.json() == result
    db.expire_all()
    assert db.get(models.Product, ctx["product"]["id"]).stock == 8
    assert db.query(models.FnbKitchenTicket).filter_by(
        shop_id=ctx["shop_id"]
    ).count() == 1
    assert db.query(models.FnbStockAllocation).filter_by(
        shop_id=ctx["shop_id"]
    ).count() == 1

    kitchen = client.get(
        "/api/fnb/stations/KITCHEN/tickets",
        params={"shop_id": ctx["shop_id"]},
        headers=headers,
    )
    bar = client.get(
        "/api/fnb/stations/BAR/tickets",
        params={"shop_id": ctx["shop_id"]},
        headers=headers,
    )
    assert kitchen.status_code == bar.status_code == 200
    assert [row["id"] for row in kitchen.json()["tickets"]] == [result["tickets"][0]["id"]]
    assert bar.json()["tickets"] == []

    _, kitchen_token = new_staff(client, ctx, "KITCHEN")
    kitchen_headers = auth(kitchen_token)
    assert client.get(
        "/api/fnb/stations/KITCHEN/tickets",
        params={"shop_id": ctx["shop_id"]},
        headers=kitchen_headers,
    ).status_code == 200
    assert client.get(
        "/api/fnb/stations/BAR/tickets",
        params={"shop_id": ctx["shop_id"]},
        headers=kitchen_headers,
    ).status_code == 403

    ticket_id = result["tickets"][0]["id"]
    out_payload = {
        "expected_state_version": 0,
        "operation_id": op("out"),
        "reason": "Hết nguyên liệu",
    }
    out = client.post(
        f"/api/fnb/tickets/{ticket_id}/out-of-stock",
        json=out_payload,
        headers=kitchen_headers,
    )
    assert out.status_code == 200, out.text
    assert out.json()["out_of_stock_reason"] == "Hết nguyên liệu"
    start_payload = {"expected_state_version": 1, "operation_id": op("start")}
    started = client.post(
        f"/api/fnb/tickets/{ticket_id}/start",
        json=start_payload,
        headers=kitchen_headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "IN_PROGRESS"
    assert client.post(
        f"/api/fnb/tickets/{ticket_id}/start",
        json=start_payload,
        headers=kitchen_headers,
    ).json() == started.json()
    stale = client.post(
        f"/api/fnb/tickets/{ticket_id}/done",
        json={"expected_state_version": 0, "operation_id": op("done")},
        headers=kitchen_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "FNB_TICKET_CHANGED"
    done = client.post(
        f"/api/fnb/tickets/{ticket_id}/done",
        json={"expected_state_version": 2, "operation_id": op("done")},
        headers=kitchen_headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "DONE"
    assert client.get(
        "/api/fnb/stations/KITCHEN/tickets",
        params={"shop_id": ctx["shop_id"]},
        headers=kitchen_headers,
    ).json()["tickets"] == []


def test_send_rejects_aggregate_stock_shortage_without_partial_writes(client, db):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx)
    table = create_fnb_table(client, ctx, area["id"])
    headers = auth(ctx["token"])
    product = db.get(models.Product, ctx["product"]["id"])
    product.fnb_station = "BAR"
    product.stock = product.cost_unknown_qty = 1
    product.cost_known_qty = product.cost_basis_vnd = 0
    db.commit()

    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]}, headers=headers).json()
    session = client.post(
        "/api/fnb/sessions",
        json={
            "shop_id": ctx["shop_id"], "table_id": table["id"],
            "expected_revision": floor["fnb_revision"],
            "expected_table_version": floor["areas"][0]["tables"][0]["state_version"],
            "operation_id": op("open"),
        }, headers=headers,
    ).json()
    session = client.post(
        f"/api/fnb/sessions/{session['id']}/lines",
        json={"product_id": product.id, "quantity": 2, "note": None,
              "expected_revision": session["revision"], "operation_id": op("line")},
        headers=headers,
    ).json()
    response = client.post(
        f"/api/fnb/sessions/{session['id']}/send",
        json={"expected_revision": session["revision"], "operation_id": op("send")},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "FNB_STOCK_SHORTAGE"
    db.expire_all()
    assert db.get(models.Product, product.id).stock == 1
    assert db.query(models.FnbKitchenTicket).filter(
        models.FnbKitchenTicket.shop_id == ctx["shop_id"]
    ).count() == 0
    assert db.query(models.FnbStockAllocation).filter(
        models.FnbStockAllocation.shop_id == ctx["shop_id"]
    ).count() == 0


def test_direct_item_skips_ticket_and_keeps_exact_batch_provenance(client, db):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx)
    table = create_fnb_table(client, ctx, area["id"])
    headers = auth(ctx["token"])
    product = db.get(models.Product, ctx["product"]["id"])
    product.track_batches = True
    product.fnb_station = "DIRECT"
    product.cost_known_qty = 0
    product.cost_unknown_qty = 0
    product.cost_basis_vnd = 0
    product.cost_deficit_qty = 0
    first = models.ProductBatch(
        product_id=product.id, shop_id=ctx["shop_id"], expiry_date="2099-01-01",
        quantity=1, cost_known_qty=0, cost_unknown_qty=1, cost_basis_vnd=0,
    )
    second = models.ProductBatch(
        product_id=product.id, shop_id=ctx["shop_id"], expiry_date="2099-02-01",
        quantity=9, cost_known_qty=0, cost_unknown_qty=9, cost_basis_vnd=0,
    )
    db.add_all([first, second])
    db.commit()

    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]}, headers=headers).json()
    session = client.post(
        "/api/fnb/sessions",
        json={
            "shop_id": ctx["shop_id"], "table_id": table["id"],
            "expected_revision": floor["fnb_revision"],
            "expected_table_version": floor["areas"][0]["tables"][0]["state_version"],
            "operation_id": op("open"),
        }, headers=headers,
    ).json()
    session = client.post(
        f"/api/fnb/sessions/{session['id']}/lines",
        json={
            "product_id": product.id, "quantity": 2, "note": None,
            "expected_revision": session["revision"], "operation_id": op("line"),
        }, headers=headers,
    ).json()
    sent = client.post(
        f"/api/fnb/sessions/{session['id']}/send",
        json={"expected_revision": session["revision"], "operation_id": op("send")},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["tickets"] == []
    db.expire_all()
    allocations = db.query(models.FnbStockAllocation).filter(
        models.FnbStockAllocation.session_id == session["id"]
    ).order_by(models.FnbStockAllocation.id).all()
    assert [(row.batch_id, row.quantity) for row in allocations] == [
        (first.id, 1), (second.id, 1),
    ]
    assert (db.get(models.ProductBatch, first.id).quantity,
            db.get(models.ProductBatch, second.id).quantity) == (0, 8)
