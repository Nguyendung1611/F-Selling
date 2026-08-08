"""Tạo một cơ sở dữ liệu DEMO có đủ dữ liệu để xem màn Dự Báo Nhập Hàng.

Vì sao cần script này: màn dự báo cần 30 ngày lịch sử bán, giá vốn, lô hạn và
nhà cung cấp. Cơ sở dữ liệu đang dùng chưa có mấy thứ đó, nên màn hình sẽ trống
trơn dù code chạy đúng - và người xem sẽ đi tìm một cái lỗi không tồn tại.

CÁCH CHẠY (trong thư mục python_app):

    .\\.venv\\Scripts\\python.exe seed_demo.py
    $env:DB_PATH="$PWD\\fselling_demo.db"
    .\\.venv\\Scripts\\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000

Rồi đăng nhập bằng tài khoản in ra ở cuối.

AN TOÀN: script này chỉ ghi vào file DB do nó tạo ra (mặc định
``fselling_demo.db``) và từ chối chạy nếu bị trỏ vào một trong các file dữ liệu
thật. Muốn ghi đè file demo cũ thì thêm cờ ``--ghi-de``.

Dữ liệu được dựng bằng chính API của app (đăng ký -> tạo shop -> nhập hàng ->
bán hàng), không phải bằng cách chèn thẳng vào bảng. Nhờ vậy mọi ràng buộc mà
app dựa vào - giá vốn bình quân, tồn theo lô, công nợ nhà cung cấp - đều đúng
như hàng thật, chứ không phải một mớ số nhìn giống thật.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

THU_MUC = Path(__file__).resolve().parent

# Không bao giờ được ghi đè các file này, kể cả khi người dùng gõ nhầm tên.
DB_THAT = {
    "fselling.db", "fselling_v2.db", "fselling_v3.db", "fselling_v4.db",
}

MAT_KHAU_DEMO = "Demo@2026"
VN = ZoneInfo("Asia/Ho_Chi_Minh")

# (tên, giá bán, giá vốn, bán trung bình mỗi ngày, tồn muốn còn lại, theo lô)
#
# Các con số được chọn để mỗi trạng thái của màn dự báo đều có ít nhất một mặt
# hàng đại diện: hết sạch, sắp cháy hàng, cần nhập, ổn định, và hàng nằm ế.
HANG_HOA = [
    ("Nước suối Lavie 500ml",        5000,   3500, 12.0,   8, False),
    ("Coca Cola lon 330ml",         10000,   7500,  8.0,   0, False),
    ("Mì Hảo Hảo tôm chua cay",      4500,   3400, 20.0,  90, False),
    ("Sữa tươi Vinamilk 1L",        34000,  27000,  6.0,  30, True),
    ("Sữa chua Vinamilk lốc 4",     28000,  22000,  4.0,  12, True),
    ("Bánh mì sandwich Kinh Đô",    20000,  14000,  3.0,  40, False),
    ("Dầu ăn Neptune 1L",           55000,  45000,  2.0,  25, False),
    ("Nước mắm Nam Ngư 500ml",      32000,  25000,  1.5,  20, False),
    ("Gạo ST25 túi 5kg",           165000, 140000,  0.7,  12, False),
    ("Bột giặt Omo 800g",           48000,  39000,  1.0,   6, False),
    ("Khăn giấy Bless You",         12000,   8500,  0.0,  30, False),
    ("Bánh trung thu Kinh Đô",      85000,  62000,  0.0,  24, True),
]

SO_NGAY = 30
SO_DON_MOI_NGAY = 3


def _kiem_tra_duong_dan(duong_dan: Path, ghi_de: bool) -> None:
    if duong_dan.name in DB_THAT:
        sys.exit(
            f"TỪ CHỐI: '{duong_dan.name}' là file dữ liệu thật. "
            "Script demo không bao giờ ghi vào đó. Chọn tên khác."
        )
    if duong_dan.exists():
        if not ghi_de:
            sys.exit(
                f"File '{duong_dan}' đã có rồi. Thêm --ghi-de nếu muốn xóa và tạo lại."
            )
        duong_dan.unlink()


def _chuan_bi_moi_truong(duong_dan: Path) -> None:
    """Phải đặt TRƯỚC khi import package - config đọc env ngay lúc import."""
    os.environ["DB_PATH"] = str(duong_dan)
    os.environ["UPLOAD_DIR"] = str(THU_MUC / "static" / "uploads")
    # Log của script để trong thư mục tạm của máy, không rải file rác vào dự án.
    os.environ["LOG_FILE"] = str(Path(tempfile.gettempdir()) / "fselling_seed_demo.txt")
    os.environ["SECRET_KEY"] = "seed-demo-khong-dung-cho-that"
    os.environ["ADMIN_INITIAL_PASSWORD"] = MAT_KHAU_DEMO
    os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:8000"
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASSWORD"] = ""


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ok(res, viec: str):
    if res.status_code != 200:
        sys.exit(f"Hỏng ở bước '{viec}': HTTP {res.status_code} - {res.text}")
    return res.json()


def _so_luong_ban(rng: random.Random, trung_binh: float) -> int:
    """Số bán của một ngày, dao động quanh mức trung bình.

    Có dao động thật thì đệm dự phòng (độ lệch chuẩn) mới có ý nghĩa; cho bán
    đều tăm tắp là dựng một thế giới không tồn tại rồi khoe công thức chạy đúng
    trong đó.
    """
    if trung_binh <= 0:
        return 0
    return max(0, round(rng.gauss(trung_binh, trung_binh * 0.35)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Đổ dữ liệu mẫu cho bản demo")
    parser.add_argument("--db", default=str(THU_MUC / "fselling_demo.db"))
    parser.add_argument("--ghi-de", action="store_true")
    args = parser.parse_args()

    duong_dan = Path(args.db).resolve()
    _kiem_tra_duong_dan(duong_dan, args.ghi_de)
    _chuan_bi_moi_truong(duong_dan)

    sys.path.insert(0, str(THU_MUC))
    from fastapi.testclient import TestClient

    from fselling import models
    from fselling.core.database import SessionLocal
    from fselling.main import create_app

    rng = random.Random(20260809)
    hom_nay = datetime.now(VN).date()

    print(f"Đang tạo dữ liệu demo trong: {duong_dan}")
    with TestClient(create_app()) as client:
        # --- Tài khoản chủ shop ---
        ten_dang_nhap = "demo"
        _ok(
            client.post(
                "/api/auth/register",
                json={
                    "username": ten_dang_nhap,
                    "password": MAT_KHAU_DEMO,
                    "email": "demo@example.com",
                },
            ),
            "đăng ký tài khoản demo",
        )
        session = SessionLocal()
        try:
            u = (
                session.query(models.User)
                .filter(models.User.username == ten_dang_nhap)
                .first()
            )
            u.is_verified = True
            u.verification_code = None
            u.verification_code_sent_at = None
            session.commit()
        finally:
            session.close()

        token = _ok(
            client.post(
                "/api/auth/login",
                json={"username": ten_dang_nhap, "password": MAT_KHAU_DEMO},
            ),
            "đăng nhập",
        )["access_token"]

        shop_id = _ok(
            client.post(
                "/api/shops",
                json={
                    "name": "Tạp hóa Bà Tư",
                    "business_address": "12 Nguyễn Trãi, Long Xuyên, An Giang",
                    "tax_code": "1601234567",
                    "phone": "0919000111",
                    "email": "batu@example.com",
                    "bank_account_no": "0071000123456",
                    "bank_account_name": "NGUYEN THI TU",
                    "bank_code": "VCB",
                },
                headers=_auth(token),
            ),
            "tạo cửa hàng",
        )["id"]

        danh_muc = {}
        for ten in ("Nước giải khát", "Sữa & Bánh", "Đồ khô", "Gia dụng"):
            danh_muc[ten] = _ok(
                client.post(
                    "/api/categories",
                    params={"name": ten, "shop_id": shop_id},
                    headers=_auth(token),
                ),
                f"tạo danh mục {ten}",
            )["id"]
        nhom_theo_hang = {
            "Nước suối Lavie 500ml": "Nước giải khát",
            "Coca Cola lon 330ml": "Nước giải khát",
            "Mì Hảo Hảo tôm chua cay": "Đồ khô",
            "Sữa tươi Vinamilk 1L": "Sữa & Bánh",
            "Sữa chua Vinamilk lốc 4": "Sữa & Bánh",
            "Bánh mì sandwich Kinh Đô": "Sữa & Bánh",
            "Dầu ăn Neptune 1L": "Đồ khô",
            "Nước mắm Nam Ngư 500ml": "Đồ khô",
            "Gạo ST25 túi 5kg": "Đồ khô",
            "Bột giặt Omo 800g": "Gia dụng",
            "Khăn giấy Bless You": "Gia dụng",
            "Bánh trung thu Kinh Đô": "Sữa & Bánh",
        }

        # --- Sản phẩm (tồn 0; hàng vào kho bằng phiếu nhập như thật) ---
        san_pham = {}
        for ten, gia, _von, _toc_do, _con_lai, theo_lo in HANG_HOA:
            du_lieu = {
                "name": ten,
                "price": gia,
                "stock": 0,
                "category_id": danh_muc[nhom_theo_hang[ten]],
            }
            if theo_lo:
                du_lieu["track_batches"] = "true"
            san_pham[ten] = _ok(
                client.post(
                    "/api/products",
                    params={"shop_id": shop_id},
                    data=du_lieu,
                    headers=_auth(token),
                ),
                f"tạo sản phẩm {ten}",
            )["id"]

        # --- Sinh trước lịch bán 30 ngày để biết cần nhập bao nhiêu ---
        lich_ban = {ten: [] for ten, *_ in HANG_HOA}
        for ten, _gia, _von, toc_do, _con_lai, _lo in HANG_HOA:
            lich_ban[ten] = [_so_luong_ban(rng, toc_do) for _ in range(SO_NGAY)]

        # --- Nhà cung cấp + phiếu nhập ---
        nha_cung_cap = {}
        for ten_ncc, dien_thoai in (
            ("Công ty TNHH Phân phối Miền Tây", "02963811222"),
            ("Đại lý Sữa & Bánh Ngọc Hân", "0913222444"),
        ):
            nha_cung_cap[ten_ncc] = _ok(
                client.post(
                    f"/api/suppliers/{shop_id}",
                    json={
                        "name": ten_ncc,
                        "phone": dien_thoai,
                        "operation_id": f"seed-ncc-{len(nha_cung_cap)}-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token),
                ),
                f"tạo nhà cung cấp {ten_ncc}",
            )["id"]

        ngay_nhap = (hom_nay - timedelta(days=SO_NGAY + 1)).isoformat()
        dong_theo_ncc = {ten: [] for ten in nha_cung_cap}
        for ten, _gia, von, _toc_do, con_lai, theo_lo in HANG_HOA:
            can_nhap = sum(lich_ban[ten]) + con_lai
            if can_nhap <= 0:
                continue
            ncc = (
                "Đại lý Sữa & Bánh Ngọc Hân"
                if nhom_theo_hang[ten] == "Sữa & Bánh"
                else "Công ty TNHH Phân phối Miền Tây"
            )
            dong = {
                "product_id": san_pham[ten],
                "quantity": can_nhap,
                "unit_cost": von,
            }
            if theo_lo:
                # Hàng theo lô phải có hạn. Để hạn gần (10-25 ngày nữa) thì màn
                # cảnh báo hết hạn và bài toán xả hàng sau này mới có dữ liệu.
                dong["expiry_date"] = (
                    hom_nay + timedelta(days=rng.randint(10, 25))
                ).isoformat()
            dong_theo_ncc[ncc].append(dong)

        for ten_ncc, cac_dong in dong_theo_ncc.items():
            if not cac_dong:
                continue
            phieu = _ok(
                client.post(
                    f"/api/purchase-receipts/{shop_id}",
                    json={
                        "supplier_id": nha_cung_cap[ten_ncc],
                        "items": cac_dong,
                        "received_date": ngay_nhap,
                        "note": "Phiếu nhập dựng sẵn cho bản demo",
                        "operation_id": f"seed-phieu-{rng.randint(10**6, 10**7)}",
                    },
                    headers=_auth(token),
                ),
                f"tạo phiếu nhập cho {ten_ncc}",
            )
            _ok(
                client.post(
                    f"/api/purchase-receipts/receipt/{phieu['id']}/confirm",
                    json={
                        "operation_id": f"seed-chot-{rng.randint(10**6, 10**7)}",
                        "draft_fingerprint": phieu["draft_fingerprint"],
                        "paid_amount": 0,
                        "note": "Nhận hàng, hẹn trả sau",
                    },
                    headers=_auth(token),
                ),
                f"xác nhận phiếu nhập cho {ten_ncc}",
            )

        # --- Bán hàng 30 ngày ---
        so_don = 0
        for chi_so_ngay in range(SO_NGAY):
            so_ngay_truoc = SO_NGAY - 1 - chi_so_ngay
            gio_hang_trong_ngay = [[] for _ in range(SO_DON_MOI_NGAY)]
            for ten, *_ in HANG_HOA:
                con_lai = lich_ban[ten][chi_so_ngay]
                while con_lai > 0:
                    o = rng.randrange(SO_DON_MOI_NGAY)
                    lay = min(con_lai, rng.randint(1, max(1, con_lai)))
                    gio_hang_trong_ngay[o].append(
                        {"product_id": san_pham[ten], "price": 1, "quantity": lay}
                    )
                    con_lai -= lay

            for gio in gio_hang_trong_ngay:
                if not gio:
                    continue
                don = _ok(
                    client.post(
                        f"/api/orders/{shop_id}",
                        json={"items": gio, "payment_method": "cash"},
                        headers=_auth(token),
                    ),
                    f"tạo đơn ngày -{so_ngay_truoc}",
                )
                so_don += 1
                # Lùi ngày tạo. Trừ nguyên ngày khỏi một mốc UTC nên ngày Việt
                # Nam lùi đúng chừng ấy ngày, không lệ thuộc giờ chạy script.
                session = SessionLocal()
                try:
                    o = (
                        session.query(models.Order)
                        .filter(models.Order.id == don["order_id"])
                        .first()
                    )
                    moc = datetime.utcnow() - timedelta(days=so_ngay_truoc)
                    # Rải trong khung 7h-20h cho giống một ngày buôn bán thật.
                    o.created_at = moc.replace(
                        hour=rng.randint(7, 20), minute=rng.randint(0, 59)
                    )
                    session.commit()
                finally:
                    session.close()

    print(f"Xong: {len(HANG_HOA)} mặt hàng, {so_don} đơn trong {SO_NGAY} ngày.")
    print()
    print("  Đăng nhập:  " + ten_dang_nhap + " / " + MAT_KHAU_DEMO)
    print("  Cửa hàng :  Tạp hóa Bà Tư")
    print()
    print("Chạy web trên đúng dữ liệu này:")
    print(f'  $env:DB_PATH="{duong_dan}"')
    print("  .\\.venv\\Scripts\\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    main()
