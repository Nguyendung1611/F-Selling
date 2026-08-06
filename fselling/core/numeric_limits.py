"""Giới hạn số nguyên an toàn dùng chung giữa sổ tiền và tồn kho.

9 triệu tỷ vẫn nhỏ hơn ``Number.MAX_SAFE_INTEGER`` của JavaScript. Giữ mọi
giá trị tiền mà giao diện phải cộng/trừ dưới ngưỡng này để không âm thầm làm
tròn số; giới hạn tồn kho riêng ngăn các phép nhân số lượng x đơn giá phình
quá lớn trước khi được kiểm tra.
"""

MAX_SAFE_VND = 9_000_000_000_000_000
MAX_SAFE_QUANTITY = 1_000_000_000


__all__ = ["MAX_SAFE_QUANTITY", "MAX_SAFE_VND"]
