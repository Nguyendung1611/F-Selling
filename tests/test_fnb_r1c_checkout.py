import uuid

from conftest import auth
from fselling import models

from test_fnb_r1c_checks import op, sent_session


def test_cash_checkout_transfers_provenance_once_and_closes_table(client, db):
    ctx, headers, session = sent_session(client, 2)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    payload = {
        "payment_method": "cash",
        "cash_tendered_vnd": 250000,
        "expected_revision": primary["revision"],
        "expected_session_revision": session["revision"],
        "operation_id": op("cash-pay"),
    }
    paid = client.post(
        f"/api/fnb/checks/{primary['id']}/pay", json=payload, headers=headers
    )
    assert paid.status_code == 200, paid.text
    result = paid.json()
    assert result["check"]["status"] == "PAID"
    assert result["order"]["status"] == "PAID"
    assert result["order"]["cash_change_vnd"] == 50000

    retry = client.post(
        f"/api/fnb/checks/{primary['id']}/pay", json=payload, headers=headers
    )
    assert retry.status_code == 200
    assert retry.json() == result

    db.expire_all()
    order = db.get(models.Order, result["order"]["id"])
    assert order.total_amount == 200000
    assert db.get(models.Product, ctx["product"]["id"]).stock == 8
    assert db.query(models.OrderItem).filter_by(order_id=order.id).one().quantity == 2
    transfer = db.query(models.FnbAllocationTransfer).filter_by(
        check_id=primary["id"]
    ).one()
    assert transfer.quantity == 2
    allocation = db.get(models.FnbStockAllocation, transfer.allocation_id)
    assert allocation.state == "TRANSFERRED_TO_ORDER"

    closed = client.post(
        f"/api/fnb/sessions/{session['id']}/close",
        json={
            "expected_revision": result["session_revision"],
            "operation_id": op("close"),
        },
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    floor = client.get(
        "/api/fnb/floor", params={"shop_id": ctx["shop_id"]}, headers=headers
    ).json()
    assert floor["areas"][0]["tables"][0]["state"] == "EMPTY"


def test_transfer_stays_pending_until_order_is_confirmed(client, db):
    _, headers, session = sent_session(client, 1)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    pending = client.post(
        f"/api/fnb/checks/{primary['id']}/pay",
        json={
            "payment_method": "transfer",
            "expected_revision": primary["revision"],
            "expected_session_revision": session["revision"],
            "operation_id": op("transfer-pay"),
        },
        headers=headers,
    )
    assert pending.status_code == 200, pending.text
    result = pending.json()
    assert result["check"]["status"] == "PAYMENT_PENDING"
    assert result["order"]["status"] == "PENDING"
    blocked = client.post(
        f"/api/fnb/sessions/{session['id']}/close",
        json={
            "expected_revision": result["session_revision"],
            "operation_id": op("close-pending"),
        },
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "FNB_UNSETTLED_CHECKS"

    order = db.get(models.Order, result["order"]["id"])
    order.status = "PAID"
    db.commit()
    refreshed = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()
    assert refreshed["checks"][0]["status"] == "PAID"


def test_debt_checkout_requires_customer_and_is_terminal(client):
    ctx, headers, session = sent_session(client, 1)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    base = {
        "payment_method": "debt",
        "expected_revision": primary["revision"],
        "expected_session_revision": session["revision"],
        "operation_id": op("debt-missing"),
    }
    missing = client.post(
        f"/api/fnb/checks/{primary['id']}/pay", json=base, headers=headers
    )
    assert missing.status_code == 400

    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": "Khách ghi nợ", "phone": f"09{uuid.uuid4().int % 10**8:08d}"},
        headers=headers,
    ).json()
    base.update(customer_id=customer["id"], operation_id=op("debt-pay"))
    debt = client.post(
        f"/api/fnb/checks/{primary['id']}/pay", json=base, headers=headers
    )
    assert debt.status_code == 200, debt.text
    assert debt.json()["check"]["status"] == "DEBT"
    assert debt.json()["order"]["status"] == "DEBT"


def test_cancelled_sent_quantity_is_removed_from_open_check(client, db):
    ctx, headers, session = sent_session(client, 2)
    line = session["lines"][0]
    cancelled = client.post(
        f"/api/fnb/sessions/{session['id']}/cancel-line",
        json={
            "line_id": line["id"],
            "quantity": 1,
            "expected_line_version": line["state_version"],
            "expected_revision": session["revision"],
            "operation_id": op("cancel-before-pay"),
        },
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    checks = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()
    primary = checks["checks"][0]
    assert primary["lines"][0]["quantity"] == 1
    assert primary["total_vnd"] == 100000
    paid = client.post(
        f"/api/fnb/checks/{primary['id']}/pay",
        json={
            "payment_method": "cash",
            "expected_revision": primary["revision"],
            "expected_session_revision": checks["session_revision"],
            "operation_id": op("pay-after-cancel"),
        },
        headers=headers,
    )
    assert paid.status_code == 200, paid.text
    db.expire_all()
    assert db.get(models.Product, ctx["product"]["id"]).stock == 9


def test_split_checks_pay_once_each_and_conserve_stock_provenance(client, db):
    ctx, headers, session = sent_session(client, 3)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    split = client.post(
        f"/api/fnb/checks/{primary['id']}/split",
        json={
            "lines": [{"line_id": primary["lines"][0]["line_id"], "quantity": 1}],
            "label": "Khách 2",
            "expected_revision": primary["revision"],
            "expected_session_revision": session["revision"],
            "operation_id": op("split-pay"),
        },
        headers=headers,
    ).json()
    revision = split["session_revision"]
    order_ids = []
    for check in split["checks"]:
        paid = client.post(
            f"/api/fnb/checks/{check['id']}/pay",
            json={
                "payment_method": "cash",
                "expected_revision": check["revision"],
                "expected_session_revision": revision,
                "operation_id": op(f"pay-{check['id']}"),
            },
            headers=headers,
        )
        assert paid.status_code == 200, paid.text
        revision = paid.json()["session_revision"]
        order_ids.append(paid.json()["order"]["id"])

    db.expire_all()
    transfers = db.query(models.FnbAllocationTransfer).filter(
        models.FnbAllocationTransfer.check_id.in_([row["id"] for row in split["checks"]])
    ).all()
    assert sum(row.quantity for row in transfers) == 3
    assert len({row.order_item_id for row in transfers}) == 2
    assert db.get(models.Product, ctx["product"]["id"]).stock == 7
    assert db.query(models.Order).filter(models.Order.id.in_(order_ids)).count() == 2
