"""Dashboard và export của SELLER."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
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
    page: int = Query(1, ge=1, description="Trang, bắt đầu từ 1"),
    per_page: int = Query(
        report_service.DEFAULT_PAGE_SIZE, ge=1, le=report_service.MAX_PAGE_SIZE
    ),
    tu_ngay: Optional[str] = Query(None, description="Lọc từ ngày (YYYY-MM-DD)"),
    den_ngay: Optional[str] = Query(None, description="Lọc đến ngày (YYYY-MM-DD)"),
    reconciliation_only: bool = Query(False, description="Chỉ đơn đang cần đối soát"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return report_service.seller_dashboard(
        db, current_user, shop_id, page=page, per_page=per_page,
        tu_ngay=tu_ngay, den_ngay=den_ngay,
        reconciliation_only=reconciliation_only,
    )


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
