"""API nhà cung cấp và trả công nợ."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.supplier import (
    SupplierCreate,
    SupplierPaymentCreate,
    SupplierStatusUpdate,
    SupplierUpdate,
)
from ..services import supplier_service

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("/member/{supplier_id}")
def get_supplier_detail(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.get_supplier_detail(db, current_user, supplier_id)


@router.put("/member/{supplier_id}")
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.update_supplier(db, current_user, supplier_id, payload)


@router.put("/member/{supplier_id}/status")
def update_supplier_status(
    supplier_id: int,
    payload: SupplierStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.update_supplier_status(
        db, current_user, supplier_id, payload
    )


@router.delete("/member/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.delete_supplier(db, current_user, supplier_id)


@router.post("/member/{supplier_id}/payments")
def create_supplier_payment(
    supplier_id: int,
    payload: SupplierPaymentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.create_supplier_payment(
        db, current_user, supplier_id, payload
    )


@router.post("/{shop_id}")
def create_supplier(
    shop_id: int,
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.create_supplier(db, current_user, shop_id, payload)


@router.get("/{shop_id}")
def list_suppliers(
    shop_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return supplier_service.list_suppliers(
        db,
        current_user,
        shop_id,
        include_inactive=include_inactive,
    )
