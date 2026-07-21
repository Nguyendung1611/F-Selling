"""Tác vụ nền: dọn tài khoản đăng ký nhưng không xác minh trong thời hạn."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from .. import models
from ..core.config import ORDER_PENDING_TIMEOUT_MINUTES
from ..core.database import SessionLocal
from . import order_service


def cleanup_expired_unverified_users() -> int:
    """Xóa user chưa xác minh đã quá hạn OTP. Trả về số bản ghi đã xóa."""
    db = SessionLocal()
    try:
        current_time = datetime.utcnow()
        expired_users = (
            db.query(models.User)
            .filter(
                models.User.is_verified == False,  # noqa: E712
                models.User.verification_code_expires < current_time,
            )
            .all()
        )

        for user in expired_users:
            print(f"[CLEANUP] Deleting unverified user: {user.username}")
            db.delete(user)

        if expired_users:
            db.commit()
            print(f"[CLEANUP] Removed {len(expired_users)} expired unverified user(s)")
        return len(expired_users)
    except SQLAlchemyError as e:
        print(f"[CLEANUP] Error cleaning up expired users: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def cancel_expired_pending_orders(timeout_minutes: int = None) -> int:
    """Tự hủy các đơn PENDING quá hạn thanh toán và hoàn lại tồn kho.

    Khách quét QR rồi bỏ đi sẽ để đơn treo mãi ở PENDING, mà tồn kho đã bị trừ
    ngay lúc tạo đơn -> hàng bị giữ vĩnh viễn. Job này giải phóng số hàng đó.

    MẶC ĐỊNH TẮT (ORDER_PENDING_TIMEOUT_MINUTES = 0). Đây là thao tác ghi lên
    dữ liệu thật nên phải được bật một cách có chủ ý.

    Trả về số đơn đã hủy.
    """
    minutes = ORDER_PENDING_TIMEOUT_MINUTES if timeout_minutes is None else timeout_minutes
    if minutes <= 0:
        return 0

    db = SessionLocal()
    try:
        han_chot = datetime.utcnow() - timedelta(minutes=minutes)
        expired_orders = (
            db.query(models.Order)
            .filter(
                models.Order.status == order_service.STATUS_PENDING,
                models.Order.created_at < han_chot,
            )
            .all()
        )

        da_huy = 0
        for order in expired_orders:
            # Mỗi đơn là một transaction riêng: một đơn lỗi không kéo đổ cả lượt chạy.
            try:
                if order_service.cancel_expired_order(db, order):
                    da_huy += 1
            except SQLAlchemyError as e:
                db.rollback()
                print(f"[AUTO-CANCEL] Loi khi huy don #{order.id}: {e}")

        if da_huy:
            print(f"[AUTO-CANCEL] Da huy {da_huy} don qua han (>{minutes} phut) va hoan ton kho")
        return da_huy
    except SQLAlchemyError as e:
        print(f"[AUTO-CANCEL] Loi khi quet don qua han: {e}")
        db.rollback()
        return 0
    finally:
        db.close()
