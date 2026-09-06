"""Giới hạn số nguyên an toàn dùng chung giữa sổ tiền và tồn kho.

Giới hạn trên áp cho từng giá trị tiền canonical được persist. Tổng báo cáo có
thể vượt ``Number.MAX_SAFE_INTEGER`` dù từng chứng từ không vượt giới hạn, nên
contract v2 trả aggregate đó dưới dạng decimal string.
"""

MAX_SAFE_VND = 9_000_000_000_000_000
MAX_SAFE_QUANTITY = 1_000_000_000


__all__ = ["MAX_SAFE_QUANTITY", "MAX_SAFE_VND"]
