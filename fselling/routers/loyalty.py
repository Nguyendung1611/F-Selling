"""HTTP routes cho cấu hình chương trình khách thân thiết."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import get_current_user, get_db
from ..models.user import User
from ..schemas.loyalty import LoyaltyProgramUpdate
from ..services import loyalty_service

router = APIRouter(prefix="/api/loyalty", tags=["loyalty"])


@router.get("/{shop_id}")
def get_loyalty_program(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return loyalty_service.get_program(db, current_user, shop_id)


@router.put("/{shop_id}")
def update_loyalty_program(
    shop_id: int,
    data: LoyaltyProgramUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return loyalty_service.update_program(db, current_user, shop_id, data)


__all__ = ["router"]
