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
    ("POST", "/api/staff/{shop_id}"),               # C1b: chủ shop tạo nhân viên
    ("GET", "/api/staff/{shop_id}"),                # C1b: danh sách nhân viên
    ("DELETE", "/api/staff/member/{staff_id}"),     # C1b: xóa nhân viên
    ("PUT", "/api/staff/member/{staff_id}/password"),  # C1b: đặt lại mật khẩu NV
    ("PUT", "/api/staff/member/{staff_id}/role"),      # RBAC: đổi preset quyền NV
    ("POST", "/api/customers/{shop_id}"),            # C2b: thêm khách hàng
    ("GET", "/api/customers/{shop_id}"),             # C2b: danh sách/tìm khách
    ("GET", "/api/customers/member/{customer_id}"),  # C2b: chi tiết khách
    ("PUT", "/api/customers/member/{customer_id}"),  # C2b: sửa khách
    ("DELETE", "/api/customers/member/{customer_id}"),  # C2b: xóa khách
    ("GET", "/api/customers/member/{customer_id}/history"),  # C2c: lịch sử mua
    ("GET", "/api/products/{shop_id}/barcode/{barcode}"),  # B1a: tra SP theo mã vạch
    ("POST", "/api/products/{shop_id}/stocktake"),  # B4: áp dụng kết quả kiểm kê
    ("POST", "/api/tts"),          # D3: sinh giọng đọc khi máy thiếu giọng Việt
    ("GET", "/api/tts/status"),    # D3: frontend hỏi server có đọc hộ được không
    ("POST", "/api/orders/{order_id}/cash-topup"),  # D4: thu tiền mặt bù phần thiếu
    ("POST", "/api/orders/{order_id}/refund-complete"),  # D4: ghi nhận đã hoàn tiền
    ("GET", "/api/shifts/current/{shop_id}"),  # E1: ca OPEN của user hiện tại
    ("POST", "/api/shifts/{shop_id}/open"),  # E1: mở ca thu ngân
    ("GET", "/api/shifts/history/{shop_id}"),  # E1: lịch sử ca
    ("GET", "/api/shifts/{shift_id}"),  # E1: chi tiết ca và sổ thu/chi
    ("POST", "/api/shifts/{shift_id}/movements"),  # E1: thu/chi tiền mặt
    ("POST", "/api/shifts/{shift_id}/close"),  # E1: chốt ca
    # F1: giá vốn tách riêng khỏi GET /api/products/{shop_id}. Endpoint đó nay
    # đã có xác thực (F6) nhưng NHÂN VIÊN vẫn đọc được, còn route này chỉ chủ
    # shop/ADMIN - hai vòng người xem khác nhau nên vẫn phải tách.
    ("GET", "/api/products/{shop_id}/costs"),
    # F2: nhận hàng khách trả. Khác hủy đơn (đơn chưa thanh toán) và khác
    # refund-complete (hoàn khoản chuyển thừa, hàng vẫn của khách).
    ("POST", "/api/orders/{order_id}/returns"),
    # F4: khách trả bớt nợ. Khác cash-topup (đơn chuyển thiếu, phải trả trọn
    # phần còn thiếu) vì trả nợ dần nhiều lần là chuyện bình thường.
    ("POST", "/api/orders/{order_id}/debt-payment"),
    # F5: lô hàng sắp/đã hết hạn của shop.
    ("GET", "/api/products/{shop_id}/batches"),
    # F6: phiếu hủy hàng. Khác hẳn xuất kho: xuất kho không ghi lý do và không
    # chốt giá vốn, nên số hàng đó biến mất khỏi báo cáo và lãi bị thổi lên.
    # F6: kiểm kê theo lô cần biết MỌI lô còn hàng, khác /batches (chỉ lô
    # sắp/đã hết hạn, phục vụ màn cảnh báo).
    ("GET", "/api/products/{shop_id}/stocktake/batches"),
    ("POST", "/api/products/{shop_id}/write-off"),
    ("GET", "/api/products/{shop_id}/write-off/expired"),
    ("GET", "/api/products/{shop_id}/write-offs"),
    # G1: sao lưu DB lên R2. Do dịch vụ cron NGOÀI gọi (máy Fly tự tắt khi rảnh
    # nên APScheduler trong tiến trình không chạy được job ban đêm). Xác thực
    # bằng BACKUP_CRON_SECRET, không qua JWT vì người gọi không phải người dùng.
    ("POST", "/api/cron/backup"),
    # G2: nhận phiếu đã bán khi mất mạng. KHÁC HẲN POST /api/orders/{shop_id}:
    # ở đó giao dịch đang xảy ra nên giá tính lại từ DB và hết hàng thì từ chối;
    # ở đây giao dịch đã xảy ra rồi nên giá lấy từ phiếu và hết hàng vẫn ghi.
    ("POST", "/api/orders/{shop_id}/offline"),
    ("GET", "/api/orders/{shop_id}/offline-issues"),
    # G3: màn "Ai làm gì" của chủ shop. Khác /api/logs/admin: chỉ việc của người
    # thuộc shop này, và đã lọc bỏ hành động không đụng tiền hay kho.
    ("GET", "/api/logs/shop/{shop_id}"),
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
    assert client.get("/js/i18n.js").status_code == 200
    assert client.get("/js/vendor/i18next-26.3.6.min.js").status_code == 200
    for catalog in ("common", "auth-admin", "seller", "pos"):
        assert client.get(f"/js/locales/{catalog}.js").status_code == 200
    assert client.get("/css/style.css").status_code == 200


