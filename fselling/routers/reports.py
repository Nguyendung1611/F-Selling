"""Dashboard và export của SELLER."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import report_service

router = APIRouter(tags=["reports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/api/dashboard/seller/{shop_id}")
def get_seller_dashboard(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return report_service.seller_dashboard(db, current_user, shop_id)


@router.get("/api/export/seller/{shop_id}")
def export_seller_excel(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    stream = report_service.seller_excel(db, current_user, shop_id)
    return StreamingResponse(
        stream,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=seller_transactions.xlsx"},
    )
