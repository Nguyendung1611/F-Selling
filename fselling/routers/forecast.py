"""Dự báo nhập hàng (G1). Router mỏng: chỉ nhận tham số và gọi service."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import forecast_service

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("/{shop_id}")
def du_bao_nhap_hang(
    shop_id: int,
    thoi_gian_dat_hang: int = Query(
        forecast_service.THOI_GIAN_DAT_HANG_MAC_DINH,
        ge=1,
        le=60,
        description="Số ngày từ lúc gọi nhà cung cấp tới lúc hàng về kệ",
    ),
    muon_du_cho: int = Query(
        forecast_service.MUON_DU_CHO_MAC_DINH,
        ge=1,
        le=90,
        description="Nhập một lần muốn đủ bán bao nhiêu ngày nữa",
    ),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Sản phẩm nào sắp hết, cần nhập bao nhiêu, gọi cho nhà cung cấp nào.

    Quyền và việc ẩn giá vốn nằm trong service, không nằm ở đây.
    """
    return forecast_service.du_bao_nhap_hang(
        db,
        current_user,
        shop_id,
        thoi_gian_dat_hang=thoi_gian_dat_hang,
        muon_du_cho=muon_du_cho,
    )
