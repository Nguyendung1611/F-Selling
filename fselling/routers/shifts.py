"""HTTP API cho ca thu ngân.

Hai route tĩnh current/history phải được khai trước ``/{shift_id}`` để FastAPI
không thử parse chúng thành số ca.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db, require_shop_access
from ..schemas.shift import CashMovementCreate, ShiftClose, ShiftOpen
from ..services import shift_service, subscription_service

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


@router.get("/current/{shop_id}")
def get_current_shift(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shift_service.get_current_shift(db, current_user, shop_id)


@router.get("/history/{shop_id}")
def list_shift_history(
    shop_id: int,
    page: int = Query(default=1),
    per_page: int = Query(default=shift_service.DEFAULT_PAGE_SIZE),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shift_service.list_shift_history(
        db, current_user, shop_id, page=page, per_page=per_page
    )


@router.post("/{shop_id}/open")
def open_shift(
    shop_id: int,
    request: ShiftOpen,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == "STAFF":
        require_shop_access(db, shop_id, current_user)
        subscription_service.require_pro(db, shop_id)
    return shift_service.open_shift(db, current_user, shop_id, request)


@router.get("/{shift_id}")
def get_shift_detail(
    shift_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shift_service.get_shift_detail(db, current_user, shift_id)


@router.post("/{shift_id}/movements")
def create_movement(
    shift_id: int,
    request: CashMovementCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == "STAFF":
        shift = (
            db.query(models.CashShift)
            .filter(models.CashShift.id == shift_id)
            .first()
        )
        if shift is not None:
            require_shop_access(db, shift.shop_id, current_user)
            subscription_service.require_pro(db, shift.shop_id)
    return shift_service.create_movement(db, current_user, shift_id, request)


@router.post("/{shift_id}/close")
def close_shift(
    shift_id: int,
    request: ShiftClose,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shift_service.close_shift(db, current_user, shift_id, request)
