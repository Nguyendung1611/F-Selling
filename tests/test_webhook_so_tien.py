"""D1: webhook phải đối chiếu SỐ TIỀN, không chỉ mã đơn.

Bản trước chỉ rút mã ORDERxxx rồi đánh dấu PAID, nên khách chuyển thiếu vẫn
được giao hàng, và một giao dịch tiền RA mang nội dung 'ORDER42' cũng đánh dấu
đơn 42 là đã thanh toán.
"""
from __future__ import annotations

import pytest
from conftest import auth, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services import payment_service

SECRET = "webhook-secret-test"
TONG_TIEN = 100000


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


def _tao_don(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": TONG_TIEN, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    return ctx, order_id


def _goi(client, payload):
    return client.post(
        "/api/orders/webhook", json=payload, headers={"X-Webhook-Secret": SECRET}
    )


def _trang_thai(client, ctx, order_id):
    return client.get(f"/api/orders/{order_id}", headers=auth(ctx["token"])).json()["status"]


def _don(order_id):
    s = SessionLocal()
    try:
        o = s.query(models.Order).filter(models.Order.id == order_id).first()
        return {"paid_amount": o.paid_amount, "bank_txn_id": o.bank_txn_id} if o else None
    finally:
        s.close()


def _logs(action, order_id):
    s = SessionLocal()
    try:
        return (
            s.query(models.SystemLog)
            .filter(
                models.SystemLog.action == action,
                models.SystemLog.details.like(f"%Order {order_id}%"),
            )
            .all()
        )
    finally:
        s.close()


# ---------- Tiền ra ----------


def test_giao_dich_tien_ra_bi_tu_choi(client, webhook_secret):
    """Shop hoàn tiền với nội dung 'hoan ORDER42' không được đánh dấu đơn đã trả."""
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"hoan tien ORDER{order_id}",
        "transferAmount": TONG_TIEN,
        "transferType": "out",
    })
    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"
    assert len(_logs("WEBHOOK_TU_CHOI", order_id)) == 1


def test_so_tien_am_coi_la_tien_ra(client, webhook_secret):
    """Casso không có transferType, tiền ra thể hiện bằng số tiền âm."""
    ctx, order_id = _tao_don(client)
    res = _goi(client, {"data": [{"description": f"ORDER{order_id}", "amount": -TONG_TIEN}]})
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"


# ---------- Thiếu số tiền trong payload ----------


def test_khong_co_so_tien_thi_khong_cho_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {"order_id": order_id})
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == []
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_tu_choi_van_tra_200_de_ngan_hang_khong_retry_vo_han(client, webhook_secret):
    _, order_id = _tao_don(client)
    assert _goi(client, {"order_id": order_id}).status_code == 200


# ---------- Chuyển thiếu ----------


def test_chuyen_thieu_thi_can_doi_soat(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": 10000, "transferType": "in"
    })
    assert res.status_code == 200, res.text
    assert res.json()["order_ids"] == []
    assert res.json()["unreconciled_order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "UNRECONCILED"


def test_chuyen_thieu_van_ghi_lai_so_tien_da_nhan(client, webhook_secret):
    """Tiền đã vào tài khoản shop nên phải để lại dấu vết, không được bỏ qua."""
    _, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": 10000, "id": "TXN-THIEU"})
    assert _don(order_id) == {"paid_amount": 10000, "bank_txn_id": "TXN-THIEU"}

    log = _logs("WEBHOOK_THIEU_TIEN", order_id)
    assert len(log) == 1
    assert "thiếu" in log[0].details


def test_thieu_mot_dong_van_bi_chan(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN - 1})
    assert _trang_thai(client, ctx, order_id) == "UNRECONCILED"


# ---------- Đủ và thừa ----------


def test_dung_so_tien_thi_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "transferType": "in", "id": "TXN-DU",
    })
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"
    assert _don(order_id) == {"paid_amount": TONG_TIEN, "bank_txn_id": "TXN-DU"}


