"""Webhook thanh toán.

Router này PHẢI được include TRƯỚC routers/orders.py và routers/subscriptions.py
vì các đường ``.../webhook`` trùng khuôn route động ``.../{shop_id}``.
"""
import json
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.config import ORDER_WEBHOOK_MAX_BODY_BYTES, log_to_file
from ..core.security import compare_secret
from ..dependencies import get_db
from ..services import order_service
from ..services.payment_service import (
    get_subscription_webhook_secret,
    get_webhook_secret,
)

router = APIRouter(tags=["webhooks"])


def _body_too_large() -> HTTPException:
    return HTTPException(status_code=413, detail="Webhook body vượt quá giới hạn cho phép")


async def _read_limited_json(
    request: Request, max_bytes: int
) -> Tuple[Any, int]:
    """Đọc JSON với trần bộ nhớ, kể cả khi Content-Length thiếu hoặc nói sai.

    Content-Length chỉ giúp từ chối sớm; giới hạn thật luôn được kiểm trên từng
    chunk ASGI. Hàm chỉ được gọi SAU khi secret webhook đã được xác thực.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            raise _body_too_large()

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise _body_too_large()
        body.extend(chunk)

    if not body:
        return {}, 0
    try:
        return json.loads(body), len(body)
    except (ValueError, UnicodeDecodeError):
        return {}, len(body)


def _client_secret(x_webhook_secret: Optional[str], authorization: Optional[str]) -> Optional[str]:
    raw = x_webhook_secret or authorization
    if raw and raw.startswith("Bearer "):
        return raw.split(" ")[1]
    if raw and raw.startswith("Apikey "):
        return raw.split(" ")[1]
    return raw


def _apply_subscription_webhook_payment(db: Session, request_data: dict):
    """Import lười để router ORDER không phụ thuộc vòng đời module thuê bao."""
    from ..services import subscription_service

    return subscription_service.apply_webhook_payment(db, request_data)


@router.post("/api/orders/webhook")
async def order_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    webhook_secret = get_webhook_secret()
    # Fail-closed: nếu chưa cấu hình secret thì từ chối, KHÔNG cho phép mark PAID.
    if not webhook_secret:
        raise HTTPException(
            status_code=503, detail="Webhook chưa được cấu hình (thiếu PAYMENT_WEBHOOK_SECRET)"
        )

    # So sánh chống timing attack
    if not compare_secret(_client_secret(x_webhook_secret, authorization), webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook secret không hợp lệ")

    # Secret phải được kiểm xong trước khi đọc một byte body. Content-Length chỉ
    # là tối ưu từ chối sớm; `_read_limited_json` vẫn đếm stream để chặn header
    # thiếu/sai. Log chỉ có metadata số học, không có raw payload/header/client.
    request_data, body_size = await _read_limited_json(
        request, ORDER_WEBHOOK_MAX_BODY_BYTES
    )
    log_to_file(f"ORDER WEBHOOK AUTHENTICATED body_bytes={body_size}")

    try:
        result = order_service.apply_webhook_payment(db, request_data)
    except HTTPException as exc:
        # Chỉ 400/404 top-level của parser/order lookup được giữ. HTTPException
        # nảy ra sau khi một event tài chính đã bắt đầu phải thành 5xx.
        if exc.status_code in (400, 404):
            raise
        db.rollback()
        log_to_file(
            "ORDER WEBHOOK FAILURE category=persistence error_type=webhook_event"
        )
        raise HTTPException(
            status_code=500,
            detail="Không thể lưu bền vững giao dịch webhook",
        ) from exc
    except Exception as exc:
        # Persistence/audit/unknown error phải hiện thành 5xx để provider retry.
        # Chỉ log category cố định; không ghi exception message/raw client data.
        db.rollback()
        log_to_file(
            "ORDER WEBHOOK FAILURE category=persistence error_type=webhook_event"
        )
        raise HTTPException(
            status_code=500,
            detail="Không thể lưu bền vững giao dịch webhook",
        ) from exc
    paid = result["paid"]
    unreconciled = result["unreconciled"]
    rejected = result.get("rejected", [])

    msg = f"Cập nhật thành công đơn hàng: {paid}"
    if unreconciled:
        msg += f" | Cần đối soát thủ công: {unreconciled}"
    if rejected:
        # Từ F6 có thêm lý do thứ ba (đơn ở trạng thái webhook không tự xử lý,
        # thực tế là đơn ghi nợ), nên câu này không liệt kê lý do nữa - liệt kê
        # thiếu còn tệ hơn không liệt kê, vì nó chỉ sai đường tra cứu.
        # Lý do đầy đủ của TỪNG đơn nằm trong SystemLog `WEBHOOK_TU_CHOI`.
        msg += f" | Từ chối, xem SystemLog: {rejected}"

    # CỐ Ý trả 200 cho duplicate tương thích và business rejection CHỈ SAU KHI
    # ledger/audit bắt buộc đã durable. Collision xác định được đã có audit
    # WEBHOOK_XUNG_DOT_IDEMPOTENCY. Persistence/audit/commit/unknown failure đi
    # nhánh 5xx bên trên để provider retry.
    #
    # `order_ids` giữ nguyên ý nghĩa cũ (các đơn đã PAID) để không phá contract;
    # hai khóa còn lại là bổ sung, thêm khóa là thay đổi an toàn.
    return {
        "msg": msg,
        "order_ids": paid,
        "unreconciled_order_ids": unreconciled,
        "rejected_order_ids": rejected,
    }


@router.post("/api/subscriptions/webhook")
async def subscription_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Nhận thanh toán gói cước, tách hoàn toàn khỏi webhook đơn bán.

    Sai/thiếu secret vẫn trả lỗi để fail-closed. Sau khi đã xác thực đúng, một
    giao dịch bị từ chối về nghiệp vụ phải trả HTTP 200 để nhà cung cấp ngân
    hàng không retry vô hạn. Lỗi server/database thật vẫn nổi thành 5xx để họ
    gửi lại và ta không làm mất giao dịch.
    """
    webhook_secret = get_subscription_webhook_secret()
    if not webhook_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "Webhook gói cước chưa được cấu hình "
                "(thiếu SUBSCRIPTION_WEBHOOK_SECRET)"
            ),
        )

    if not compare_secret(
        _client_secret(x_webhook_secret, authorization), webhook_secret
    ):
        raise HTTPException(
            status_code=401, detail="Webhook gói cước có secret không hợp lệ"
        )

    try:
        request_data = await request.json()
    except (ValueError, UnicodeDecodeError):
        request_data = {}
    if not isinstance(request_data, dict):
        request_data = {}

    # Không ghi raw payload: nội dung chuyển khoản có thể chứa dữ liệu cá nhân.
    log_to_file("SUBSCRIPTION WEBHOOK RECEIVED")

    try:
        return _apply_subscription_webhook_payment(db, request_data)
    except HTTPException as exc:
        if 400 <= exc.status_code < 500:
            # Đây là từ chối nghiệp vụ của một request đã xác thực, không phải
            # lỗi giao tiếp. Trả 200 để ngân hàng dừng retry; service chịu trách
            # nhiệm ghi ledger UNAPPLIED/SystemLog trước khi ném lỗi (nếu có).
            return {
                "msg": "Giao dịch gói cước đã được tiếp nhận nhưng không được áp dụng",
                "status": "rejected",
                "detail": exc.detail,
            }
        raise
