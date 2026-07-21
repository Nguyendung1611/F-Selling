"""Liệt kê các đơn PENDING đang treo và số hàng chúng đang giữ trong kho.

CHỈ ĐỌC - script này không bao giờ ghi vào database (mở ở chế độ read-only).
Dùng để xem trước sẽ có gì bị ảnh hưởng TRƯỚC KHI bật tự động hủy đơn
(ORDER_PENDING_TIMEOUT_MINUTES trong .env).

Cách dùng:
    .venv\\Scripts\\python.exe liet_ke_don_treo.py
    .venv\\Scripts\\python.exe liet_ke_don_treo.py --phut 30
    .venv\\Scripts\\python.exe liet_ke_don_treo.py --db fselling_v3.db
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def mo_readonly(duong_dan: str) -> sqlite3.Connection:
    """Mở DB ở chế độ chỉ đọc - không thể ghi nhầm kể cả khi code có lỗi."""
    if not os.path.exists(duong_dan):
        print(f"Khong tim thay database: {duong_dan}")
        sys.exit(1)
    return sqlite3.connect(f"file:{duong_dan}?mode=ro", uri=True)


def cot_cua_bang(con: sqlite3.Connection, bang: str) -> set:
    """Tap ten cot cua mot bang. Rong neu bang khong ton tai."""
    return {r[1] for r in con.execute(f"PRAGMA table_info({bang})")}


def co_cot_product_id(con: sqlite3.Connection) -> bool:
    return "product_id" in cot_cua_bang(con, "order_items")


def main() -> None:
    parser = argparse.ArgumentParser(description="Liet ke don PENDING dang treo (chi doc).")
    parser.add_argument(
        "--phut",
        type=int,
        default=0,
        help="Chi tinh don cu hon N phut. 0 = liet ke tat ca don PENDING.",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("DB_PATH") or os.path.join(BASE_DIR, "fselling_v4.db"),
        help="Duong dan file database.",
    )
    args = parser.parse_args()

    con = mo_readonly(args.db)

    # Cac file DB cu (v1-v3) co schema khac: chua co voucher_code tren orders,
    # chua co stock tren products. Doc PRAGMA de tu thich nghi thay vi gia dinh.
    cot_orders = cot_cua_bang(con, "orders")
    if not cot_orders:
        print("Database nay khong co bang 'orders'.")
        sys.exit(1)
    co_voucher = "voucher_code" in cot_orders
    co_stock = "stock" in cot_cua_bang(con, "products")

    dieu_kien = "o.status = 'PENDING'"
    tham_so: tuple = ()
    if args.phut > 0:
        han_chot = (datetime.utcnow() - timedelta(minutes=args.phut)).strftime("%Y-%m-%d %H:%M:%S")
        dieu_kien += " AND o.created_at < ?"
        tham_so = (han_chot,)
        print(f"Loc: don tao truoc {han_chot} UTC (cu hon {args.phut} phut)\n")
    else:
        print("Loc: tat ca don PENDING\n")

    print(f"Database: {args.db}")
    print("-" * 78)

    chon_voucher = "o.voucher_code" if co_voucher else "NULL"
    don = con.execute(
        f"""SELECT o.id, s.name, o.shop_id, o.total_amount, o.created_at, {chon_voucher},
                   (SELECT SUM(oi.quantity) FROM order_items oi WHERE oi.order_id = o.id)
            FROM orders o LEFT JOIN shops s ON s.id = o.shop_id
            WHERE {dieu_kien} ORDER BY o.created_at""",
        tham_so,
    ).fetchall()

    if not don:
        print("Khong co don PENDING nao.")
        return

    print(f"{'Don':<7}{'Cua hang':<26}{'So tien':>13}  {'Tao luc':<17}{'SL':>4}")
    print("-" * 78)
    mo_coi = []
    for oid, shop, shop_id, tien, tao_luc, voucher, sl in don:
        ten_shop = shop if shop else f"[shop #{shop_id} DA XOA]"
        if not shop:
            mo_coi.append(oid)
        ghi_chu = f"  voucher={voucher}" if voucher else ""
        print(
            f"#{oid:<6}{ten_shop[:24]:<26}{tien:>12,.0f}d  "
            f"{str(tao_luc)[:16]:<17}{sl or 0:>4}{ghi_chu}"
        )

    tong_tien = sum(d[3] or 0 for d in don)
    tong_sl = sum(d[6] or 0 for d in don)
    print("-" * 78)
    print(f"Tong: {len(don)} don | {tong_sl} san pham dang bi giu | {tong_tien:,.0f}d")

    # Hang dang bi giu, gom theo san pham
    if co_cot_product_id(con):
        noi_bang = "LEFT JOIN products p ON p.id = oi.product_id"
        cach_khop = "theo product_id"
    else:
        noi_bang = "LEFT JOIN products p ON p.shop_id = o.shop_id AND p.name = oi.product_name"
        cach_khop = "theo TEN (DB chua chay migration product_id)"

    chon_ton = "MAX(p.stock)" if co_stock else "NULL"
    cau_truy_van = f"""
        SELECT oi.product_name, SUM(oi.quantity), {chon_ton}
        FROM order_items oi JOIN orders o ON o.id = oi.order_id
        {noi_bang}
        WHERE {dieu_kien} GROUP BY oi.product_name ORDER BY 2 DESC"""

    print(f"\nHang dang bi giu ({cach_khop}):")
    print("-" * 78)
    for ten, sl, ton in con.execute(cau_truy_van, tham_so):
        if not co_stock:
            hien_tai = "DB cu khong theo doi ton kho"
        elif ton is None:
            hien_tai = "SP da xoa - se KHONG hoan duoc"
        else:
            hien_tai = ton
        print(f"  {str(ten)[:34]:<36} giu {sl:>4}   ton hien tai: {hien_tai}")

    if mo_coi:
        print(f"\nCanh bao: {len(mo_coi)} don mo coi (cua hang da bi xoa): "
              f"{', '.join('#' + str(i) for i in mo_coi)}")
        print("  Cac don nay van huy duoc, nhung san pham cua shop da xoa thi khong hoan kho duoc.")

    print("\n(Script nay chi doc, khong thay doi gi. De thuc su huy: bat")
    print(" ORDER_PENDING_TIMEOUT_MINUTES trong .env roi khoi dong lai app.)")


if __name__ == "__main__":
    main()
