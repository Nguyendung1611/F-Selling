"""Ghi nhật ký hành động vào bảng system_logs."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models


def log_system_action(
    db: Session, user_id: Optional[int], action: str, details: str = ""
) -> None:
    try:
        log_entry = models.SystemLog(user_id=user_id, action=action, details=details)
        db.add(log_entry)
        db.commit()
    except SQLAlchemyError as e:
        print(f"Error logging action: {e}")
        db.rollback()


def get_recent_logs(db: Session, limit: int = 100) -> List[dict]:
    logs = (
        db.query(models.SystemLog)
        .order_by(models.SystemLog.created_at.desc())
        .limit(limit)
        .all()
    )
    res = []
    for log in logs:
        username = log.user.username if log.user else "System"
        res.append(
            {
                "id": log.id,
                "username": username,
                "action": log.action,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
        )
    return res
