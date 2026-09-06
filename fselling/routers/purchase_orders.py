"""API đơn đặt hàng nhà cung cấp."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.supplier import (
    PurchaseOrderCancel,
    PurchaseOrderCreate,
    PurchaseOrderPlace,
    PurchaseOrderUpdate,
)
from ..services import supplier_service

router = APIRouter(prefix="/api/purchase-orders", tags=["purchase-orders"])


@router.get("/order/{order_id}")
def get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.get_purchase_order_detail(db, current_user, order_id)


@router.put("/order/{order_id}")
def update_purchase_order(
    order_id: int,
    payload: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.update_purchase_order_draft(
        db, current_user, order_id, payload
    )


@router.delete("/order/{order_id}")
def delete_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.delete_purchase_order_draft(db, current_user, order_id)


@router.post("/order/{order_id}/place")
def place_purchase_order(
    order_id: int,
    payload: PurchaseOrderPlace,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.place_purchase_order(db, current_user, order_id, payload)


@router.post("/order/{order_id}/cancel")
def cancel_purchase_order(
    order_id: int,
    payload: PurchaseOrderCancel,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.cancel_purchase_order(db, current_user, order_id, payload)


@router.post("/{shop_id}")
def create_purchase_order(
    shop_id: int,
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.create_purchase_order(db, current_user, shop_id, payload)


@router.get("/{shop_id}")
def list_purchase_orders(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.list_purchase_orders(db, current_user, shop_id)
