"""Script tạo dữ liệu mẫu TOÀN DIỆN (Comprehensive Demo Data) cho F-Selling.

Bao gồm 100% các tính năng của hệ thống:
1. Tài khoản Chủ shop demo; tài khoản nội bộ dùng mật khẩu ngẫu nhiên, không công bố
2. Gói PRO kích hoạt sẵn
3. Đầy đủ Danh mục & Sản phẩm (Hàng thường, Hàng theo Lô Hạn FEFO, Hàng Biến thể Size/Màu)
4. Nhà cung cấp, Phiếu nhập hàng, Công nợ nhà cung cấp
5. Khách hàng CRM, Điểm thưởng Loyalty, Đơn nợ khách hàng (DEBT)
6. Vouchers / Khuyến mãi
7. 30 ngày lịch sử bán hàng (phục vụ Dự báo nhập hàng Smart Forecast & Báo cáo Tài chính)
8. Phiếu Đổi/Trả hàng (Order Returns)
9. Phiếu Hủy hàng hỏng/hết hạn (Stock Write-Off)
10. Chi phí vận hành & Phân bổ chi phí trả trước 6 tháng (Operating Expenses & Amortization)
11. Ca bán hàng (Shift Management): Ca cũ đã chốt két + Ca hiện tại ĐANG MỞ (vào POS bán ngay)
"""
from __future__ import annotations

import argparse
import os
import random
import secrets
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

THU_MUC = Path(__file__).resolve().parent
VN = ZoneInfo("Asia/Ho_Chi_Minh")

MAT_KHAU_CHUNG = "Demo@2026"
MAT_KHAU_NHAN_VIEN = secrets.token_urlsafe(32)
ADMIN_PW = secrets.token_urlsafe(32)

def _chuan_bi_moi_truong(duong_dan: Path) -> None:
    os.environ["DB_PATH"] = str(duong_dan)
    os.environ["UPLOAD_DIR"] = str(THU_MUC / "static" / "uploads")
    os.environ["LOG_FILE"] = str(Path(tempfile.gettempdir()) / "fselling_seed_full.txt")
    os.environ["SECRET_KEY"] = "seed-demo-full-secret-key-2026-very-secure-and-long-enough-32bytes"
    os.environ["ADMIN_INITIAL_PASSWORD"] = ADMIN_PW
    os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:8000,http://localhost:8000"
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASSWORD"] = ""


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ok(res, viec: str):
    if res.status_code not in (200, 201):
        print(f"\n[LỖI] ở bước '{viec}': HTTP {res.status_code} - {res.text}")
        sys.exit(1)
    return res.json()


