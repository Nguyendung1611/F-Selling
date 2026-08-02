"""Phân quyền: seller không được đụng dữ liệu của seller khác; endpoint ADMIN."""
import pytest

from conftest import admin_token, auth, new_seller, new_staff, seller_with_shop


def test_seller_khong_xem_duoc_dashboard_shop_nguoi_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(f"/api/dashboard/seller/{a['shop_id']}", headers=auth(token_b))
    assert res.status_code == 403


def test_seller_khong_xem_duoc_stats_shop_nguoi_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    assert client.get(f"/api/shops/{a['shop_id']}/stats", headers=auth(token_b)).status_code == 403


def test_seller_khong_export_duoc_excel_shop_nguoi_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    assert client.get(f"/api/export/seller/{a['shop_id']}", headers=auth(token_b)).status_code == 403


def test_seller_khong_xem_duoc_danh_muc_shop_nguoi_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    assert client.get(f"/api/categories/{a['shop_id']}", headers=auth(token_b)).status_code == 403


# --- F6: GET /api/products/{shop_id} trước đây mở cho mọi người ---
#
# Đoán được `shop_id` là đọc trọn danh mục hàng và tồn kho của một cửa hàng lạ.
# Bốn test dưới canh cả hai phía: đóng đúng người ngoài, và KHÔNG đóng nhầm
# nhân viên đang cần lưới hàng để bán.


def test_danh_sach_san_pham_bat_buoc_dang_nhap(client):
    a = seller_with_shop(client)
    assert client.get(f"/api/products/{a['shop_id']}").status_code == 401


def test_seller_khong_xem_duoc_danh_sach_san_pham_shop_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.get(f"/api/products/{a['shop_id']}", headers=auth(token_b))
    assert res.status_code == 403


@pytest.mark.parametrize("staff_role", ["CASHIER", "WAREHOUSE", "MANAGER"])
def test_moi_vai_tro_nhan_vien_van_xem_duoc_danh_sach_san_pham(client, staff_role):
    """Thu ngân cần lưới hàng để bán, thủ kho cần để nhập xuất. Siết endpoint
    này mà chặn nhầm một vai trò là POS trống trơn ngay ca làm việc kế tiếp."""
    a = seller_with_shop(client)
    _, staff_token = new_staff(client, a, staff_role=staff_role)
    res = client.get(f"/api/products/{a['shop_id']}", headers=auth(staff_token))
    assert res.status_code == 200, res.text
    assert any(p["id"] == a["product"]["id"] for p in res.json())


def test_nhan_vien_khong_xem_duoc_danh_sach_san_pham_shop_khac(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    _, staff_token = new_staff(client, b, staff_role="MANAGER")
    res = client.get(f"/api/products/{a['shop_id']}", headers=auth(staff_token))
    assert res.status_code == 403


def test_seller_khong_sua_duoc_trang_thai_san_pham_shop_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    pid = a["product"]["id"]
    assert client.put(f"/api/products/{pid}/status", headers=auth(token_b)).status_code == 403
    assert client.delete(f"/api/products/{pid}", headers=auth(token_b)).status_code == 403


def test_seller_khong_xoa_duoc_voucher_shop_khac(client):
    a = seller_with_shop(client)
    res = client.post(
        "/api/vouchers",
        params={"shop_id": a["shop_id"]},
        json={"code": "AUTH10", "discount_type": "flat", "discount_value": 1000},
        headers=auth(a["token"]),
    )
    voucher_id = res.json()["id"]
    _, token_b = new_seller(client)
    assert client.delete(f"/api/vouchers/{voucher_id}", headers=auth(token_b)).status_code == 403


def test_seller_khong_sua_duoc_shop_nguoi_khac(client):
    from conftest import SHOP_PAYLOAD

    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.put(
        f"/api/shops/{a['shop_id']}", json=dict(SHOP_PAYLOAD), headers=auth(token_b)
    )
    assert res.status_code == 404  # giữ nguyên hành vi cũ: không lộ sự tồn tại của shop
    assert client.delete(f"/api/shops/{a['shop_id']}", headers=auth(token_b)).status_code == 404


def test_seller_khong_tao_duoc_danh_muc_cho_shop_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.post(
        "/api/categories",
        params={"name": "Cua nguoi khac", "shop_id": a["shop_id"]},
        headers=auth(token_b),
    )
    assert res.status_code == 403


def test_seller_khong_tao_duoc_san_pham_cho_shop_khac(client):
    a = seller_with_shop(client)
    _, token_b = new_seller(client)
    res = client.post(
        "/api/products",
        params={"shop_id": a["shop_id"]},
        data={"name": "SP lau", "price": 1000, "stock": 1, "category_id": a["category_id"]},
        headers=auth(token_b),
    )
    assert res.status_code == 403


def test_seller_khong_goi_duoc_endpoint_admin(client):
    _, token = new_seller(client)
    assert client.get("/api/dashboard/admin", headers=auth(token)).status_code == 403
    assert client.get("/api/export/admin", headers=auth(token)).status_code == 403
    assert client.get("/api/logs/admin", headers=auth(token)).status_code == 403


def test_admin_goi_duoc_endpoint_admin(client):
    token = admin_token(client)
    assert client.get("/api/dashboard/admin", headers=auth(token)).status_code == 200
    assert client.get("/api/logs/admin", headers=auth(token)).status_code == 200
    res = client.get("/api/export/admin", headers=auth(token))
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]


def test_admin_truy_cap_duoc_shop_cua_seller(client):
    a = seller_with_shop(client)
    token = admin_token(client)
    assert client.get(f"/api/dashboard/seller/{a['shop_id']}", headers=auth(token)).status_code == 200


def test_shop_khong_ton_tai_tra_404(client):
    _, token = new_seller(client)
    assert client.get("/api/dashboard/seller/999999", headers=auth(token)).status_code == 404


def test_gioi_han_3_cua_hang(client):
    from conftest import create_shop

    _, token = new_seller(client)
    for _ in range(3):
        create_shop(client, token)
    from conftest import SHOP_PAYLOAD

    res = client.post("/api/shops", json=dict(SHOP_PAYLOAD), headers=auth(token))
    assert res.status_code == 400
    assert "tối đa 3" in res.json()["detail"]
