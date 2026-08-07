"""Router khách hàng (CRM). Chủ shop và nhân viên của shop đều thao tác được."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db, require_shop_access
from ..schemas.customer import CustomerCreate, CustomerStatusUpdate, CustomerUpdate
from ..services import customer_service, subscription_service

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _require_pro_for_staff_customer(
    db: Session, current_user: models.User, customer_id: int
) -> None:
    if current_user.role != "STAFF":
        return
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id)
        .first()
    )
    if customer is None:
        return  # service phía sau giữ nguyên phản hồi 404 cũ
    require_shop_access(db, customer.shop_id, current_user)
    subscription_service.require_pro(db, customer.shop_id)


@router.post("/{shop_id}")
def create_customer(
    shop_id: int,
    data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == "STAFF":
        require_shop_access(db, shop_id, current_user)
        subscription_service.require_pro(db, shop_id)
    return customer_service.create_customer(db, current_user, shop_id, data)


@router.get("/{shop_id}")
def list_customers(
    shop_id: int,
    q: Optional[str] = Query(None, description="Tìm theo tên hoặc SĐT"),
    include_inactive: bool = Query(False, description="Gồm cả khách đã ngừng sử dụng"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.list_customers(
        db,
        current_user,
        shop_id,
        q=q,
        include_inactive=include_inactive,
    )


@router.get("/member/{customer_id}")
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.get_customer(db, current_user, customer_id)


@router.get("/member/{customer_id}/history")
def customer_history(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.customer_history(db, current_user, customer_id)


@router.put("/member/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_pro_for_staff_customer(db, current_user, customer_id)
    return customer_service.update_customer(db, current_user, customer_id, data)


@router.put("/member/{customer_id}/status")
def update_customer_status(
    customer_id: int,
    data: CustomerStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_pro_for_staff_customer(db, current_user, customer_id)
    return customer_service.update_customer_status(
        db, current_user, customer_id, data
    )


@router.delete("/member/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _require_pro_for_staff_customer(db, current_user, customer_id)
    return customer_service.delete_customer(db, current_user, customer_id)
