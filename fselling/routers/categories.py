from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.catalog import CategoryUpdate
from ..services import catalog_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.post("")
def create_category(
    name: str,
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.create_category(db, current_user, name, shop_id)


@router.put("/{category_id}")
def update_category(
    category_id: int,
    cat: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.update_category(db, current_user, category_id, cat)


@router.get("/{shop_id}")
def get_categories(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.list_categories(db, current_user, shop_id)
