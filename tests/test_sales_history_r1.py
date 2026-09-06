from datetime import datetime, timedelta

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import order_service
from conftest import auth, new_staff, seller_with_shop


def add_order(ctx, *, status="PAID", created_at=None, customer=None, total=12_000):
    with SessionLocal() as db:
        customer_id = None
        if customer:
            row = models.Customer(
                shop_id=ctx["shop_id"], name=customer[0], phone=customer[1]
            )
            db.add(row)
            db.flush()
            customer_id = row.id
        order = models.Order(
            shop_id=ctx["shop_id"], status=status, payment_method="cash",
            total_amount=total, customer_id=customer_id,
            created_at=created_at or datetime.utcnow(),
        )
        db.add(order)
        db.flush()
        db.add(models.OrderItem(
            order_id=order.id, product_name="Nước suối", price=total,
            quantity=1, net_amount_vnd=total, cost_unknown_qty=1,
        ))
        db.commit()
        return order.id


def _today_midday_utc():
    local_now = datetime.utcnow() + timedelta(hours=7)
    return datetime.combine(local_now.date(), datetime.min.time()) + timedelta(hours=5)


def test_history_defaults_to_20_finalized_orders_today(client):
    ctx = seller_with_shop(client)
    now = _today_midday_utc()
    ids = [add_order(ctx, status="PAID" if i % 2 else "DEBT",
                     created_at=now - timedelta(minutes=i)) for i in range(21)]
    add_order(ctx, status="PENDING", created_at=now + timedelta(seconds=1))
    add_order(ctx, status="CANCELLED", created_at=now + timedelta(seconds=2))
    add_order(ctx, status="PAID", created_at=now + timedelta(days=2))

    response = client.get(
        f"/api/orders/{ctx['shop_id']}/history", headers=auth(ctx["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["id"] for row in body["orders"]] == ids[:20]
    assert {row["status"] for row in body["orders"]} <= {"PAID", "DEBT"}
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert body["has_more"] is True
    assert body["searching_all_history"] is False
    second = client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"page": 2}, headers=auth(ctx["token"]),
    ).json()
    assert [row["id"] for row in second["orders"]] == ids[20:]
    assert second["has_more"] is False


def test_search_ignores_scope_and_matches_id_name_or_phone(client):
    ctx = seller_with_shop(client)
    old = datetime.utcnow() - timedelta(days=45)
    order_id = add_order(
        ctx, created_at=old, customer=("Cô Lan", "0774867057"), total=45_000
    )
    for query in (str(order_id), "cô lan", "867057"):
        response = client.get(
            f"/api/orders/{ctx['shop_id']}/history",
            params={"scope": "today", "q": query},
            headers=auth(ctx["token"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["id"] for row in body["orders"]] == [order_id]
        assert body["searching_all_history"] is True
        assert body["orders"][0]["customer_phone_masked"] == "077 *** 7057"
        assert "0774867057" not in response.text


def test_history_range_and_page_are_validated(client):
    ctx = seller_with_shop(client)
    assert client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"scope": "month"}, headers=auth(ctx["token"]),
    ).status_code == 422


def test_history_uses_calendar_days_in_utc_plus_seven(client):
    fixed_utc = datetime(2026, 8, 30, 18, 0, 0)  # 01:00 ngày 31/08 tại VN
    assert order_service._history_bounds_utc("today", fixed_utc) == (
        datetime(2026, 8, 30, 17, 0, 0),
        datetime(2026, 8, 31, 17, 0, 0),
    )
    assert order_service._history_bounds_utc("7d", fixed_utc) == (
        datetime(2026, 8, 24, 17, 0, 0),
        datetime(2026, 8, 31, 17, 0, 0),
    )
    ctx = seller_with_shop(client)
    assert client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"page": 0}, headers=auth(ctx["token"]),
    ).status_code == 422


def test_cashier_can_read_but_warehouse_and_other_shop_cannot(client):
    owner = seller_with_shop(client)
    other = seller_with_shop(client)
    add_order(owner)
    _, cashier = new_staff(client, owner, staff_role="CASHIER")
    _, warehouse = new_staff(client, owner, staff_role="WAREHOUSE")
    url = f"/api/orders/{owner['shop_id']}/history"
    assert client.get(url, headers=auth(cashier)).status_code == 200
    assert client.get(url, headers=auth(warehouse)).status_code == 403
    assert client.get(url, headers=auth(other["token"])).status_code == 403


def test_search_treats_sql_wildcards_as_plain_text(client):
    ctx = seller_with_shop(client)
    add_order(ctx, customer=("Khách thường", "0900000001"))
    response = client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"q": "%_"}, headers=auth(ctx["token"]),
    )
    assert response.status_code == 200
    assert response.json()["orders"] == []
