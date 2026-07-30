"""Thanh toán: sinh link VietQR và phân tích payload webhook ngân hàng."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .. import models

ORDER_CODE_RE = re.compile(r"ORDER(\d+)", re.IGNORECASE)


@dataclass
class GiaoDich:
    """Một giao dịch rút ra từ payload webhook.

    `amount` là None khi payload KHÔNG hề chứa số tiền - khác hẳn với số tiền
    bằng 0. Phân biệt được hai ca này mới từ chối đúng chỗ: không đọc được số
    tiền thì không có cơ sở nào để xác nhận đã thu đủ.

    `direction` là 'in' (tiền vào), 'out' (tiền ra) hoặc None khi không rõ.
    Giao dịch tiền RA vẫn có thể mang nội dung 'ORDER42' - ví dụ chính shop
    hoàn tiền cho khách - nên phải loại ra, nếu không đơn vừa hoàn lại bị đánh
    dấu là đã thanh toán.
    """

    order_id: int
    amount: Optional[float] = None
    direction: Optional[str] = None
    txn_id: Optional[str] = None
    account_no: Optional[str] = None
    provider: Optional[str] = None
    payload_fingerprint: Optional[str] = None


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


def _so_tien(*ung_vien: Any) -> Optional[float]:
    """Lấy số tiền đầu tiên đọc được. None khi không trường nào có giá trị.

    Chuỗi rỗng và None đều coi như không có. Số 0 thì GIỮ - đó là một số tiền
    thật (và là số tiền sai), không phải "thiếu dữ liệu".
    """
    for v in ung_vien:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _chieu_tien(item: Dict[str, Any], amount: Optional[float]) -> Optional[str]:
    """Xác định tiền vào hay tiền ra.

    SePay nói thẳng bằng `transferType`. Casso không có trường đó nhưng dùng
    dấu của `amount`: âm là tiền ra. payOS chỉ gửi giao dịch tiền vào.
    """
    raw = item.get("transferType") or item.get("type") or item.get("direction")
    if isinstance(raw, str):
        r = raw.strip().lower()
        if r in ("in", "credit", "receive", "money_in"):
            return "in"
        if r in ("out", "debit", "send", "money_out"):
            return "out"
    if amount is not None and amount < 0:
        return "out"
    return None


def _txn_id(item: Dict[str, Any]) -> Optional[str]:
    for k in ("id", "tid", "referenceCode", "reference", "transactionId", "transaction_id"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _tai_khoan(item: Dict[str, Any]) -> Optional[str]:
    for k in ("accountNumber", "account_number", "subAccId", "bankSubAccId", "accountNo"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _giao_dich_tu_item(
    item: Dict[str, Any], mo_ta: str, provider: str
) -> List[GiaoDich]:
    """Dựng GiaoDich cho một mục giao dịch, kèm mọi mã đơn tìm được trong mô tả."""
    amount = _so_tien(
        item.get("transferAmount"), item.get("amount"), item.get("value"), item.get("money")
    )
    chung = {
        "amount": abs(amount) if amount is not None else None,
        "direction": _chieu_tien(item, amount),
        "txn_id": _txn_id(item),
        "account_no": _tai_khoan(item),
        "provider": provider,
        # Retry không có mã giao dịch vẫn phải nhận ra được. Hash toàn bộ mục
        # giao dịch (không dùng vị trí trong mảng vì provider có thể đổi thứ tự).
        "payload_fingerprint": hashlib.sha256(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
    }
    return [GiaoDich(order_id=oid, **chung) for oid in _match_order_code(mo_ta)]


def extract_transactions(request_data: Dict[str, Any]) -> List[GiaoDich]:
    """Rút danh sách giao dịch kèm số tiền từ payload webhook.

    Hỗ trợ cùng các định dạng mà `extract_order_ids` hỗ trợ, nhưng giữ lại số
    tiền, chiều tiền và mã giao dịch để tầng trên còn đối chiếu.
    """
    if not isinstance(request_data, dict):
        return []

    data = request_data.get("data")

    if isinstance(data, list):
        ket_qua: List[GiaoDich] = []
        for item in data:
            if isinstance(item, dict):
                ket_qua.extend(
                    _giao_dich_tu_item(item, item.get("description", ""), "casso")
                )
        return ket_qua

    if isinstance(data, dict) and "orderCode" in data:
        gd = _giao_dich_tu_item(data, data.get("description", ""), "payos")
        try:
            oid = int(data["orderCode"])
        except (ValueError, TypeError):
            return gd
        # orderCode là nguồn đáng tin nhất của payOS; mô tả chỉ để bổ sung.
        if not any(g.order_id == oid for g in gd):
            mau = _giao_dich_tu_item(data, f"ORDER{oid}", "payos")
            gd = mau + gd
        return gd

    if "content" in request_data or "transferAmount" in request_data:
        mo_ta = request_data.get("content", "") or request_data.get("description", "")
        return _giao_dich_tu_item(request_data, mo_ta, "sepay")

    if "order_id" in request_data:
        try:
            oid = int(request_data["order_id"])
        except (ValueError, TypeError):
            return []
        return _giao_dich_tu_item(request_data, f"ORDER{oid}", "generic")

    # Fallback: quét toàn bộ payload tìm ORDERxxx. Không có số tiền nào đáng
    # tin ở đây nên để None - tầng trên sẽ từ chối.
    return [
        GiaoDich(order_id=oid, provider="fallback")
        for oid in _match_order_code(str(request_data))
    ]


def get_webhook_secret() -> str:
    """Secret webhook lấy từ biến môi trường. Đọc tại thời điểm gọi để
    test có thể monkeypatch, và để fail-closed khi chưa cấu hình."""
    import os

    return os.getenv("PAYMENT_WEBHOOK_SECRET", "")
