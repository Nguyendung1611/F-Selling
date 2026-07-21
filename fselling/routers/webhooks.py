"""Webhook thanh toán.

Router này PHẢI được include TRƯỚC routers/orders.py vì đường dẫn
POST /api/orders/webhook trùng khuôn với POST /api/orders/{shop_id}.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.config import log_to_file
from ..core.security import compare_secret
from ..dependencies import get_db
from ..services import order_service
from ..services.payment_service import get_webhook_secret

router = APIRouter(tags=["webhooks"])


def _client_secret(x_webhook_secret: Optional[str], authorization: Optional[str]) -> Optional[str]:
    raw = x_webhook_secret or authorization
    if raw and raw.startswith("Bearer "):
        return raw.split(" ")[1]
    if raw and raw.startswith("Apikey "):
        return raw.split(" ")[1]
    return raw


@router.post("/api/orders/webhook")
async def order_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    try:
        request_data = await request.json()
    except (ValueError, UnicodeDecodeError):
        request_data = {}

    log_to_file(f"WEBHOOK RECEIVED: {request_data}")

    webhook_secret = get_webhook_secret()
    # Fail-closed: nếu chưa cấu hình secret thì từ chối, KHÔNG cho phép mark PAID.
    if not webhook_secret:
        raise HTTPException(
            status_code=503, detail="Webhook chưa được cấu hình (thiếu PAYMENT_WEBHOOK_SECRET)"
        )

    # So sánh chống timing attack
    if not compare_secret(_client_secret(x_webhook_secret, authorization), webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook secret không hợp lệ")

    result = order_service.apply_webhook_payment(db, request_data)
    paid = result["paid"]
    unreconciled = result["unreconciled"]

    msg = f"Cập nhật thành công đơn hàng: {paid}"
    if unreconciled:
        msg += f" | Cần đối soát thủ công (tiền về sau khi đơn đã hủy): {unreconciled}"

    # `order_ids` giữ nguyên ý nghĩa cũ (các đơn đã PAID) để không phá contract;
    # `unreconciled_order_ids` là khóa bổ sung, thêm khóa là thay đổi an toàn.
    return {
        "msg": msg,
        "order_ids": paid,
        "unreconciled_order_ids": unreconciled,
    }
