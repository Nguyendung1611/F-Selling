"""Bảo vệ contract: danh sách route, trang HTML, static, header export."""
from conftest import auth, seller_with_shop

# Ảnh chụp toàn bộ route của app.py TRƯỚC khi refactor (47 route).
BASELINE_ROUTES = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/verify-email"),
    ("POST", "/api/auth/resend-code"),
    ("POST", "/api/auth/forgot-password-request"),
    ("POST", "/api/auth/forgot-password-reset"),
    ("POST", "/api/auth/change-password"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/session-check"),
    ("POST", "/api/shops"),
    ("GET", "/api/shops"),
    ("PUT", "/api/shops/{shop_id}"),
    ("PUT", "/api/shops/{shop_id}/status"),
    ("DELETE", "/api/shops/{shop_id}"),
    ("GET", "/api/shops/{shop_id}/stats"),
    ("POST", "/api/categories"),
    ("PUT", "/api/categories/{category_id}"),
    ("GET", "/api/categories/{shop_id}"),
    ("POST", "/api/products"),
    ("GET", "/api/products/{shop_id}"),
    ("PUT", "/api/products/{product_id}/status"),
    ("DELETE", "/api/products/{product_id}"),
    ("POST", "/api/orders/webhook"),
    ("POST", "/api/orders/{shop_id}"),
    ("GET", "/api/orders/{order_id}"),
    ("POST", "/api/orders/{order_id}/pay"),
    ("POST", "/api/vouchers"),
    ("PUT", "/api/vouchers/{voucher_id}"),
    ("DELETE", "/api/vouchers/{voucher_id}"),
    ("GET", "/api/vouchers/{shop_id}"),
    ("POST", "/api/vouchers/apply/{shop_id}"),
    ("GET", "/api/dashboard/seller/{shop_id}"),
    ("GET", "/api/dashboard/admin"),
    ("GET", "/api/export/admin"),
    ("GET", "/api/logs/admin"),
    ("GET", "/api/export/seller/{shop_id}"),
    ("GET", "/admin"),
    ("GET", "/pos"),
    ("GET", "/register"),
    ("GET", "/seller"),
    ("GET", "/verify"),
    ("GET", "/admin.html"),
    ("GET", "/pos.html"),
    ("GET", "/register.html"),
    ("GET", "/seller.html"),
    ("GET", "/verify.html"),
    ("GET", "/index.html"),
    ("GET", "/index"),
}


# Route được thêm CÓ CHỦ Ý sau bản refactor. Mọi route /api không nằm trong
# BASELINE_ROUTES hoặc danh sách này đều bị coi là thêm ngoài ý muốn.
ROUTES_BO_SUNG = {
    ("POST", "/api/orders/{order_id}/cancel"),  # A1d: hủy đơn + hoàn tồn kho
    ("GET", "/api/orders/{order_id}/detail"),   # B3: xem chi tiết đơn kèm dòng hàng
    ("PUT", "/api/products/{product_id}"),      # behavior fix: sửa sản phẩm từ Kho hàng
    ("POST", "/api/products/{product_id}/stock"),  # nhập/xuất kho theo delta
}


def _iter_routes(routes):
    """Yield concrete routes across eager and lazy FastAPI router layouts."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from _iter_routes(original_router.routes)
        else:
            yield route


def _routes(app):
    found = set()
    for route in _iter_routes(app.routes):
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or path is None:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            found.add((m, path))
    return found


def test_giu_nguyen_toan_bo_route_cu(app):
    found = _routes(app)
    thieu = BASELINE_ROUTES - found
    assert not thieu, f"Thiếu route so với bản gốc: {sorted(thieu)}"


def test_khong_them_route_api_ngoai_du_kien(app):
    duoc_phep = BASELINE_ROUTES | ROUTES_BO_SUNG
    api_moi = {r for r in _routes(app) if r[1].startswith("/api/")} - duoc_phep
    assert not api_moi, f"Route /api mới ngoài dự kiến: {sorted(api_moi)}"


def test_cac_route_bo_sung_deu_ton_tai(app):
    thieu = ROUTES_BO_SUNG - _routes(app)
    assert not thieu, f"Route bổ sung bị thiếu: {sorted(thieu)}"


def test_webhook_dang_ky_truoc_route_shop_id(app):
    paths = [
        (list(r.methods)[0] if getattr(r, "methods", None) else None, r.path)
        for r in _iter_routes(app.routes)
        if getattr(r, "path", "").startswith("/api/orders")
    ]
    order_paths = [p for _, p in paths]
    assert order_paths.index("/api/orders/webhook") < order_paths.index("/api/orders/{shop_id}")


def test_trang_html_va_redirect(client):
    for page in ("/admin", "/pos", "/register", "/seller", "/verify"):
        res = client.get(page)
        assert res.status_code == 200, page
        assert "text/html" in res.headers["content-type"]

    for old, new in (
        ("/admin.html", "/admin"),
        ("/pos.html", "/pos"),
        ("/index.html", "/"),
        ("/index", "/"),
    ):
        res = client.get(old, follow_redirects=False)
        assert res.status_code == 301, old
        assert res.headers["location"] == new


def test_trang_chu_va_static_file(client):
    assert client.get("/").status_code == 200
    assert client.get("/js/api.js").status_code == 200
    assert client.get("/css/style.css").status_code == 200


def test_export_seller_tra_dung_header(client):
    ctx = seller_with_shop(client)
    res = client.get(f"/api/export/seller/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]
    assert "seller_transactions.xlsx" in res.headers["content-disposition"]


def test_danh_sach_san_pham_giu_nguyen_cac_truong(client):
    ctx = seller_with_shop(client)
    res = client.get(f"/api/products/{ctx['shop_id']}")
    assert res.status_code == 200
    item = res.json()[0]
    assert set(item.keys()) == {
        "id",
        "code",
        "name",
        "price",
        "stock",
        "image_url",
        "is_active",
        "category_id",
        "shop_id",
        "category_is_active",
    }


def test_dashboard_seller_giu_nguyen_contract(client):
    """Nhóm B thêm khóa phân trang. Hai khóa cũ phải còn nguyên tên và ý nghĩa
    để frontend hiện tại không vỡ (thêm khóa là thay đổi an toàn)."""
    ctx = seller_with_shop(client)
    res = client.get(f"/api/dashboard/seller/{ctx['shop_id']}", headers=auth(ctx["token"]))
    body = res.json()
    assert {"total_revenue", "orders"} <= set(body.keys())
    assert isinstance(body["orders"], list)
    assert set(body.keys()) == {
        "total_revenue", "orders", "page", "per_page", "total_orders", "has_more",
    }
