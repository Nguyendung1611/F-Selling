"""Hỏi đáp báo cáo (L3). Router mỏng: chỉ nhận câu hỏi và gọi service."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import assistant_service

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class CauHoi(BaseModel):
    cau_hoi: str = Field(min_length=1, max_length=assistant_service.CAU_HOI_TOI_DA)


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
    return assistant_service.hoi_dap(db, current_user, shop_id, payload.cau_hoi)
