from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db, require_shop_access
from ..schemas.catalog import CategoryUpdate
from ..services import catalog_service, subscription_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.post("")
def create_category(
    name: str,
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == "STAFF":
        require_shop_access(db, shop_id, current_user)
        subscription_service.require_pro(db, shop_id)
    return catalog_service.create_category(db, current_user, name, shop_id)


@router.put("/{category_id}")
def update_category(
    category_id: int,
    cat: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == "STAFF":
        category = (
            db.query(models.Category)
            .filter(models.Category.id == category_id)
            .first()
        )
        if category is not None:
            require_shop_access(db, category.shop_id, current_user)
            subscription_service.require_pro(db, category.shop_id)
    return catalog_service.update_category(db, current_user, category_id, cat)


@router.get("/{shop_id}")
def get_categories(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.list_categories(db, current_user, shop_id)
