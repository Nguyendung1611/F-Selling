from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.order import (
    CashPayment,
    CashTopup,
    OrderCreate,
    OrderReturnCreate,
    RefundComplete,
)
from ..services import order_service, return_service

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
    chi_tiet = order_service.get_order_detail(db, current_user, order_id)
    return return_service.bo_sung_thong_tin_tra_hang(db, chi_tiet)


@router.post("/{order_id}/returns")
def create_order_return(
    order_id: int,
    payload: OrderReturnCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return return_service.create_return(db, current_user, order_id, payload)


@router.post("/{order_id}/pay")
def pay_order(
    order_id: int,
    request: CashPayment | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.pay_order(db, current_user, order_id, request)


@router.post("/{order_id}/cash-topup")
def cash_topup(
    order_id: int,
    request: CashTopup,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.cash_topup(db, current_user, order_id, request)


@router.post("/{order_id}/refund-complete")
def refund_complete(
    order_id: int,
    request: RefundComplete,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.complete_refund(db, current_user, order_id, request)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.cancel_order(db, current_user, order_id)
