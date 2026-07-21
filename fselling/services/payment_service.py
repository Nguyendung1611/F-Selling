"""Thanh toán: sinh link VietQR và phân tích payload webhook ngân hàng."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .. import models

ORDER_CODE_RE = re.compile(r"ORDER(\d+)", re.IGNORECASE)


def build_qr_url(shop: models.Shop, total: float, order_id: int) -> str:
    """Link ảnh VietQR. Nội dung chuyển khoản chứa ORDER<id> để webhook đối soát."""
    return (
        f"https://img.vietqr.io/image/{shop.bank_code}-{shop.bank_account_no}-compact2.png"
        f"?amount={int(total)}&addInfo=ORDER{order_id}&accountName={shop.bank_account_name}"
    )


def _match_order_code(text: str) -> List[int]:
    """Chỉ lấy mã ORDER đầu tiên - giữ đúng hành vi của bản gốc (re.search),
    tránh việc một payload đánh dấu PAID cho nhiều đơn ngoài ý muốn."""
    match = ORDER_CODE_RE.search(text or "")
    return [int(match.group(1))] if match else []


def extract_order_ids(request_data: Dict[str, Any]) -> List[int]:
    """Rút mã đơn từ payload webhook. Hỗ trợ nhiều định dạng nhà cung cấp
    (danh sách giao dịch, orderCode, content/transferAmount, order_id)."""
    order_ids: List[int] = []
    data = request_data.get("data") if isinstance(request_data, dict) else None

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                order_ids.extend(_match_order_code(item.get("description", "")))

    elif isinstance(data, dict) and "orderCode" in data:
        try:
            order_ids.append(int(data["orderCode"]))
        except (ValueError, TypeError):
            pass
        order_ids.extend(_match_order_code(data.get("description", "")))

    elif "content" in request_data or "transferAmount" in request_data:
        desc = request_data.get("content", "") or request_data.get("description", "")
        order_ids.extend(_match_order_code(desc))

    elif "order_id" in request_data:
        try:
            order_ids.append(int(request_data["order_id"]))
        except (ValueError, TypeError):
            pass

    if not order_ids:
        # Fallback: quét toàn bộ payload tìm ORDERxxx
        order_ids.extend(_match_order_code(str(request_data)))

    return order_ids


def get_webhook_secret() -> str:
    """Secret webhook lấy từ biến môi trường. Đọc tại thời điểm gọi để
    test có thể monkeypatch, và để fail-closed khi chưa cấu hình."""
    import os

    return os.getenv("PAYMENT_WEBHOOK_SECRET", "")
