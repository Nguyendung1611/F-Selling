from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.fnb import (
    FnbAreaCreate,
    FnbAreaUpdate,
    FnbSettingsUpdate,
    FnbTableCreate,
    FnbTableUpdate,
)
from ..services import fnb_service

router = APIRouter(prefix="/api/fnb", tags=["fnb"])


@router.patch("/shops/{shop_id}/settings")
def patch_settings(
    shop_id: int,
    request: FnbSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.update_fnb_settings(db, current_user, shop_id, request)


@router.get("/floor")
def floor(
    shop_id: int,
    after_revision: int | None = Query(None, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.get_floor(db, current_user, shop_id, after_revision)


@router.post("/areas")
def post_area(
    request: FnbAreaCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.create_area(db, current_user, request)


@router.patch("/areas/{area_id}")
def patch_area(
    area_id: int,
    request: FnbAreaUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.update_area(db, current_user, area_id, request)


@router.post("/tables")
def post_table(
    request: FnbTableCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.create_table(db, current_user, request)


@router.patch("/tables/{table_id}")
def patch_table(
    table_id: int,
    request: FnbTableUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.update_table(db, current_user, table_id, request)
