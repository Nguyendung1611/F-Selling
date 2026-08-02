"""F4: bán ghi nợ và thu nợ.

Đơn ghi nợ nằm ở trạng thái riêng `DEBT` chứ KHÔNG dùng lại `PENDING`, vì hai cỗ
máy đang bám vào nghĩa "PENDING = đang chờ khách trả tiền ngay bây giờ":

- `cancel_expired_pending_orders` hủy mọi đơn PENDING quá hạn và hoàn tồn kho.
- `close_shift` không cho đóng ca khi còn đơn PENDING tiền mặt.

Hai test ở mục "Hai quả mìn" dưới đây tồn tại để chứng minh cả hai vẫn không
đụng tới đơn nợ — nếu ai đó đổi `STATUS_DEBT` về lại `PENDING` thì chúng phải đỏ.
"""
import uuid

import pytest
from conftest import _unique, auth, new_seller, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal
from fselling.routers import webhooks
from fselling.services import maintenance_service

WEBHOOK_SECRET = "webhook-secret-cong-no"


def _op() -> str:
    return uuid.uuid4().hex


def _don(order_id):
    session = SessionLocal()
    try:
        return session.query(models.Order).filter(models.Order.id == order_id).first()
    finally:
        session.close()


def _sp(product_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.Product)
            .filter(models.Product.id == product_id)
            .first()
        )
    finally:
        session.close()


def _tao_khach(client, ctx, ten=None, han_muc=None, token=None):
    body = {"name": ten or _unique("Khach"), "phone": _unique("09")[:15]}
    if han_muc is not None:
        body["credit_limit"] = han_muc
    res = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json=body,
        headers=auth(token or ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _ban_no(client, ctx, khach_id, qty=1, token=None, san_pham=None):
    sp = san_pham or ctx["product"]
    return client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_id": sp["id"], "price": sp["price"], "quantity": qty}],
            "payment_method": "debt",
            "customer_id": khach_id,
        },
        headers=auth(token or ctx["token"]),
    )


def _thu_no(client, ctx, order_id, so_tien, method="transfer", token=None, **kw):
    body = {"amount": so_tien, "method": method, "operation_id": _op()}
    body.update(kw)
    return client.post(
        f"/api/orders/{order_id}/debt-payment",
        json=body,
        headers=auth(token or ctx["token"]),
    )


