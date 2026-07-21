"""Tác vụ nền: dọn tài khoản đăng ký nhưng không xác minh trong thời hạn."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from .. import models
from ..core.database import SessionLocal


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
