"""Các endpoint chỉ dành cho ADMIN."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models
from ..core.config import log_to_file
from ..dependencies import get_db, require_admin
from ..services import log_service, report_service
from .reports import XLSX_MEDIA_TYPE

router = APIRouter(tags=["admin"])


@router.get("/api/dashboard/admin")
def get_admin_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    log_to_file(f"get_admin_dashboard requested by user='{current_user.username}'")
    return report_service.admin_dashboard(db)


@router.get("/api/export/admin")
def export_admin_excel(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    stream = report_service.admin_excel(db)
    return StreamingResponse(
        stream,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=admin_revenue.xlsx"},
    )


@router.get("/api/logs/admin")
def get_system_logs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return log_service.get_recent_logs(db, limit=100)
