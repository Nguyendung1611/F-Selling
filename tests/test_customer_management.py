"""C2b: CRUD khách hàng. Chủ shop VÀ nhân viên đều quản lý được (vận hành)."""
from conftest import auth, new_seller, new_staff, seller_with_shop

from fselling import models
from fselling.core.database import SessionLocal


def _tao(client, token, shop_id, name="Nguyen Van A", phone="0900000001", **kw):
    body = {"name": name, "phone": phone}
    body.update(kw)
    return client.post(f"/api/customers/{shop_id}", json=body, headers=auth(token))


# ---------- Tạo ----------
def test_tao_khach_du_truong(client):
    ctx = seller_with_shop(client)
    res = _tao(
        client, ctx["token"], ctx["shop_id"],
        name="Trần B", phone="0911000000", address="12 Lê Lợi", note="thích cà phê",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {
        "id", "shop_id", "name", "phone", "address", "note",
        # F4: trần công nợ. None = không giới hạn (mặc định).
        "credit_limit",
    }
    assert body["name"] == "Trần B"
    assert body["address"] == "12 Lê Lợi"
    assert body["note"] == "thích cà phê"


def test_tao_khach_toi_thieu_ten_sdt(client):
    ctx = seller_with_shop(client)
    res = _tao(client, ctx["token"], ctx["shop_id"], name="C", phone="0912")
    assert res.status_code == 200
    assert res.json()["address"] is None
    assert res.json()["note"] is None


def test_ten_rong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    assert _tao(client, ctx["token"], ctx["shop_id"], name="  ").status_code == 400


def test_sdt_rong_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    assert _tao(client, ctx["token"], ctx["shop_id"], phone="  ").status_code == 400


def test_trung_sdt_trong_shop_bi_chan(client):
    ctx = seller_with_shop(client)
    _tao(client, ctx["token"], ctx["shop_id"], phone="0900123456")
    res = _tao(client, ctx["token"], ctx["shop_id"], name="Khác", phone="0900123456")
    assert res.status_code == 400
    assert "điện thoại" in res.json()["detail"]


def test_trung_sdt_shop_khac_van_duoc(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    assert _tao(client, a["token"], a["shop_id"], phone="0999888777").status_code == 200
    assert _tao(client, b["token"], b["shop_id"], phone="0999888777").status_code == 200


# ---------- Quyền: nhân viên cũng quản lý được ----------
def test_nhan_vien_quan_ly_khach_duoc(client):
    ctx = seller_with_shop(client)
    _, staff_token = new_staff(client, ctx)

    res = _tao(client, staff_token, ctx["shop_id"], name="KH của staff", phone="0900555")
    assert res.status_code == 200
    kh_id = res.json()["id"]

    assert client.get(f"/api/customers/{ctx['shop_id']}", headers=auth(staff_token)).status_code == 200
    assert (
        client.put(
            f"/api/customers/member/{kh_id}",
            json={"name": "KH sửa", "phone": "0900555"},
            headers=auth(staff_token),
        ).status_code
        == 200
    )
    assert client.delete(f"/api/customers/member/{kh_id}", headers=auth(staff_token)).status_code == 200


def test_seller_khac_khong_quan_ly_khach_shop_nguoi_ta(client):
    ctx = seller_with_shop(client)
    kh_id = _tao(client, ctx["token"], ctx["shop_id"]).json()["id"]

    _, token_b = new_seller(client)
    assert _tao(client, token_b, ctx["shop_id"], phone="0900222").status_code == 403
    assert client.get(f"/api/customers/{ctx['shop_id']}", headers=auth(token_b)).status_code == 403
    assert client.get(f"/api/customers/member/{kh_id}", headers=auth(token_b)).status_code == 403
    assert client.delete(f"/api/customers/member/{kh_id}", headers=auth(token_b)).status_code == 403


def test_chua_dang_nhap_khong_thao_tac(client):
    ctx = seller_with_shop(client)
    assert client.post(f"/api/customers/{ctx['shop_id']}", json={"name": "x", "phone": "1"}).status_code == 401


# ---------- Danh sách + tìm kiếm ----------
def test_liet_ke_va_tim_theo_ten_sdt(client):
    ctx = seller_with_shop(client)
    # Hai tên KHÔNG chia sẻ chuỗi con, để kiểm tìm kiếm không nhập nhằng.
    _tao(client, ctx["token"], ctx["shop_id"], name="Hoa Mai", phone="0911111")
    _tao(client, ctx["token"], ctx["shop_id"], name="Le Cuong", phone="0922222")

    tat_ca = client.get(f"/api/customers/{ctx['shop_id']}", headers=auth(ctx["token"])).json()
    assert len(tat_ca) == 2

    theo_ten = client.get(
        f"/api/customers/{ctx['shop_id']}?q=Hoa", headers=auth(ctx["token"])
    ).json()
    assert {c["name"] for c in theo_ten} == {"Hoa Mai"}

    theo_sdt = client.get(
        f"/api/customers/{ctx['shop_id']}?q=0922", headers=auth(ctx["token"])
    ).json()
    assert {c["name"] for c in theo_sdt} == {"Le Cuong"}


def test_tim_kiem_la_chuoi_con_khong_phan_biet_hoa_thuong(client):
    """Ghi rõ hành vi: ô tìm khớp chuỗi con, không phân biệt hoa/thường."""
    ctx = seller_with_shop(client)
    _tao(client, ctx["token"], ctx["shop_id"], name="Tran Van Nam", phone="0933333")

    for tu_khoa in ("tran", "TRAN", "Van", "nam"):
        kq = client.get(
            f"/api/customers/{ctx['shop_id']}?q={tu_khoa}", headers=auth(ctx["token"])
        ).json()
        assert {c["name"] for c in kq} == {"Tran Van Nam"}, f"q={tu_khoa}"


def test_danh_sach_khong_lan_shop_khac(client):
    a = seller_with_shop(client)
    _tao(client, a["token"], a["shop_id"], name="KH shop A", phone="0900A")
    b = seller_with_shop(client)
    _tao(client, b["token"], b["shop_id"], name="KH shop B", phone="0900B")

    ds_a = client.get(f"/api/customers/{a['shop_id']}", headers=auth(a["token"])).json()
    assert {c["name"] for c in ds_a} == {"KH shop A"}


# ---------- Sửa ----------
def test_sua_khach(client):
    ctx = seller_with_shop(client)
    kh_id = _tao(client, ctx["token"], ctx["shop_id"], name="Cũ", phone="0900333").json()["id"]

    res = client.put(
        f"/api/customers/member/{kh_id}",
        json={"name": "Mới", "phone": "0900444", "address": "Địa chỉ mới"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Mới"
    assert res.json()["phone"] == "0900444"


def test_sua_khong_trung_sdt_khach_khac(client):
    ctx = seller_with_shop(client)
    _tao(client, ctx["token"], ctx["shop_id"], name="A", phone="0900111")
    kh2 = _tao(client, ctx["token"], ctx["shop_id"], name="B", phone="0900222").json()["id"]

    # đổi B sang trùng SĐT của A -> chặn
    res = client.put(
        f"/api/customers/member/{kh2}",
        json={"name": "B", "phone": "0900111"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400

    # giữ nguyên SĐT của chính B -> được
    ok = client.put(
        f"/api/customers/member/{kh2}",
        json={"name": "B đổi tên", "phone": "0900222"},
        headers=auth(ctx["token"]),
    )
    assert ok.status_code == 200


def test_khach_khong_ton_tai(client):
    ctx = seller_with_shop(client)
    assert client.get("/api/customers/member/999999", headers=auth(ctx["token"])).status_code == 404
    assert (
        client.put(
            "/api/customers/member/999999",
            json={"name": "x", "phone": "1"},
            headers=auth(ctx["token"]),
        ).status_code
        == 404
    )


# ---------- Xóa: giữ lịch sử đơn ----------
def test_xoa_khach_go_lien_ket_don_giu_don(client):
    ctx = seller_with_shop(client)
    kh_id = _tao(client, ctx["token"], ctx["shop_id"], phone="0900999").json()["id"]

    # tạo đơn rồi gắn khách thủ công (gắn ở POS là C2c)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 1, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    session = SessionLocal()
    try:
        session.query(models.Order).filter(models.Order.id == order_id).update(
            {models.Order.customer_id: kh_id}
        )
        session.commit()
    finally:
        session.close()

    res = client.delete(f"/api/customers/member/{kh_id}", headers=auth(ctx["token"]))
    assert res.status_code == 200

    session = SessionLocal()
    try:
        # đơn vẫn còn, chỉ mất liên kết khách
        order = session.query(models.Order).filter(models.Order.id == order_id).first()
        assert order is not None
        assert order.customer_id is None
        # hồ sơ khách đã bị xóa
        assert session.query(models.Customer).filter(models.Customer.id == kh_id).first() is None
    finally:
        session.close()
