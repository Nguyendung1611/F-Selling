"""API phiếu nhập nhà cung cấp."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.supplier import (
    PurchaseReceiptConfirm,
    PurchaseReceiptCreate,
    PurchaseReceiptUpdate,
)
from ..services import supplier_service

router = APIRouter(prefix="/api/purchase-receipts", tags=["purchase-receipts"])


@router.get("/receipt/{receipt_id}")
def get_receipt_detail(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.get_receipt_detail(db, current_user, receipt_id)


@router.put("/receipt/{receipt_id}")
def update_receipt_draft(
    receipt_id: int,
    payload: PurchaseReceiptUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.update_receipt_draft(
        db, current_user, receipt_id, payload
    )


@router.delete("/receipt/{receipt_id}")
def delete_receipt_draft(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.delete_receipt_draft(db, current_user, receipt_id)


@router.post("/receipt/{receipt_id}/confirm")
def confirm_receipt(
    receipt_id: int,
    payload: PurchaseReceiptConfirm,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.confirm_receipt(db, current_user, receipt_id, payload)


@router.post("/{shop_id}")
def create_receipt_draft(
    shop_id: int,
    payload: PurchaseReceiptCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.create_receipt_draft(
        db, current_user, shop_id, payload
    )


@router.get("/{shop_id}")
def list_receipts(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.list_receipts(db, current_user, shop_id)