def test_export_seller_tra_dung_header(client):
    ctx = seller_with_shop(client)
    res = client.get(f"/api/export/seller/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]
    assert "seller_transactions.xlsx" in res.headers["content-disposition"]


def test_danh_sach_san_pham_giu_nguyen_cac_truong(client):
    ctx = seller_with_shop(client)
    res = client.get(f"/api/products/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200
    item = res.json()[0]
    assert set(item.keys()) == {
        "id",
        "code",
        "barcode",  # B1a: thêm khóa là thay đổi an toàn với frontend hiện tại
        "name",
        "price",
        "stock",
        "image_url",
        "is_active",
        "category_id",
        "shop_id",
        "category_is_active",
        # F5: cờ theo dõi lô + hạn sử dụng. POS cần biết để cảnh báo khi tồn
        # khả dụng thấp hơn tổng tồn vì có hàng quá hạn.
        "track_batches",
        # F6: biến thể. Cả hai NULL với sản phẩm đơn lẻ, nên client cũ đọc
        # `name` như trước vẫn đúng - `name` đã là tên đầy đủ kèm biến thể.
        "variant_group",
        "variant_name",
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
        "reconciliation_count",
    }


# ---------- Cache-busting cho file tĩnh ----------
def test_moi_file_js_css_deu_co_dau_phien_ban():
    """Mọi <script src="/js/..."> và <link href="/css/..."> phải kèm `?v=`.

    Trình duyệt cache JS/CSS rất dai (xem CLAUDE.md). Sửa file mà quên đổi dấu
    phiên bản thì người dùng đang mở sẵn trang sẽ CHẠY CODE CŨ - trong im lặng,
    không có lỗi nào cả, và mọi tính năng mới coi như không tồn tại với họ.
    Test này chỉ bắt được ca "thêm file mới mà quên `?v=`"; việc BUMP dấu phiên
    bản khi sửa file thì không máy nào kiểm hộ được, phải tự nhớ.
    """
    import re
    from pathlib import Path

    static_dir = Path(__file__).resolve().parent.parent / "static"
    mau = re.compile(r'(?:src|href)="(/(?:js|css)/[^"]+)"')
    thieu = []
    for trang in sorted(static_dir.glob("*.html")):
        for duong_dan in mau.findall(trang.read_text(encoding="utf-8")):
            if "?v=" not in duong_dan:
                thieu.append(f"{trang.name}: {duong_dan}")
    assert not thieu, "File tĩnh thiếu dấu phiên bản: " + ", ".join(thieu)