def test_chuyen_thua_van_paid_va_ghi_log_so_du(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN + 50000})
    assert _trang_thai(client, ctx, order_id) == "PAID"

    log = _logs("WEBHOOK_PAYMENT", order_id)
    assert len(log) == 1
    assert "DƯ" in log[0].details


# ---------- Trả trùng ----------


def test_tra_hai_lan_bang_hai_giao_dich_khac_nhau_thi_ghi_log(client, webhook_secret):
    """Máy trạng thái chặn xử lý lại, nhưng shop đã nhận dư tiền thật."""
    ctx, order_id = _tao_don(client)
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-1"})
    _goi(client, {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-2"})

    assert _trang_thai(client, ctx, order_id) == "PAID"
    log = _logs("WEBHOOK_TRA_TRUNG", order_id)
    assert len(log) == 1
    assert "TXN-2" in log[0].details


def test_cung_mot_giao_dich_gui_lai_khong_bao_tra_trung(client, webhook_secret):
    """Ngân hàng gửi lại đúng giao dịch cũ là chuyện bình thường."""
    _, order_id = _tao_don(client)
    payload = {"content": f"ORDER{order_id}", "transferAmount": TONG_TIEN, "id": "TXN-SAME"}
    _goi(client, payload)
    _goi(client, payload)
    assert _logs("WEBHOOK_TRA_TRUNG", order_id) == []


# ---------- Sai tài khoản: chỉ cảnh báo ----------


def test_sai_tai_khoan_chi_canh_bao_khong_chan(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "accountNumber": "9999999999",
    })
    assert _trang_thai(client, ctx, order_id) == "PAID"   # vẫn cho qua
    assert len(_logs("WEBHOOK_KHAC_TAI_KHOAN", order_id)) == 1


def test_tai_khoan_khop_thi_khong_canh_bao(client, webhook_secret):
    _, order_id = _tao_don(client)
    _goi(client, {
        "content": f"ORDER{order_id}", "transferAmount": TONG_TIEN,
        "accountNumber": "0123456789",     # khớp SHOP_PAYLOAD trong conftest
    })
    assert _logs("WEBHOOK_KHAC_TAI_KHOAN", order_id) == []


# ---------- Bộ phân tích payload ----------


def test_extract_transactions_sepay():
    gd = payment_service.extract_transactions({
        "content": "CK ORDER42", "transferAmount": 150000,
        "transferType": "in", "id": 777, "accountNumber": "0011",
    })
    assert len(gd) == 1
    assert (gd[0].order_id, gd[0].amount, gd[0].direction) == (42, 150000, "in")
    assert (gd[0].txn_id, gd[0].account_no) == ("777", "0011")


def test_extract_transactions_casso_nhieu_giao_dich():
    gd = payment_service.extract_transactions({"data": [
        {"description": "ORDER1", "amount": 1000, "tid": "A"},
        {"description": "ORDER2", "amount": 2000, "tid": "B"},
    ]})
    assert [(g.order_id, g.amount, g.txn_id) for g in gd] == [(1, 1000, "A"), (2, 2000, "B")]


def test_extract_transactions_payos_lay_ordercode():
    gd = payment_service.extract_transactions(
        {"data": {"orderCode": 9, "description": "", "amount": 5000, "reference": "R9"}}
    )
    assert (gd[0].order_id, gd[0].amount, gd[0].txn_id) == (9, 5000, "R9")


def test_so_tien_bang_0_khac_voi_khong_co_so_tien():
    """0 là một số tiền thật (và sai); thiếu trường mới là None."""
    co_0 = payment_service.extract_transactions({"content": "ORDER5", "transferAmount": 0})
    khong_co = payment_service.extract_transactions({"order_id": 5})
    assert co_0[0].amount == 0
    assert khong_co[0].amount is None


def test_fallback_khong_co_so_tien():
    gd = payment_service.extract_transactions({"note": "thanh toan ORDER77"})
    assert gd[0].order_id == 77
    assert gd[0].amount is None
