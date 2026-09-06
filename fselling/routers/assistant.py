"""Hỏi đáp báo cáo và phản hồi chất lượng có cấu trúc."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import assistant_feedback_service, assistant_service

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class CauHoi(BaseModel):
    cau_hoi: str = Field(min_length=1, max_length=assistant_service.CAU_HOI_TOI_DA)


class DanhGia(BaseModel):
    feedback_token: str = Field(min_length=20, max_length=1000)
    rating: Literal["HELPFUL", "NOT_HELPFUL"]
    reason: Optional[
        Literal[
            "NOT_UNDERSTOOD",
            "WRONG_REPORT",
            "WRONG_TIME_RANGE",
            "WRONG_NUMBERS",
            "OTHER",
        ]
    ] = None


@router.post("/{shop_id}")
def hoi_dap(
    shop_id: int,
    payload: CauHoi,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Trả lời câu hỏi tiếng Việt bằng đúng các báo cáo đã có.

    POST chứ không GET: câu hỏi là nội dung người dùng gõ, và query string thì
    nằm lại trong lịch sử trình duyệt lẫn log máy chủ.

    CHỈ ĐỌC. Quyền do từng báo cáo bên dưới tự kiểm, không kiểm lại ở đây.
    """
    result = assistant_service.hoi_dap(db, current_user, shop_id, payload.cau_hoi)
    result["feedback_token"] = assistant_feedback_service.issue_token(
        current_user,
        shop_id,
        intent=result.get("y_dinh"),
        understood=bool(result.get("hieu_duoc")),
        used_ai=bool(result.get("dung_ai")),
    )
    return result


@router.post("/{shop_id}/feedback")
def danh_gia(
    shop_id: int,
    payload: DanhGia,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return assistant_feedback_service.record_feedback(
        db,
        current_user,
        shop_id,
        feedback_token=payload.feedback_token,
        rating=payload.rating,
        reason=payload.reason,
    )


@router.get("/{shop_id}/feedback/summary")
def tong_hop_danh_gia(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return assistant_feedback_service.get_summary(db, current_user, shop_id)
