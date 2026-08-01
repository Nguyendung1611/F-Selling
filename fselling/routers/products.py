from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.catalog import StockAdjust, StocktakeApply
from ..services import catalog_service

router = APIRouter(prefix="/api/products", tags=["products"])


async def barcode_field(request: Request) -> Optional[str]:
    """Lấy mã vạch từ form, phân biệt được "không gửi" với "gửi rỗng".

    FastAPI 0.139 quy đổi form field rỗng thành giá trị mặc định, nên khai báo
    `Form(None)` trả về `None` cho cả hai trường hợp - không phân biệt được
    form cũ (chưa có ô mã vạch, phải giữ nguyên mã đang có) với người dùng cố ý
    xóa trắng ô để gỡ mã vạch gán nhầm. Đọc lại form thô để biết field có mặt.

    Là dependency **async** nhưng endpoint vẫn để `def` đồng bộ: FastAPI giải
    dependency trên event loop rồi chạy endpoint trong threadpool, nên phần gọi
    database đồng bộ vẫn không chặn event loop.

    Trả về `None` = giữ nguyên, `""` = xóa mã vạch, chuỗi khác = gán mã mới.
    """
    form = await request.form()
    if "barcode" not in form:
        return None
    return str(form.get("barcode") or "")


async def cost_price_field(request: Request) -> Optional[str]:
    """Lấy giá vốn từ form, cùng lý do và cùng cách làm với `barcode_field`.

    Trả về `None` = giữ nguyên giá vốn, `""` = xóa giá vốn về NULL (khai nhầm
    thì gỡ ra được), chuỗi số = đặt giá vốn mới. Service parse và báo 400 nếu
    không phải số.
    """
    form = await request.form()
    if "cost_price" not in form:
        return None
    return str(form.get("cost_price") or "")


@router.post("")
def create_product(
    shop_id: int,
    code: Optional[str] = Form(None),
    barcode: Optional[str] = Form(None),
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    category_id: int = Form(...),
    image: UploadFile = File(None),
    cost_price: Optional[float] = Form(None),
    track_batches: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.create_product(
        db,
        current_user,
        shop_id=shop_id,
        name=name,
        price=price,
        stock=stock,
        category_id=category_id,
        code=code,
        barcode=barcode,
        image=image,
        cost_price=cost_price,
        track_batches=track_batches,
    )


@router.get("/{shop_id}")
def get_products(shop_id: int, db: Session = Depends(get_db)):
    """CỐ Ý không yêu cầu đăng nhập (hành vi sẵn có, POS đang dựa vào).
    Vì vậy tuyệt đối KHÔNG trả `cost_price` ở đây - giá vốn đi qua
    `GET /{shop_id}/costs`, nơi có xác thực và chỉ chủ shop xem được."""
    return catalog_service.list_products(db, shop_id)


@router.get("/{shop_id}/costs")
def get_product_costs(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.list_product_costs(db, current_user, shop_id)


@router.get("/{shop_id}/batches")
def get_product_batches(
    shop_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.danh_sach_lo(db, current_user, shop_id, days)


@router.get("/{shop_id}/barcode/{barcode}")
def get_product_by_barcode(
    shop_id: int,
    barcode: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.lookup_by_barcode(db, current_user, shop_id, barcode)


@router.put("/{product_id}")
def update_product(
    product_id: int,
    code: Optional[str] = Form(None),
    barcode: Optional[str] = Depends(barcode_field),
    name: str = Form(...),
    price: float = Form(...),
    # `stock` được chấp nhận để không phá form cũ nhưng KHÔNG dùng: đổi tồn kho
    # đi qua POST /{product_id}/stock (nhập/xuất theo delta, cập nhật nguyên tử).
    stock: Optional[int] = Form(None),
    category_id: int = Form(...),
    image: UploadFile = File(None),
    cost_price: Optional[str] = Depends(cost_price_field),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.update_product(
        db,
        current_user,
        product_id=product_id,
        name=name,
        price=price,
        category_id=category_id,
        code=code,
        barcode=barcode,
        image=image,
        cost_price=cost_price,
    )


@router.post("/{product_id}/stock")
def adjust_stock(
    product_id: int,
    payload: StockAdjust,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.adjust_stock(
        db, current_user, product_id, payload.delta, payload.unit_cost,
        payload.expiry_date,
    )


@router.post("/{shop_id}/stocktake")
def apply_stocktake(
    shop_id: int,
    payload: StocktakeApply,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.apply_stocktake(db, current_user, shop_id, payload.items)


@router.put("/{product_id}/status")
def toggle_product_status(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.toggle_product_status(db, current_user, product_id)


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return catalog_service.delete_product(db, current_user, product_id)
