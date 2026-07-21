from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.shop import ShopCreate
from ..services import report_service, shop_service

router = APIRouter(prefix="/api/shops", tags=["shops"])


@router.post("")
def create_shop(
    shop: ShopCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shop_service.create_shop(db, current_user, shop)


@router.get("")
def get_shops(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shop_service.list_shops(db, current_user)


@router.put("/{shop_id}")
def update_shop(
    shop_id: int,
    shop: ShopCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shop_service.update_shop(db, current_user, shop_id, shop)


@router.put("/{shop_id}/status")
def toggle_shop_status(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shop_service.toggle_shop_status(db, current_user, shop_id)


@router.delete("/{shop_id}")
def delete_shop(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return shop_service.delete_shop(db, current_user, shop_id)


@router.get("/{shop_id}/stats")
def get_shop_stats(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return report_service.shop_stats(db, current_user, shop_id)
