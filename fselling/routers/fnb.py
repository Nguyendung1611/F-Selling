from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.fnb import (
    FnbAreaCreate,
    FnbAreaUpdate,
    FnbLineCancel,
    FnbLineCreate,
    FnbLineUpdate,
    FnbMergeTable,
    FnbMoveTable,
    FnbSessionCancel,
    FnbSessionOpen,
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
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.get_floor(
        db, current_user, shop_id, after_revision, include_inactive
    )


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


@router.post("/sessions")
def post_session(
    request: FnbSessionOpen,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.open_session(db, current_user, request)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.get_session(db, current_user, session_id)


@router.post("/sessions/{session_id}/lines")
def post_line(
    session_id: int,
    request: FnbLineCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.add_line(db, current_user, session_id, request)


@router.patch("/lines/{line_id}")
def patch_line(
    line_id: int,
    request: FnbLineUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.update_line(db, current_user, line_id, request)


@router.post("/sessions/{session_id}/cancel-line")
def post_cancel_line(
    session_id: int,
    request: FnbLineCancel,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.cancel_line(db, current_user, session_id, request)


@router.post("/sessions/{session_id}/move-table")
def post_move_table(
    session_id: int,
    request: FnbMoveTable,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.move_table(db, current_user, session_id, request)


@router.post("/sessions/{session_id}/merge-table")
def post_merge_table(
    session_id: int,
    request: FnbMergeTable,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.merge_table(db, current_user, session_id, request)


@router.post("/sessions/{session_id}/cancel")
def post_cancel_session(
    session_id: int,
    request: FnbSessionCancel,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return fnb_service.cancel_session(db, current_user, session_id, request)
