from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.catalog import VoucherCreate
from ..services import voucher_service

router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])


@router.post("")
def create_voucher(
    v: VoucherCreate,
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return voucher_service.create_voucher(db, current_user, shop_id, v)


@router.put("/{voucher_id}")
def update_voucher(
    voucher_id: int,
    v: VoucherCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return voucher_service.update_voucher(db, current_user, voucher_id, v)


@router.delete("/{voucher_id}")
def delete_voucher(
    voucher_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return voucher_service.delete_voucher(db, current_user, voucher_id)


@router.post("/apply/{shop_id}")
def apply_voucher(
    shop_id: int,
    subtotal: float = Form(...),
    voucher_code: str = Form(...),
    db: Session = Depends(get_db),
):
    return voucher_service.apply_voucher(db, shop_id, subtotal, voucher_code)


@router.get("/{shop_id}")
def get_vouchers(shop_id: int, db: Session = Depends(get_db)):
    return voucher_service.list_vouchers(db, shop_id)
