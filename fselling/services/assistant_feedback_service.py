"""Privacy-safe ratings for assistant replies.

Only fixed metadata is signed and persisted. Questions, answers and free-text
comments never cross this boundary.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.config import ALGORITHM, SECRET_KEY
from ..core.i18n import tr
from ..dependencies import require_shop_access

ACTION = "ASSISTANT_FEEDBACK"
TOKEN_TYPE = "assistant_feedback"
TOKEN_TTL_HOURS = 24
RATING_HELPFUL = "HELPFUL"
RATING_NOT_HELPFUL = "NOT_HELPFUL"
REASONS = (
    "NOT_UNDERSTOOD",
    "WRONG_REPORT",
    "WRONG_TIME_RANGE",
    "WRONG_NUMBERS",
    "OTHER",
)
MINIMUM_SAMPLES = 30
TARGET_HELPFUL_PERCENT = 95
_SAFE_INTENT = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")


def issue_token(
    current_user: models.User,
    shop_id: int,
    *,
    intent: Optional[str],
    understood: bool,
    used_ai: bool,
) -> str:
    """Issue a short-lived receipt containing fixed metadata only."""
    safe_intent = intent if intent and _SAFE_INTENT.fullmatch(intent) else "UNKNOWN"
    claims = {
        "typ": TOKEN_TYPE,
        "feedback_id": secrets.token_hex(16),
        "user_id": current_user.id,
        "shop_id": shop_id,
        "intent": safe_intent,
        "understood": bool(understood),
        "used_ai": bool(used_ai),
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str, current_user: models.User, shop_id: int) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail=tr("Phiếu đánh giá không hợp lệ hoặc đã hết hạn")) from exc

    feedback_id = claims.get("feedback_id")
    intent = claims.get("intent")
    if (
        claims.get("typ") != TOKEN_TYPE
        or claims.get("user_id") != current_user.id
        or claims.get("shop_id") != shop_id
        or not isinstance(feedback_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", feedback_id)
        or not isinstance(intent, str)
        or not _SAFE_INTENT.fullmatch(intent)
        or not isinstance(claims.get("understood"), bool)
        or not isinstance(claims.get("used_ai"), bool)
    ):
        raise HTTPException(status_code=400, detail=tr("Phiếu đánh giá không hợp lệ hoặc đã hết hạn"))
    return claims


def record_feedback(
    db: Session,
    current_user: models.User,
    shop_id: int,
    *,
    feedback_token: str,
    rating: str,
    reason: Optional[str],
) -> Dict[str, bool]:
    require_shop_access(db, shop_id, current_user)
    claims = _decode_token(feedback_token, current_user, shop_id)

    if rating == RATING_HELPFUL and reason is not None:
        raise HTTPException(status_code=400, detail=tr("Đánh giá hữu ích không cần lý do sai"))
    if rating == RATING_NOT_HELPFUL and reason is None:
        raise HTTPException(status_code=400, detail=tr("Hãy chọn một lý do cố định"))

    feedback_id = claims["feedback_id"]
    exists = db.query(models.SystemLog.id).filter(
        models.SystemLog.shop_id == shop_id,
        models.SystemLog.action == ACTION,
        models.SystemLog.details.like(f"feedback_id={feedback_id};%"),
    ).first()
    if exists:
        return {"recorded": False}

    details = (
        f"feedback_id={feedback_id};"
        f"intent={claims['intent']};"
        f"understood={int(claims['understood'])};"
        f"used_ai={int(claims['used_ai'])};"
        f"rating={rating};"
        f"reason={reason or 'NONE'}"
    )
    db.add(models.SystemLog(
        user_id=current_user.id,
        shop_id=shop_id,
        action=ACTION,
        details=details,
    ))
    db.commit()
    return {"recorded": True}


def _parse_details(details: str) -> Dict[str, str]:
    pairs = (part.split("=", 1) for part in (details or "").split(";") if "=" in part)
    return {key: value for key, value in pairs}


def get_summary(db: Session, current_user: models.User, shop_id: int) -> Dict[str, Any]:
    shop = require_shop_access(db, shop_id, current_user)
    if current_user.role != "ADMIN" and shop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail=tr("Chỉ chủ cửa hàng mới xem được chất lượng trợ lý"))

    rows = db.query(models.SystemLog.details).filter(
        models.SystemLog.shop_id == shop_id,
        models.SystemLog.action == ACTION,
    ).all()
    helpful = 0
    not_helpful = 0
    reasons = {reason: 0 for reason in REASONS}
    for (details,) in rows:
        metadata = _parse_details(details)
        if metadata.get("rating") == RATING_HELPFUL:
            helpful += 1
        elif metadata.get("rating") == RATING_NOT_HELPFUL:
            not_helpful += 1
            reason = metadata.get("reason")
            if reason in reasons:
                reasons[reason] += 1

    total = helpful + not_helpful
    helpful_percent = round(helpful * 100 / total, 1) if total else 0.0
    return {
        "total": total,
        "helpful": helpful,
        "not_helpful": not_helpful,
        "helpful_percent": helpful_percent,
        "reasons": reasons,
        "gate": {
            "minimum_samples": MINIMUM_SAMPLES,
            "target_helpful_percent": TARGET_HELPFUL_PERCENT,
            "ready_for_review": total >= MINIMUM_SAMPLES
            and helpful_percent >= TARGET_HELPFUL_PERCENT,
        },
    }
