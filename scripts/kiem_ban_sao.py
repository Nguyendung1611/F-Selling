r"""Kiểm tra một file sao lưu tải về từ R2 có thật sự dùng được không.

Chạy từ thư mục ``python_app``:

    .\.venv\Scripts\python.exe scripts\kiem_ban_sao.py

Không đưa tên file thì script tự tìm file .db.gz MỚI NHẤT trong thư mục
Downloads. Muốn chỉ đích danh:

    .\.venv\Scripts\python.exe scripts\kiem_ban_sao.py duong\dan\toi\file.db.gz

Vì sao cần: `PRAGMA integrity_check` chỉ trả lời "file có hỏng không". Nó KHÔNG
trả lời "đây có phải dữ liệu của tôi không" — một database rỗng hoàn toàn lành
lặn vẫn qua được bài kiểm đó. Nên script này in luôn số cửa hàng, số đơn, số
khách để bạn nhìn bằng mắt mà nhận ra dữ liệu của mình.

Script chỉ ĐỌC. Nó giải nén ra thư mục tạm rồi tự xóa, không đụng gì tới
database đang chạy.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# Bảng nào có thì đếm bảng đó. Thiếu bảng không phải lỗi — bản sao cũ có thể
# được tạo trước khi bảng đó ra đời.
BANG_CAN_DEM = [
    ("shops", "Cua hang"),
    ("users", "Tai khoan"),
    ("products", "San pham"),
    ("customers", "Khach hang"),
    ("orders", "Don hang"),
    ("order_returns", "Phieu tra hang"),
    ("cash_shifts", "Ca thu ngan"),
]


def _tim_file_moi_nhat() -> Path | None:
    tai_ve = Path.home() / "Downloads"
    if not tai_ve.is_dir():
        return None
    ung_vien = sorted(
        tai_ve.glob("*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return ung_vien[0] if ung_vien else None


def _dem(conn: sqlite3.Connection, bang: str) -> int | None:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {bang}").fetchone()[0]
    except sqlite3.Error:
        return None


def main() -> int:
    if len(sys.argv) > 1:
        goi = Path(sys.argv[1]).expanduser()
    else:
        goi = _tim_file_moi_nhat()
        if goi is None:
            print("Khong tim thay file .db.gz nao trong thu muc Downloads.")
            print("Dua duong dan truc tiep:")
            print(r"   .\.venv\Scripts\python.exe scripts\kiem_ban_sao.py duong\dan\file.db.gz")
            return 2
        print(f"(Tu chon file moi nhat trong Downloads)")

    if not goi.is_file():
        print(f"Khong thay file: {goi}")
        return 2

    print(f"File     : {goi}")
    print(f"Kich thuoc: {goi.stat().st_size:,} byte (da nen)")
    print()

    thu_muc = tempfile.mkdtemp(prefix="fselling_kiem_")
    try:
        db = os.path.join(thu_muc, "kiem_thu.db")
        try:
            with gzip.open(goi, "rb") as vao, open(db, "wb") as ra:
                shutil.copyfileobj(vao, ra)
        except (OSError, EOFError) as e:
            print(f"KHONG GIAI NEN DUOC: {e}")
            print("File co the tai ve chua xong, hoac khong phai file .gz.")
            return 1

        print(f"Sau giai nen: {os.path.getsize(db):,} byte")

        try:
            conn = sqlite3.connect(db)
        except sqlite3.Error as e:
            print(f"KHONG MO DUOC: {e}")
            return 1

        try:
            ket_qua = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if ket_qua != "ok":
                print(f"\nFILE HONG: {ket_qua}")
                return 1

            print("Tinh trang  : ok (file lanh lan)")
            print()
            print("Du lieu ben trong:")
            co_du_lieu = False
            for bang, nhan in BANG_CAN_DEM:
                so = _dem(conn, bang)
                if so is None:
                    print(f"   {nhan:<16}: (khong co bang nay)")
                else:
                    print(f"   {nhan:<16}: {so:,}")
                    if so > 0:
                        co_du_lieu = True
        finally:
            conn.close()
    finally:
        shutil.rmtree(thu_muc, ignore_errors=True)

    print()
    if co_du_lieu:
        print("=> BAN SAO DUNG DUOC. Day la du lieu that, phuc hoi duoc.")
        return 0

    print("=> FILE LANH NHUNG RONG. Khong co dong du lieu nao.")
    print("   Kiem lai DB_PATH luc sao luu co tro dung database that khong.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
