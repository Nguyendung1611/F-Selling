"""Router khách hàng (CRM). Chủ shop và nhân viên của shop đều thao tác được."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.customer import CustomerCreate, CustomerUpdate
from ..services import customer_service

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.post("/{shop_id}")
def create_customer(
    shop_id: int,
    data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.create_customer(db, current_user, shop_id, data)


@router.get("/{shop_id}")
def list_customers(
    shop_id: int,
    q: Optional[str] = Query(None, description="Tìm theo tên hoặc SĐT"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.list_customers(db, current_user, shop_id, q=q)


@router.get("/member/{customer_id}")
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.get_customer(db, current_user, customer_id)


@router.put("/member/{customer_id}")
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.update_customer(db, current_user, customer_id, data)


@router.delete("/member/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return customer_service.delete_customer(db, current_user, customer_id)
