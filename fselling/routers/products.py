from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import catalog_service

router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("")
def create_product(
    shop_id: int,
    code: Optional[str] = Form(None),
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    category_id: int = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.create_product(
        db,
        current_user,
        shop_id=shop_id,
        name=name,
        price=price,
        stock=stock,
        category_id=category_id,
        code=code,
        image=image,
    )


@router.get("/{shop_id}")
def get_products(shop_id: int, db: Session = Depends(get_db)):
    return catalog_service.list_products(db, shop_id)


@router.put("/{product_id}/status")
def toggle_product_status(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.toggle_product_status(db, current_user, product_id)


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.delete_product(db, current_user, product_id)