def _mo_ca(client, ctx, token=None, tien=500000):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": tien},
        headers=auth(token or ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


# ---------- Bán ghi nợ ----------
def test_ban_ghi_no_tao_don_trang_thai_debt(client):
    ctx = seller_with_shop(client)   # SP giá 100000, tồn 10
    kh = _tao_khach(client, ctx)

    res = _ban_no(client, ctx, kh["id"], qty=2)
    assert res.status_code == 200, res.text
    o = _don(res.json()["order_id"])
    assert o.status == "DEBT"
    assert o.payment_method == "debt"
    assert o.customer_id == kh["id"]


def test_ban_ghi_no_van_tru_ton_kho_ngay(client):
    """Hàng đã ra khỏi cửa rồi, chỉ có tiền là chưa thu."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    _ban_no(client, ctx, kh["id"], qty=3)
    assert _sp(ctx["product"]["id"]).stock == 7


def test_ban_ghi_no_bat_buoc_chon_khach(client):
    """Nợ mà không biết ai nợ thì không đòi được."""
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "price": ctx["product"]["price"],
                    "quantity": 1,
                }
            ],
            "payment_method": "debt",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert _sp(ctx["product"]["id"]).stock == 10, "Đơn hỏng thì không trừ kho"


def test_hinh_thuc_thanh_toan_la_bi_tu_choi(client):
    """Trước F4 trường này không được kiểm gì cả, client gửi chuỗi nào cũng lưu."""
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "price": ctx["product"]["price"],
                    "quantity": 1,
                }
            ],
            "payment_method": "mien_phi_luon",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_don_no_khong_tinh_vao_doanh_thu(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    _ban_no(client, ctx, kh["id"], qty=2)

    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    ).json()
    assert stats["total_revenue"] == 0, "Chưa thu được đồng nào thì chưa có doanh thu"
    assert stats["receivable_amount"] == 200000


def test_pay_order_khong_ap_dung_cho_don_no(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    res = client.post(f"/api/orders/{order_id}/pay", headers=auth(ctx["token"]))
    assert res.status_code == 409
    assert "thu nợ" in res.json()["detail"]


# ---------- Hai quả mìn ----------
def test_job_tu_huy_don_treo_KHONG_dung_toi_don_no(client):
    """Nếu đơn nợ để ở PENDING thì job này xóa sạch sổ nợ và cộng trả vào kho
    số hàng khách đã cầm về."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=3).json()["order_id"]

    # Đẩy đơn về quá khứ rồi chạy job với ngưỡng 1 phút.
    session = SessionLocal()
    try:
        from datetime import datetime, timedelta

        o = session.query(models.Order).filter(models.Order.id == order_id).first()
        o.created_at = datetime.utcnow() - timedelta(days=30)
        session.commit()
    finally:
        session.close()

    maintenance_service.cancel_expired_pending_orders(timeout_minutes=1)

    assert _don(order_id).status == "DEBT", "Đơn nợ KHÔNG được tự hủy"
    assert _sp(ctx["product"]["id"]).stock == 7, "Và tồn kho không được hoàn"


def test_don_no_khong_chan_ket_ca(client):
    """Đơn nợ treo hàng tuần là bình thường; nếu nó chặn đóng ca thì thu ngân
    sẽ không bao giờ kết ca được."""
    ctx = seller_with_shop(client)
    _, thu_ngan = new_staff(client, ctx, staff_role="CASHIER")
    shift_id = _mo_ca(client, ctx, token=thu_ngan)
    kh = _tao_khach(client, ctx, token=thu_ngan)
    _ban_no(client, ctx, kh["id"], qty=2, token=thu_ngan)

    res = client.post(
        f"/api/shifts/{shift_id}/close",
        json={"counted_cash_amount": 500000},
        headers=auth(thu_ngan),
    )
    assert res.status_code == 200, res.text


# ---------- Hạn mức ----------
def test_vuot_han_muc_bi_chan(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx, han_muc=150000)   # SP giá 100000

    assert _ban_no(client, ctx, kh["id"], qty=1).status_code == 200
    res = _ban_no(client, ctx, kh["id"], qty=1)
    assert res.status_code == 400, "100k + 100k vượt hạn mức 150k"
    assert _sp(ctx["product"]["id"]).stock == 9, "Đơn bị chặn thì không trừ kho"


def test_dung_bang_han_muc_thi_van_cho(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx, han_muc=200000)
    assert _ban_no(client, ctx, kh["id"], qty=2).status_code == 200


def test_khong_dat_han_muc_thi_khong_gioi_han(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    assert kh["credit_limit"] is None
    for _ in range(5):
        assert _ban_no(client, ctx, kh["id"], qty=2).status_code == 200


def test_han_muc_0_la_khong_cho_no_dong_nao(client):
    """0 khác hẳn None: None = không giới hạn, 0 = cấm nợ."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx, han_muc=0)
    assert _ban_no(client, ctx, kh["id"], qty=1).status_code == 400


def test_tra_bot_no_thi_lai_ban_ghi_no_duoc(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx, han_muc=200000)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]
    assert _ban_no(client, ctx, kh["id"], qty=1).status_code == 400

    _thu_no(client, ctx, order_id, 150000)
    assert _ban_no(client, ctx, kh["id"], qty=1).status_code == 200


def test_han_muc_am_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": "Khach am", "phone": "0900000111", "credit_limit": -1},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


# ---------- Thu nợ ----------
def test_tra_dan_nhieu_lan_du_tien_thi_thanh_paid(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]   # 200k

    res = _thu_no(client, ctx, order_id, 50000)
    assert res.status_code == 200, res.text
    assert res.json()["remaining_amount"] == 150000
    assert _don(order_id).status == "DEBT"

    _thu_no(client, ctx, order_id, 100000)
    assert _don(order_id).status == "DEBT"

    cuoi = _thu_no(client, ctx, order_id, 50000)
    assert cuoi.status_code == 200, cuoi.text
    assert cuoi.json()["remaining_amount"] == 0
    assert _don(order_id).status == "PAID", "Trả đủ là đơn tự chuyển PAID"


def test_tra_du_roi_moi_tinh_vao_doanh_thu(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]

    _thu_no(client, ctx, order_id, 150000)
    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    ).json()
    assert stats["total_revenue"] == 0, "Trả một phần chưa phải doanh thu"
    assert stats["receivable_amount"] == 50000

    _thu_no(client, ctx, order_id, 50000)
    stats = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    ).json()
    assert stats["total_revenue"] == 200000
    assert stats["receivable_amount"] == 0


def test_khong_thu_qua_so_con_no(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=1).json()["order_id"]   # 100k

    res = _thu_no(client, ctx, order_id, 150000)
    assert res.status_code == 400
    assert _don(order_id).status == "DEBT"


def test_thu_so_tien_khong_duong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    assert _thu_no(client, ctx, order_id, 0).status_code == 400
    assert _thu_no(client, ctx, order_id, -5000).status_code == 400


def test_don_da_tra_het_thi_khong_thu_them(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=1).json()["order_id"]
    _thu_no(client, ctx, order_id, 100000)

    res = _thu_no(client, ctx, order_id, 10000)
    assert res.status_code == 409


def test_thu_no_bam_hai_lan_chi_ghi_mot_lan(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]

    body = {"amount": 50000, "method": "transfer", "operation_id": _op()}
    a = client.post(
        f"/api/orders/{order_id}/debt-payment", json=body, headers=auth(ctx["token"])
    )
    b = client.post(
        f"/api/orders/{order_id}/debt-payment", json=body, headers=auth(ctx["token"])
    )
    assert a.status_code == b.status_code == 200
    assert b.json()["remaining_amount"] == 150000, "Retry không được thu hai lần"


def test_don_khong_phai_don_no_thi_khong_thu_no_duoc(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [
                {
                    "product_id": ctx["product"]["id"],
                    "price": ctx["product"]["price"],
                    "quantity": 1,
                }
            ],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    ).json()["order_id"]

    assert _thu_no(client, ctx, order_id, 50000).status_code == 409


# ---------- Két ca ----------
def test_thu_no_tien_mat_vao_dung_ket_ca(client):
    ctx = seller_with_shop(client)
    _, thu_ngan = new_staff(client, ctx, staff_role="CASHIER")
    shift_id = _mo_ca(client, ctx, token=thu_ngan)
    kh = _tao_khach(client, ctx, token=thu_ngan)
    order_id = _ban_no(client, ctx, kh["id"], qty=2, token=thu_ngan).json()["order_id"]

    truoc = client.get(f"/api/shifts/{shift_id}", headers=auth(thu_ngan)).json()[
        "expected_cash_amount"
    ]
    res = _thu_no(client, ctx, order_id, 80000, method="cash", token=thu_ngan)
    assert res.status_code == 200, res.text
    sau = client.get(f"/api/shifts/{shift_id}", headers=auth(thu_ngan)).json()[
        "expected_cash_amount"
    ]
    assert sau == truoc + 80000


def test_thu_no_chuyen_khoan_khong_dung_toi_ket(client):
    ctx = seller_with_shop(client)
    _, thu_ngan = new_staff(client, ctx, staff_role="CASHIER")
    shift_id = _mo_ca(client, ctx, token=thu_ngan)
    kh = _tao_khach(client, ctx, token=thu_ngan)
    order_id = _ban_no(client, ctx, kh["id"], qty=2, token=thu_ngan).json()["order_id"]

    truoc = client.get(f"/api/shifts/{shift_id}", headers=auth(thu_ngan)).json()[
        "expected_cash_amount"
    ]
    _thu_no(client, ctx, order_id, 80000, method="transfer", token=thu_ngan)
    sau = client.get(f"/api/shifts/{shift_id}", headers=auth(thu_ngan)).json()[
        "expected_cash_amount"
    ]
    assert sau == truoc


def test_thu_tien_mat_khi_chua_mo_ca_bi_chan(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]

    res = _thu_no(client, ctx, order_id, 50000, method="cash")
    assert res.status_code == 409
    assert _don(order_id).cash_paid_amount in (0, None), "Bị chặn thì không ghi gì"


# ---------- Hủy đơn nợ ----------
def test_huy_don_no_chua_thu_dong_nao(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=3).json()["order_id"]

    res = client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text
    assert _don(order_id).status == "CANCELLED"
    assert _sp(ctx["product"]["id"]).stock == 10, "Hủy thì hoàn tồn kho"


def test_don_no_da_thu_mot_phan_thi_khong_huy_duoc(client):
    """Hủy sẽ hoàn kho số hàng khách đã cầm về, và biến khoản đã thu thành tiền
    vô chủ - nằm trong két nhưng không thuộc đơn nào."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=3).json()["order_id"]
    _thu_no(client, ctx, order_id, 50000)

    res = client.post(f"/api/orders/{order_id}/cancel", headers=auth(ctx["token"]))
    assert res.status_code == 409
    assert _don(order_id).status == "DEBT"
    assert _sp(ctx["product"]["id"]).stock == 7


# ---------- Màn khách hàng ----------
def test_danh_sach_khach_hien_cong_no(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx, han_muc=500000)
    _ban_no(client, ctx, kh["id"], qty=2)

    res = client.get(
        f"/api/customers/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    ban_ghi = next(c for c in res.json() if c["id"] == kh["id"])
    assert ban_ghi["debt_amount"] == 200000
    assert ban_ghi["credit_limit"] == 500000


def test_lich_su_khach_hien_no_va_so_con_thieu_tung_don(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"], qty=2).json()["order_id"]
    _thu_no(client, ctx, order_id, 30000)

    body = client.get(
        f"/api/customers/member/{kh['id']}/history", headers=auth(ctx["token"])
    ).json()
    assert body["debt_amount"] == 170000
    don = next(o for o in body["orders"] if o["id"] == order_id)
    assert don["remaining"] == 170000


def test_cong_no_gom_nhieu_don_cua_cung_khach(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    _ban_no(client, ctx, kh["id"], qty=2)
    _ban_no(client, ctx, kh["id"], qty=3)

    res = client.get(
        f"/api/customers/member/{kh['id']}", headers=auth(ctx["token"])
    )
    assert res.json()["debt_amount"] == 500000


def test_no_cua_khach_nay_khong_lan_sang_khach_khac(client):
    ctx = seller_with_shop(client)
    a = _tao_khach(client, ctx)
    b = _tao_khach(client, ctx)
    _ban_no(client, ctx, a["id"], qty=2)

    res = client.get(f"/api/customers/member/{b['id']}", headers=auth(ctx["token"]))
    assert res.json()["debt_amount"] == 0


def test_shop_khac_khong_thu_no_ho_duoc(client):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    _, nguoi_khac = new_seller(client)

    assert _thu_no(
        client, ctx, order_id, 10000, token=nguoi_khac
    ).status_code == 403


# ---------- Quả mìn thứ ba: webhook ngân hàng ----------
#
# `WEBHOOK_PAY_FROM` được khai từ F4 nhưng KHÔNG chỗ nào đọc, nên nó trông như
# một ràng buộc đang có hiệu lực trong khi webhook thực ra nhận mọi trạng thái.
# Hậu quả đo được: chuyển 40k cho đơn nợ 100k đẩy đơn sang UNRECONCILED, mà
# `receivable_amount` lọc đúng chuỗi "DEBT" nên 60k khách còn nợ biến mất khỏi
# sổ - shop mất dấu khoản phải thu trong im lặng.


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: WEBHOOK_SECRET)
    return WEBHOOK_SECRET


def _goi_webhook(client, payload):
    return client.post(
        "/api/orders/webhook",
        json=payload,
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )


def _phai_thu(client, ctx):
    res = client.get(
        f"/api/shops/{ctx['shop_id']}/stats", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    return res.json()["receivable_amount"]


def test_webhook_KHONG_dung_toi_don_no_khi_chuyen_thieu(client, webhook_secret):
    """Đây là ca làm mất dấu sổ nợ. Đơn phải ở nguyên DEBT."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    tong = _don(order_id).total_amount

    res = _goi_webhook(client, {
        "content": f"ORDER{order_id}", "transferAmount": tong / 2
    })
    assert res.status_code == 200, res.text
    assert res.json()["rejected_order_ids"] == [order_id]

    o = _don(order_id)
    assert o.status == "DEBT", "Đơn nợ không được đổi trạng thái vì một webhook"
    assert not o.paid_amount, "Không được cộng tiền vào đơn nợ qua webhook"
    assert _phai_thu(client, ctx) == tong, "Sổ nợ phải còn nguyên"


def test_webhook_KHONG_dung_toi_don_no_ke_ca_khi_chuyen_du(client, webhook_secret):
    """Chuyển đủ tiền cũng không được tự tất toán: khoản đó phải đi qua ledger
    thu nợ để vào đúng ca và đúng cột, chứ không nhảy thẳng sang PAID."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    tong = _don(order_id).total_amount

    res = _goi_webhook(client, {
        "content": f"ORDER{order_id}", "transferAmount": tong
    })
    assert res.json()["order_ids"] == []
    assert res.json()["rejected_order_ids"] == [order_id]
    assert _don(order_id).status == "DEBT"
    assert _phai_thu(client, ctx) == tong


def test_webhook_tu_choi_don_no_van_tra_200(client, webhook_secret):
    """Trả 4xx/5xx thì ngân hàng retry vô hạn (luật ở mục 8 KIEN_TRUC.md)."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    res = _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 1000})
    assert res.status_code == 200


def test_webhook_ghi_ly_do_tu_choi_vao_system_log(client, webhook_secret):
    """Tiền về mà không xử lý được thì phải để lại dấu vết tra được."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 1000})

    session = SessionLocal()
    try:
        log = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == "WEBHOOK_TU_CHOI",
                models.SystemLog.details.like(f"%Order {order_id}%"),
            )
            .all()
        )
    finally:
        session.close()
    assert len(log) == 1
    assert "DEBT" in log[0].details


def test_thu_no_van_chay_binh_thuong_sau_khi_webhook_bi_chan(client, webhook_secret):
    """Chặn webhook không được chặn luôn đường thu nợ thật."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    tong = _don(order_id).total_amount
    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": tong})

    res = _thu_no(client, ctx, order_id, tong)
    assert res.status_code == 200, res.text
    assert _don(order_id).status == "PAID"
    assert _phai_thu(client, ctx) == 0


# ---------- Tiền về cho đơn nợ phải NHÌN THẤY ĐƯỢC ----------
#
# Chặn webhook mà chỉ ghi SystemLog thì tiền về mà người bán không biết để đi
# thu. Khoản đó nay được ghi thành bút toán `BANK_UNAPPLIED` và nổi lên màn
# Đối Soát. Bút toán này KHÔNG phải một khoản thu: không cộng vào paid_amount,
# không đổi trạng thái, không vào két.


def _but_toan(order_id):
    session = SessionLocal()
    try:
        return (
            session.query(models.OrderPayment)
            .filter(models.OrderPayment.order_id == order_id)
            .order_by(models.OrderPayment.id)
            .all()
        )
    finally:
        session.close()


def _doi_soat(client, ctx, token=None):
    res = client.get(
        f"/api/dashboard/seller/{ctx['shop_id']}?reconciliation_only=true",
        headers=auth(token or ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_tien_ve_cho_don_no_duoc_ghi_thanh_but_toan_rieng(client, webhook_secret):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 40000})

    bt = _but_toan(order_id)
    assert len(bt) == 1
    assert bt[0].entry_type == "BANK_UNAPPLIED"
    assert bt[0].amount == 40000
    assert bt[0].shift_id is None, "Không được vào két của ca nào"

    o = _don(order_id)
    assert o.status == "DEBT"
    assert not o.paid_amount, "Bút toán này KHÔNG phải một khoản thu"


def test_don_no_co_tien_ve_noi_len_man_doi_soat(client, webhook_secret):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    truoc = _doi_soat(client, ctx)
    assert all(o["id"] != order_id for o in truoc["orders"])

    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 40000})

    sau = _doi_soat(client, ctx)
    the = [o for o in sau["orders"] if o["id"] == order_id]
    assert len(the) == 1, "Đơn nợ có tiền về phải hiện trên màn Đối Soát"
    assert the[0]["unapplied_transfer_amount"] == 40000
    assert the[0]["status"] == "DEBT"
    assert sau["reconciliation_count"] >= 1


def test_thu_no_xong_thi_don_roi_khoi_man_doi_soat(client, webhook_secret):
    """Nhắc mãi một khoản đã xử lý xong thì người bán sẽ học cách phớt lờ nó."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 40000})

    _thu_no(client, ctx, order_id, 40000)

    sau = _doi_soat(client, ctx)
    assert all(o["id"] != order_id for o in sau["orders"])
    assert _don(order_id).status == "DEBT", "Mới thu một phần, vẫn còn nợ"


def test_them_lan_chuyen_moi_thi_nhac_lai(client, webhook_secret):
    """Đã thu lần trước không có nghĩa là lần chuyển sau cũng đã xử lý."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 40000})
    _thu_no(client, ctx, order_id, 40000)

    _goi_webhook(client, {
        "content": f"ORDER{order_id}", "transferAmount": 30000,
        "referenceCode": "GD-KHAC",
    })

    the = [o for o in _doi_soat(client, ctx)["orders"] if o["id"] == order_id]
    assert len(the) == 1
    assert the[0]["unapplied_transfer_amount"] == 70000


def test_ngan_hang_gui_lai_khong_nhan_ban_but_toan(client, webhook_secret):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": 40000,
        "referenceCode": "GD-LAP-LAI",
    }
    _goi_webhook(client, payload)
    _goi_webhook(client, payload)
    _goi_webhook(client, payload)

    assert len(_but_toan(order_id)) == 1


def test_gui_lai_sau_khi_da_thu_no_KHONG_cong_tien_lan_hai(client, webhook_secret):
    """Kịch bản nguy hiểm nhất, và là lý do bút toán chưa-ghi-nhận phải dùng
    CHUNG khóa idempotency với bút toán thật.

    Khách chuyển đủ -> webhook ghi unapplied -> người bán thu nợ tay, đơn thành
    PAID -> ngân hàng gửi lại đúng giao dịch đó. Lúc này PAID nằm trong
    WEBHOOK_PAY_FROM nên giao dịch được xử lý thật; nếu khóa khác nhau thì nó
    không bị coi là trùng và đơn thành OVERPAID với một khoản chờ hoàn không có
    thật.
    """
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]
    tong = _don(order_id).total_amount
    payload = {
        "content": f"ORDER{order_id}",
        "transferAmount": tong,
        "referenceCode": "GD-TRA-DU",
    }

    _goi_webhook(client, payload)
    _thu_no(client, ctx, order_id, tong)
    assert _don(order_id).status == "PAID"

    _goi_webhook(client, payload)

    o = _don(order_id)
    assert o.status == "PAID"
    assert not o.refund_due_amount, "Không được đẻ ra khoản chờ hoàn ảo"
    assert o.reconciliation_reason != "OVERPAID"


def test_tien_RA_cho_don_no_khong_ghi_but_toan(client, webhook_secret):
    """Không có tiền nào về thì không có gì để báo cho người bán."""
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    _goi_webhook(client, {
        "content": f"hoan ORDER{order_id}",
        "transferAmount": 40000,
        "transferType": "out",
    })
    assert _but_toan(order_id) == []


def test_payload_thieu_so_tien_khong_ghi_but_toan(client, webhook_secret):
    ctx = seller_with_shop(client)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    _goi_webhook(client, {"order_id": order_id})
    assert _but_toan(order_id) == []


def test_but_toan_chua_ghi_nhan_khong_vao_ket_ca(client, webhook_secret):
    """`CASH_PAYMENT_IN_TYPES` liệt kê tường minh nên loại này nằm ngoài - test
    canh đúng chỗ đó, vì thêm nhầm một chuỗi vào danh sách kia là tiền ảo vào
    két và thu ngân lệch ca."""
    ctx = seller_with_shop(client)
    shift_id = _mo_ca(client, ctx)
    kh = _tao_khach(client, ctx)
    order_id = _ban_no(client, ctx, kh["id"]).json()["order_id"]

    truoc = client.get(
        f"/api/shifts/{shift_id}", headers=auth(ctx["token"])
    ).json()["expected_cash_amount"]
    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": 40000})
    sau = client.get(
        f"/api/shifts/{shift_id}", headers=auth(ctx["token"])
    ).json()["expected_cash_amount"]

    assert sau == truoc, "Két không được đổi vì một khoản chưa ghi nhận"


def test_don_thuong_khong_co_but_toan_chua_ghi_nhan(client, webhook_secret):
    """Đơn PENDING chạy đường cũ: tiền được áp thẳng, không sinh loại bút toán
    mới nào."""
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [
            {"product_id": ctx["product"]["id"],
             "price": ctx["product"]["price"], "quantity": 1}
        ]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    tong = _don(order_id).total_amount

    _goi_webhook(client, {"content": f"ORDER{order_id}", "transferAmount": tong})

    loai = [b.entry_type for b in _but_toan(order_id)]
    assert "BANK_UNAPPLIED" not in loai
    assert loai == ["BANK_IN"]


def test_webhook_van_chay_dung_cho_don_PENDING(client, webhook_secret):
    """Danh sách trạng thái cho phép mà liệt kê thiếu là chặn nhầm đường chính."""
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [
            {"product_id": ctx["product"]["id"],
             "price": ctx["product"]["price"], "quantity": 1}
        ]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    tong = _don(order_id).total_amount

    res = _goi_webhook(client, {
        "content": f"ORDER{order_id}", "transferAmount": tong
    })
    assert res.json()["order_ids"] == [order_id]
    assert _don(order_id).status == "PAID"
