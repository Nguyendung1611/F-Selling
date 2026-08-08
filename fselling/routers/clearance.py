"""Xả hàng tồn (L2). Router mỏng: chỉ nhận tham số và gọi service."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..services import clearance_service

router = APIRouter(prefix="/api/clearance", tags=["clearance"])


@router.get("/{shop_id}")
def de_xuat_xa_hang(
    shop_id: int,
    so_ngay_coi_la_e: int = Query(
        clearance_service.SO_NGAY_COI_LA_E,
        ge=7,
        le=365,
        description="Bao lâu không bán được món nào thì coi là hàng nằm ế",
    ),
    so_ngay_canh_bao_han: int = Query(
        clearance_service.SO_NGAY_CANH_BAO_HAN,
        ge=1,
        le=180,
        description="Lô còn hạn dưới ngần này ngày thì phải đẩy đi",
    ),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Hàng nào đang chôn vốn, và hạ giá tới đâu thì vẫn còn lãi.

    CHỈ ĐỌC. Không tự đổi giá và không tự tạo voucher: đổi giá bán là quyết
    định của chủ shop, máy chỉ đưa ra con số và mở sẵn ô sửa.

    Quyền nằm trong service (`require_cost_visibility`), không nằm ở đây.
    """
    return clearance_service.de_xuat_xa_hang(
        db,
        current_user,
        shop_id,
        so_ngay_coi_la_e=so_ngay_coi_la_e,
        so_ngay_canh_bao_han=so_ngay_canh_bao_han,
    )