def _prepare_database_reset(
    duong_dan: Path, *, confirmed: bool, now: datetime | None = None
) -> Path | None:
    """Keep a verified snapshot before replacing an existing demo database."""
    if not duong_dan.exists():
        return None
    if not confirmed:
        raise ValueError(
            "Database đã tồn tại. Chạy lại với --yes-reset nếu thật sự muốn "
            "thay bằng dữ liệu demo."
        )

    from fselling.migration.backup import create_verified_backup

    stamp = (now or datetime.now(VN)).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = duong_dan.with_name(
        f"{duong_dan.stem}.pilot-backup-{stamp}{duong_dan.suffix}"
    )
    create_verified_backup(duong_dan, backup_path)
    try:
        duong_dan.unlink()
    except OSError as exc:
        raise RuntimeError(
            "Không thể thay database khi F-Selling còn đang chạy. Hãy dừng "
            f"server rồi thử lại; bản sao an toàn nằm tại {backup_path.name}."
        ) from exc
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Tạo dữ liệu demo toàn diện cho F-Selling")
    parser.add_argument("--db", default=str(THU_MUC / "fselling_v4.db"))
    parser.add_argument(
        "--yes-reset",
        action="store_true",
        help="xác nhận thay database hiện có sau khi tạo backup đã kiểm chứng",
    )
    args = parser.parse_args()

    duong_dan = Path(args.db).resolve()
    print(f"=== Đang chuẩn bị tạo dữ liệu demo vào: {duong_dan.name} ===")

    try:
        backup_path = _prepare_database_reset(
            duong_dan, confirmed=args.yes_reset
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if backup_path:
        print(f"-> Đã tạo và kiểm chứng backup: {backup_path.name}")

    _chuan_bi_moi_truong(duong_dan)
    sys.path.insert(0, str(THU_MUC))

    from fselling.migration.coordinator import MigrationCoordinator
    print(f"-> Đang khởi tạo cấu trúc bảng (schema) cho {duong_dan.name}...")
    coord = MigrationCoordinator(duong_dan)
    coord.init()
    coord.upgrade("head")

    from fastapi.testclient import TestClient
    from fselling import models
    from fselling.core.database import SessionLocal
    from fselling.main import create_app

    rng = random.Random(20260819)
    hom_nay = datetime.now(VN).date()

    with TestClient(create_app()) as client:
        # =====================================================================
        # 1. TÀI KHOẢN ADMIN & SELLER (demo)
        # =====================================================================
        print("1. Khởi tạo tài khoản...")
        # Đăng ký seller demo
        _ok(
            client.post(
                "/api/auth/register",
                json={
                    "username": "demo",
                    "password": MAT_KHAU_CHUNG,
                    "email": "demo@example.com",
                },
            ),
            "Đăng ký tài khoản demo",
        )

        # Kích hoạt xác minh user demo & cập nhật admin
        session = SessionLocal()
        try:
            u_demo = session.query(models.User).filter(models.User.username == "demo").first()
            if u_demo:
                u_demo.is_verified = True
                u_demo.verification_code = None

            # Đồng bộ admin
            u_admin = session.query(models.User).filter(models.User.username == "admin").first()
            if u_admin:
                u_admin.is_verified = True
            session.commit()
        finally:
            session.close()

        # Login seller
        token_seller = _ok(
            client.post("/api/auth/login", json={"username": "demo", "password": MAT_KHAU_CHUNG}),
            "Đăng nhập seller demo",
        )["access_token"]

        # Login admin
        token_admin = _ok(
            client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}),
            "Đăng nhập admin",
        )["access_token"]

        # =====================================================================
        # 2. TẠO CỬA HÀNG & GÁN GÓI PRO
        # =====================================================================
        print("2. Tạo cửa hàng & kích hoạt gói PRO...")
        shop = _ok(
            client.post(
                "/api/shops",
                json={
                    "name": "Tạp Hóa Bà Tư - Siêu Thị Mini",
                    "business_address": "12 Nguyễn Trãi, Phường Mỹ Long, TP. Long Xuyên, An Giang",
                    "tax_code": "1601234567",
                    "phone": "0919000111",
                    "email": "batu@example.com",
                    "bank_account_no": "0071000123456",
                    "bank_account_name": "NGUYEN THI TU",
                    "bank_code": "VCB",
                },
                headers=_auth(token_seller),
            ),
            "Tạo cửa hàng",
        )
        shop_id = shop["id"]

        # Tặng gói PRO 1 năm qua Admin API
        _ok(
            client.post(
                f"/api/admin/subscriptions/{shop_id}/gifts",
                json={
                    "expires_on": (hom_nay + timedelta(days=365)).isoformat(),
                    "reason": "Kích hoạt gói PRO Demo đầy đủ tính năng",
                    "operation_id": f"gift-pro-{rng.randint(10**6, 10**7)}",
                },
                headers=_auth(token_admin),
            ),
            "Tặng gói PRO",
        )

        # =====================================================================
        # 3. TẠO TÀI KHOẢN NHÂN VIÊN (STAFF - CASHIER)
        # =====================================================================
        print("3. Tạo tài khoản nhân viên thu ngân...")
        _ok(
            client.post(
                f"/api/staff/{shop_id}",
                json={
                    "username": "nhanvien",
                    "password": MAT_KHAU_NHAN_VIEN,
                    "staff_role": "CASHIER",
                },
                headers=_auth(token_seller),
            ),
            "Tạo tài khoản nhân viên",
        )

        # =====================================================================
        # 4. DANH MỤC & SẢN PHẨM (Standard + Batches + Variants)
        # =====================================================================
        print("4. Tạo danh mục và hàng hóa...")
        categories_data = [
            "Nước giải khát",
            "Sữa & Bánh kẹo",
            "Đồ khô & Gia vị",
            "Hàng gia dụng & Hóa mỹ phẩm",
            "Thời trang & Phụ kiện",
        ]
        cats = {}
        for cat_name in categories_data:
            c = _ok(
                client.post(
                    "/api/categories",
                    params={"name": cat_name, "shop_id": shop_id},
                    headers=_auth(token_seller),
                ),
                f"Tạo danh mục {cat_name}",
            )
            cats[cat_name] = c["id"]

        # Danh sách sản phẩm:
        # (tên, giá bán, giá vốn, nhóm danh mục, theo lô HSD, tốc độ bán/ngày, tồn còn lại muốn giữ)
        HANG_HOA_CONFIG = [
            # Nước giải khát
            ("Nước suối Lavie 500ml", 5000, 3500, "Nước giải khát", False, 15.0, 20),
            ("Coca Cola lon 330ml", 10000, 7500, "Nước giải khát", False, 10.0, 5),
            ("Nước tăng lực Red Bull 250ml", 15000, 11000, "Nước giải khát", False, 8.0, 15),
            ("Trà xanh Không Độ 450ml", 10000, 7000, "Nước giải khát", False, 6.0, 10),

            # Sữa & Bánh kẹo (Có theo dõi Lô Hạn - FEFO)
            ("Sữa tươi Vinamilk 1L", 34000, 27000, "Sữa & Bánh kẹo", True, 7.0, 25),
            ("Sữa chua Vinamilk lốc 4", 28000, 22000, "Sữa & Bánh kẹo", True, 5.0, 15),
            ("Bánh mì sandwich Kinh Đô", 20000, 14000, "Sữa & Bánh kẹo", True, 4.0, 12),
            ("Sữa chua uống Probi 65ml", 26000, 20000, "Sữa & Bánh kẹo", True, 4.0, 10),
            ("Bánh trung thu Kinh Đô", 85000, 62000, "Sữa & Bánh kẹo", True, 0.2, 18), # Hàng ế

            # Đồ khô & Gia vị
            ("Mì Hảo Hảo tôm chua cay", 4500, 3400, "Đồ khô & Gia vị", False, 25.0, 80),
            ("Dầu ăn Neptune 1L", 55000, 45000, "Đồ khô & Gia vị", False, 3.0, 15),
            ("Nước mắm Nam Ngư 500ml", 32000, 25000, "Đồ khô & Gia vị", False, 2.5, 12),
            ("Gạo ST25 túi 5kg", 165000, 140000, "Đồ khô & Gia vị", False, 1.2, 8),
            ("Tương ớt Chinsu 250g", 16000, 12000, "Đồ khô & Gia vị", False, 3.0, 20),

            # Hàng gia dụng
            ("Bột giặt Omo 800g", 48000, 39000, "Hàng gia dụng & Hóa mỹ phẩm", False, 1.5, 8),
            ("Nước rửa chén Sunlight 750g", 28000, 21000, "Hàng gia dụng & Hóa mỹ phẩm", False, 2.0, 10),
            ("Khăn giấy Bless You 3 lớp", 12000, 8500, "Hàng gia dụng & Hóa mỹ phẩm", False, 0.1, 30), # Hàng ế

            # Thời trang
            ("Áo thun F-Selling Cotton - Size M", 120000, 75000, "Thời trang & Phụ kiện", False, 0.8, 12),
            ("Áo thun F-Selling Cotton - Size L", 120000, 75000, "Thời trang & Phụ kiện", False, 1.0, 10),
            ("Áo thun F-Selling Cotton - Size XL", 130000, 80000, "Thời trang & Phụ kiện", False, 0.5, 6),
        ]

        products = {}
        for ten, gia, _von, nhom, theo_lo, _toc_do, _con_lai in HANG_HOA_CONFIG:
            bien_the = (
                ten.removeprefix("Áo thun F-Selling Cotton - ")
                if ten.startswith("Áo thun F-Selling Cotton - ") else ""
            )
            du_lieu = {
                "name": "Áo thun F-Selling Cotton" if bien_the else ten,
                "price": gia,
                "stock": 0,
                "category_id": cats[nhom],
            }
            if bien_the:
                du_lieu["variant_name"] = bien_the
            if theo_lo:
                du_lieu["track_batches"] = "true"
            p = _ok(
                client.post(
                    "/api/products",
                    params={"shop_id": shop_id},
                    data=du_lieu,
                    headers=_auth(token_seller),
                ),
                f"Tạo sản phẩm {ten}",
            )
            products[ten] = p["id"]

        # =====================================================================
        # 5. NHÀ CUNG CẤP & PHIẾU NHẬP HÀNG (Kèm Lô Hạn & Nợ NCC)
        # =====================================================================
        print("5. Tạo nhà cung cấp và nhập kho ban đầu...")
        ncc_list = {
            "Công ty TNHH Phân phối Miền Tây": ("02963811222", "1601234567", "Long Xuyên, An Giang"),
            "Đại lý Sữa & Bánh Ngọc Hân": ("0913222444", "1609876543", "Chợ Mới, An Giang"),
            "Xưởng May & Thời Trang Nam Việt": ("0908889999", "0301122334", "Tân Bình, TP.HCM"),
        }
        suppliers = {}
        for ten_ncc, (sdt, mst, dc) in ncc_list.items():
            s = _ok(
                client.post(
                    f"/api/suppliers/{shop_id}",
                    json={
                        "name": ten_ncc,
                        "phone": sdt,
                        "tax_code": mst,
                        "address": dc,
                        "operation_id": f"seed-ncc-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                f"Tạo NCC {ten_ncc}",
            )
            suppliers[ten_ncc] = s["id"]

        # Tính lịch bán 30 ngày để nhập đủ hàng
        SO_NGAY = 30
        lich_ban = {}
        for ten, _gia, _von, _nhom, _lo, toc_do, _con_lai in HANG_HOA_CONFIG:
            lich_ban[ten] = [
                max(0, round(rng.gauss(toc_do, toc_do * 0.3))) if toc_do > 0 else 0
                for _ in range(SO_NGAY)
            ]

        # Chuẩn bị dòng nhập cho từng NCC
        ngay_nhap_cu = (hom_nay - timedelta(days=SO_NGAY + 2)).isoformat()
        dong_theo_ncc = {k: [] for k in suppliers}

        for ten, _gia, von, nhom, theo_lo, _toc_do, con_lai in HANG_HOA_CONFIG:
            can_nhap = sum(lich_ban[ten]) + con_lai
            if can_nhap <= 0:
                continue

            if nhom == "Sữa & Bánh kẹo":
                ncc_ten = "Đại lý Sữa & Bánh Ngọc Hân"
            elif nhom == "Thời trang & Phụ kiện":
                ncc_ten = "Xưởng May & Thời Trang Nam Việt"
            else:
                ncc_ten = "Công ty TNHH Phân phối Miền Tây"

            dong = {
                "product_id": products[ten],
                "quantity": can_nhap,
                "unit_cost": von,
            }
            if theo_lo:
                # Đặt hạn sử dụng: một số món sắp hết hạn (12-25 ngày) để demo Clearance, một số món 90 ngày
                if "Probi" in ten or "sandwich" in ten or "trung thu" in ten:
                    dong["expiry_date"] = (hom_nay + timedelta(days=rng.randint(10, 20))).isoformat()
                else:
                    dong["expiry_date"] = (hom_nay + timedelta(days=rng.randint(60, 120))).isoformat()
            dong_theo_ncc[ncc_ten].append(dong)

        # Tạo và xác nhận phiếu nhập
        for ncc_ten, items in dong_theo_ncc.items():
            if not items:
                continue
            phieu = _ok(
                client.post(
                    f"/api/purchase-receipts/{shop_id}",
                    json={
                        "supplier_id": suppliers[ncc_ten],
                        "items": items,
                        "received_date": ngay_nhap_cu,
                        "note": f"Phiếu nhập đầu kỳ từ {ncc_ten}",
                        "operation_id": f"seed-po-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                f"Tạo phiếu nhập {ncc_ten}",
            )
            # Với NCC Miền Tây: trả trước 1 nửa, để lại NỢ NCC để demo tính năng trả nợ NCC!
            tong_tien = sum(i["quantity"] * i["unit_cost"] for i in items)
            tra_tien = tong_tien if ncc_ten != "Công ty TNHH Phân phối Miền Tây" else tong_tien // 2

            _ok(
                client.post(
                    f"/api/purchase-receipts/receipt/{phieu['id']}/confirm",
                    json={
                        "operation_id": f"seed-confirm-po-{rng.randint(10**6, 10**7)}",
                        "draft_fingerprint": phieu["draft_fingerprint"],
                        "paid_amount": tra_tien,
                        "method": "TRANSFER" if tra_tien > 0 else None,
                        "note": "Xác nhận nhập kho" + (" (Còn nợ)" if tra_tien < tong_tien else " (Đã thanh toán đủ)"),
                    },
                    headers=_auth(token_seller),
                ),
                f"Xác nhận phiếu nhập {ncc_ten}",
            )

        # =====================================================================
        # 6. KHÁCH HÀNG CRM & CHƯƠNG TRÌNH TÍCH ĐIỂM LOYALTY
        # =====================================================================
        print("6. Cấu hình Khách hàng CRM & Loyalty...")
        # Cấu hình Loyalty: 10k = 1 điểm, 1 điểm = 1000đ
        _ok(
            client.put(
                f"/api/loyalty/{shop_id}",
                json={
                    "enabled": True,
                    "earn_amount": 10000,
                    "earn_points": 1,
                    "redeem_points": 1,
                    "redeem_amount": 1000,
                    "min_redeem_points": 10,
                    "max_redeem_percent": 50,
                    "expiry_days": 365,
                },
                headers=_auth(token_seller),
            ),
            "Cấu hình chương trình Loyalty",
        )

        customers_data = [
            ("Nguyễn Văn An", "0918123456", "45 Trần Hưng Đạo, Long Xuyên", "Khách VIP quen thuộc", 5000000),
            ("Trần Thị Mai", "0987654321", "88 Lê Lợi, Long Xuyên", "Khách thân thiết", 2000000),
            ("Lê Hoàng Nam", "0903111222", "12 Hà Hoàng Hổ, Long Xuyên", "Khách vãng lai", 1000000),
            ("Phạm Thu Hương", "0934555666", "Chợ Mỹ Bình, Long Xuyên", "Khách mới", 1000000),
        ]
        customers = {}
        for ten_kh, sdt_kh, dc_kh, ghi_chu, limit in customers_data:
            kh = _ok(
                client.post(
                    f"/api/customers/{shop_id}",
                    json={
                        "name": ten_kh,
                        "phone": sdt_kh,
                        "address": dc_kh,
                        "note": ghi_chu,
                        "credit_limit": limit,
                    },
                    headers=_auth(token_seller),
                ),
                f"Tạo khách hàng {ten_kh}",
            )
            customers[ten_kh] = kh["id"]

        # =====================================================================
        # 7. VOUCHERS / MÃ GIẢM GIÁ
        # =====================================================================
        print("7. Tạo mã khuyến mãi (Vouchers)...")
        vouchers = [
            {
                "code": "CHAOBANMOI",
                "discount_type": "percentage",
                "discount_value": 10,
                "min_order_value": 50000,
                "max_discount": 30000,
                "usage_limit": 100,
            },
            {
                "code": "GIAM20K",
                "discount_type": "flat",
                "discount_value": 20000,
                "min_order_value": 150000,
                "max_discount": 20000,
                "usage_limit": 50,
            },
            {
                "code": "TRIANKHACH",
                "discount_type": "percentage",
                "discount_value": 15,
                "min_order_value": 200000,
                "max_discount": 50000,
                "usage_limit": 50,
            },
        ]
        for v in vouchers:
            _ok(
                client.post(
                    "/api/vouchers",
                    params={"shop_id": shop_id},
                    json=v,
                    headers=_auth(token_seller),
                ),
                f"Tạo voucher {v['code']}",
            )

        # =====================================================================
        # 8. BÁN HÀNG 30 NGÀY (Đơn thường, Đơn QR, Đơn Nợ DEBT, Đơn Trả Hàng)
        # =====================================================================
        print("8. Sinh lịch sử 30 ngày bán hàng...")
        so_don = 0
        order_to_return_id = None
        order_to_return_item_id = None

        for chi_so_ngay in range(SO_NGAY):
            so_ngay_truoc = SO_NGAY - 1 - chi_so_ngay
            ngay_gio_ban = datetime.utcnow() - timedelta(days=so_ngay_truoc)

            # Phân bổ các món cần bán trong ngày vào 3-4 đơn hàng
            don_trong_ngay = [[] for _ in range(3)]
            for ten, *_ in HANG_HOA_CONFIG:
                so_luong = lich_ban[ten][chi_so_ngay]
                while so_luong > 0:
                    d_idx = rng.randrange(3)
                    lay = min(so_luong, rng.randint(1, max(1, so_luong)))
                    don_trong_ngay[d_idx].append({
                        "product_id": products[ten],
                        "price": 1,
                        "quantity": lay
                    })
                    so_luong -= lay

            for d_idx, gio in enumerate(don_trong_ngay):
                if not gio:
                    continue

                # Tất cả đơn lịch sử thu bằng tiền mặt để hoàn tất thanh toán
                pttt = "cash"
                kh_id = None
                if chi_so_ngay % 3 == 0:
                    kh_id = customers["Nguyễn Văn An"]
                elif chi_so_ngay % 3 == 1:
                    kh_id = customers["Trần Thị Mai"]

                payload = {
                    "items": gio,
                    "payment_method": pttt,
                    "customer_id": kh_id,
                }
                don = _ok(
                    client.post(f"/api/orders/{shop_id}", json=payload, headers=_auth(token_seller)),
                    f"Tạo đơn ngày -{so_ngay_truoc}",
                )
                order_id = don["order_id"]
                so_don += 1

                # Thu tiền
                _ok(
                    client.post(
                        f"/api/orders/{order_id}/pay",
                        json={"tendered_amount": don["total"]},
                        headers=_auth(token_seller),
                    ),
                    f"Thu tiền đơn {order_id}",
                )

                # Lùi timestamp về đúng ngày trong lịch sử
                session = SessionLocal()
                try:
                    o = session.query(models.Order).filter(models.Order.id == order_id).first()
                    o.created_at = ngay_gio_ban.replace(
                        hour=rng.randint(8, 20), minute=rng.randint(0, 59), second=rng.randint(0, 59)
                    )
                    session.commit()

                    # Lưu lại 1 đơn để tạo phiếu trả hàng
                    if so_ngay_truoc == 3 and not order_to_return_id and len(o.items) > 0:
                        order_to_return_id = order_id
                        order_to_return_item_id = o.items[0].id
                finally:
                    session.close()

        # Tạo 1 đơn GHI NỢ (DEBT) cho khách Nguyễn Văn An (để demo thu nợ / đối soát)
        print("-> Tạo đơn hàng ghi nợ (DEBT) cho khách hàng...")
        don_no = _ok(
            client.post(
                f"/api/orders/{shop_id}",
                json={
                    "items": [
                        {"product_id": products["Gạo ST25 túi 5kg"], "price": 1, "quantity": 2},
                        {"product_id": products["Dầu ăn Neptune 1L"], "price": 1, "quantity": 2},
                        {"product_id": products["Nước mắm Nam Ngư 500ml"], "price": 1, "quantity": 1},
                    ],
                    "payment_method": "debt",
                    "customer_id": customers["Nguyễn Văn An"],
                },
                headers=_auth(token_seller),
            ),
            "Tạo đơn ghi nợ DEBT",
        )

        # Tạo 1 phiếu ĐỔI/TRẢ HÀNG (Order Return)
        if order_to_return_id and order_to_return_item_id:
            print("-> Tạo phiếu trả hàng (Order Return)...")
            _ok(
                client.post(
                    f"/api/orders/{order_to_return_id}/returns",
                    json={
                        "items": [{"order_item_id": order_to_return_item_id, "quantity": 1, "restock": True}],
                        "method": "transfer",
                        "reason": "Khách mua nhầm loại, đổi trả nguyên vẹn",
                        "operation_id": f"seed-return-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                "Tạo phiếu trả hàng",
            )

        # =====================================================================
        # 9. PHIẾU HỦY HÀNG HỎNG/HẾT HẠN (Stock Write-Off)
        # =====================================================================
        print("9. Tạo phiếu hủy hàng hỏng/hết hạn...")
        session = SessionLocal()
        try:
            # Lấy 1 batch của sữa chua hoặc bánh sandwich
            lo_sua = session.query(models.ProductBatch).filter(
                models.ProductBatch.product_id == products["Sữa chua Vinamilk lốc 4"]
            ).first()
            if lo_sua:
                _ok(
                    client.post(
                        f"/api/products/{shop_id}/write-off",
                        json={
                            "reason": "DAMAGED",
                            "items": [
                                {
                                    "product_id": products["Sữa chua Vinamilk lốc 4"],
                                    "batch_id": lo_sua.id,
                                    "quantity": 2,
                                }
                            ],
                            "note": "2 lốc sữa chua bị cấn rách vỏ bọc khi xếp lên kệ",
                            "operation_id": f"seed-writeoff-{rng.randint(10**6, 10**7)}",
                        },
                        headers=_auth(token_seller),
                    ),
                    "Tạo phiếu hủy hàng",
                )
        finally:
            session.close()

        # =====================================================================
        # 10. CHI PHÍ HOẠT ĐỘNG & PHÂN BỔ CHI PHÍ TRẢ TRƯỚC (Expenses)
        # =====================================================================
        print("10. Tạo danh mục và chi phí vận hành...")
        # Lấy danh mục chi phí đã seed
        cats_exp = _ok(client.get(f"/api/expense-categories/{shop_id}", headers=_auth(token_seller)), "Lấy danh mục chi phí")
        cat_map = {c["name"]: c["id"] for c in cats_exp.get("categories", [])}

        # Tạo mẫu nhắc chi phí định kỳ
        if "Thuê mặt bằng" in cat_map:
            _ok(
                client.post(
                    f"/api/expense-templates/{shop_id}",
                    json={
                        "category_id": cat_map["Thuê mặt bằng"],
                        "name": "Tiền thuê nhà số 12 Nguyễn Trãi",
                        "amount": 3000000,
                        "day_of_month": 5,
                        "note": "Hợp đồng thuê 2 năm",
                    },
                    headers=_auth(token_seller),
                ),
                "Tạo mẫu chi phí thuê mặt bằng",
            )
        if "Điện nước" in cat_map:
            _ok(
                client.post(
                    f"/api/expense-templates/{shop_id}",
                    json={
                        "category_id": cat_map["Điện nước"],
                        "name": "Tiền điện sinh hoạt cửa hàng",
                        "amount": 1500000,
                        "day_of_month": 15,
                        "note": "Theo hóa đơn EVN",
                    },
                    headers=_auth(token_seller),
                ),
                "Tạo mẫu chi phí điện nước",
            )
        if "Internet / Điện thoại" in cat_map:
            _ok(
                client.post(
                    f"/api/expense-templates/{shop_id}",
                    json={
                        "category_id": cat_map["Internet / Điện thoại"],
                        "name": "Cước Internet cáp quang VNPT",
                        "amount": 350000,
                        "day_of_month": 20,
                        "note": "Gói doanh nghiệp 150Mbps",
                    },
                    headers=_auth(token_seller),
                ),
                "Tạo mẫu chi phí Internet",
            )

        # Ghi các khoản chi thực tế:
        # 1. Thuê mặt bằng 6 tháng trả trước 18tr (Phân bổ 6 tháng -> demo công thức amortize)
        if "Thuê mặt bằng" in cat_map:
            ngay_dau_thang = (hom_nay.replace(day=1)).isoformat()
            _ok(
                client.post(
                    f"/api/expenses/{shop_id}",
                    json={
                        "category_id": cat_map["Thuê mặt bằng"],
                        "amount": 18000000,
                        "expense_date": ngay_dau_thang,
                        "amortize_months": 6,
                        "amortize_start_date": ngay_dau_thang,
                        "method": "TRANSFER",
                        "note": "Thanh toán tiền thuê mặt bằng 6 tháng (T8/2026 - T1/2027)",
                        "reference": "UNC-THUEMATBANG-06T",
                        "operation_id": f"seed-exp-rent-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                "Ghi chi phí thuê mặt bằng trả trước 6 tháng",
            )

        # 2. Tiền điện nước tháng này
        if "Điện nước" in cat_map:
            _ok(
                client.post(
                    f"/api/expenses/{shop_id}",
                    json={
                        "category_id": cat_map["Điện nước"],
                        "amount": 1650000,
                        "expense_date": (hom_nay - timedelta(days=5)).isoformat(),
                        "method": "TRANSFER",
                        "note": "Tiền điện kinh doanh tháng vừa qua",
                        "reference": "EVN-8849201",
                        "operation_id": f"seed-exp-elec-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                "Ghi chi phí điện nước",
            )

        # 3. Tiền Internet
        if "Internet / Điện thoại" in cat_map:
            _ok(
                client.post(
                    f"/api/expenses/{shop_id}",
                    json={
                        "category_id": cat_map["Internet / Điện thoại"],
                        "amount": 350000,
                        "expense_date": (hom_nay - timedelta(days=8)).isoformat(),
                        "method": "TRANSFER",
                        "note": "Cước Internet tháng 8/2026",
                        "reference": "VNPT-109283",
                        "operation_id": f"seed-exp-net-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                "Ghi chi phí Internet",
            )

        # 4. Lương nhân viên
        if "Lương nhân viên" in cat_map:
            _ok(
                client.post(
                    f"/api/expenses/{shop_id}",
                    json={
                        "category_id": cat_map["Lương nhân viên"],
                        "amount": 6000000,
                        "expense_date": (hom_nay - timedelta(days=10)).isoformat(),
                        "method": "TRANSFER",
                        "note": "Lương tháng cho nhân viên thu ngân",
                        "operation_id": f"seed-exp-salary-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token_seller),
                ),
                "Ghi chi phí lương nhân viên",
            )

        # =====================================================================
        # 11. CA BÁN HÀNG (Shifts): 1 Ca cũ đã đóng + 1 Ca mới ĐANG MỞ
        # =====================================================================
        print("11. Khởi tạo ca bán hàng (Shifts)...")
        # Mở ca cũ hôm qua
        shift_old = _ok(
            client.post(
                f"/api/shifts/{shop_id}/open",
                json={"opening_cash_amount": 1000000, "note": "Ca sáng hôm qua"},
                headers=_auth(token_seller),
            ),
            "Mở ca cũ",
        )
        # Đóng ca cũ với số tiền đếm khớp
        _ok(
            client.post(
                f"/api/shifts/{shop_id}/close",
                json={"counted_cash_amount": 1850000, "note": "Kết ca hôm qua, két khớp"},
                headers=_auth(token_seller),
            ),
            "Đóng ca cũ",
        )

        # Mở CA HIỆN TẠI ĐANG HOẠT ĐỘNG (để vào POS bán được ngay)
        _ok(
            client.post(
                f"/api/shifts/{shop_id}/open",
                json={"opening_cash_amount": 1000000, "note": "Ca bán hàng hôm nay đang mở"},
                headers=_auth(token_seller),
            ),
            "Mở ca hiện tại",
        )

    print("\n" + "=" * 65)
    print("  ✅ TẠO DỮ LIỆU DEMO TOÀN DIỆN THÀNH CÔNG!")
    print("=" * 65)
    print(f"  📁 File Database : {duong_dan.name}")
    print(f"  🏪 Cửa hàng      : Tạp Hóa Bà Tư - Siêu Thị Mini (Gói PRO)")
    print(f"  📦 Hàng hóa      : {len(HANG_HOA_CONFIG)} sản phẩm (Standard, Batches, Variants)")
    print(f"  🛒 Đơn hàng      : {so_don} đơn (30 ngày lịch sử + Đơn nợ + Đơn trả)")
    print(f"  👥 Khách hàng    : 4 khách CRM (Điểm Loyalty, Hạn mức nợ)")
    print(f"  🏭 Nhà cung cấp  : 3 NCC (Kèm công nợ chưa trả)")
    print(f"  💸 Chi phí       : Thuê mặt bằng (phân bổ 6T), Điện nước, Lương")
    print(f"  ⏰ Ca bán hàng   : Ca hiện tại ĐANG MỞ (1.000.000đ tiền két)")
    print("-" * 65)
    print("  🔑 TÀI KHOẢN DEMO CÓ THỂ CHIA SẺ:")
    print("  Chủ shop (SELLER):")
    print("     - Tài khoản: demo")
    print("     - Mật khẩu : Demo@2026")
    print("  Không nhập dữ liệu cá nhân hoặc dữ liệu kinh doanh thật.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
