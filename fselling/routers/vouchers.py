from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import (
    PERMISSION_VOUCHER,
    get_current_user,
    get_db,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.catalog import VoucherCreate
from ..services import subscription_service, voucher_service

router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])


def _require_pro_for_voucher_change(
    db: Session, current_user: models.User, voucher_id: int
) -> None:
    voucher = (
        db.query(models.Voucher)
        .filter(models.Voucher.id == voucher_id)
        .first()
    )
    if voucher is None:
        return  # service phía sau giữ nguyên phản hồi 404 cũ
    require_shop_access(db, voucher.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_VOUCHER)
    subscription_service.require_pro(db, voucher.shop_id)


@router.post("")
def create_voucher(
    v: VoucherCreate,
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_VOUCHER)
    subscription_service.require_pro(db, shop_id)
    return voucher_service.create_voucher(db, current_user, shop_id, v)


@router.put("/{voucher_id}")
def update_voucher(
    voucher_id: int,
    v: VoucherCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_pro_for_voucher_change(db, current_user, voucher_id)
    return voucher_service.update_voucher(db, current_user, voucher_id, v)


@router.delete("/{voucher_id}")
def delete_voucher(
    voucher_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_pro_for_voucher_change(db, current_user, voucher_id)
    return voucher_service.delete_voucher(db, current_user, voucher_id)


@router.post("/apply/{shop_id}")
def apply_voucher(
    shop_id: int,
    subtotal: float = Form(...),
    voucher_code: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return voucher_service.apply_voucher(
        db, current_user, shop_id, subtotal, voucher_code
    )


@router.get("/{shop_id}")
def get_vouchers(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return voucher_service.list_vouchers(db, current_user, shop_id)
