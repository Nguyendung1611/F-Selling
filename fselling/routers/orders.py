from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.order import OrderCreate
from ..services import order_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("/{shop_id}")
def create_order(
    shop_id: int,
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.create_order(db, current_user, shop_id, order)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.get_order(db, current_user, order_id)


@router.get("/{order_id}/detail")
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.get_order_detail(db, current_user, order_id)


@router.post("/{order_id}/pay")
def pay_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.pay_order(db, current_user, order_id)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.cancel_order(db, current_user, order_id)
