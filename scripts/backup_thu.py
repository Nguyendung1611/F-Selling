r"""Chạy MỘT lần sao lưu thật lên R2, để xác nhận cấu hình đúng.

Chạy từ thư mục ``python_app``:

    .\.venv\Scripts\python.exe scripts\backup_thu.py

Vì sao cần script này: bộ test dùng `urlopen` giả, nên nó chứng minh được rằng
ta chụp đúng, nén đúng và ký đúng khuôn — nhưng KHÔNG chứng minh được R2 chấp
nhận chữ ký đó. Chỉ một lần chạy thật mới trả lời được câu ấy. Chạy script này
ngay sau khi cắm khóa, đừng đợi tới lúc cần phục hồi mới biết là hỏng.

Script chỉ ĐỌC database, không ghi gì.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fselling.services import backup_service  # noqa: E402


def main() -> int:
    if not backup_service.dang_bat():
        print("CHUA CAU HINH. Can dat day du 4 bien moi truong:")
        print("   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET")
        return 2

    print(f"Database nguon : {backup_service.DB_PATH}")
    print(f"Bucket         : {backup_service.R2_BUCKET}")
    print("Dang chup va tai len...")

    try:
        kq = backup_service.chay_sao_luu()
    except Exception as e:  # noqa: BLE001 - script tay, in ra cho người đọc
        print(f"\nTHAT BAI: {e}")
        print("\nBa nguyen nhan hay gap nhat:")
        print("  1. Sai khoa (Access Key ID / Secret Access Key)")
        print("  2. Sai ten bucket, hoac bucket nam o tai khoan khac")
        print("  3. Dong ho may lech qua 15 phut so voi gio thuc")
        return 1

    print("\nTHANH CONG")
    print(f"  Khoa      : {kq['khoa']}")
    print(f"  Goc       : {kq['byte_goc']:,} byte")
    print(f"  Sau nen   : {kq['byte_nen']:,} byte")
    print(f"  ETag      : {kq['etag']}")
    print(f"  Mat       : {kq['giay']} giay")
    print("\nVao Cloudflare Dashboard > R2 > bucket de nhin thay file vua len.")
    print("Tai ve va giai nen thu MOT lan, dung tin vao ETag mai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
