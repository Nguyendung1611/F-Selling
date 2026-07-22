"""Nghiệp vụ danh mục & sản phẩm (gồm kiểm tra file ảnh upload)."""
from __future__ import annotations

import os
import pathlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..core.config import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_IMAGE_MIMES,
    MAX_IMAGE_SIZE,
    UPLOAD_DIR,
)
from ..dependencies import require_shop_access
from ..schemas.catalog import CategoryUpdate
from .log_service import log_system_action

DEFAULT_PRODUCT_IMAGE = "https://placehold.co/150x150/1E293B/FFF?text=SP"


def is_valid_image(data: bytes) -> bool:
    """Kiểm tra magic bytes để xác nhận file thực sự là JPEG/PNG/WEBP."""
    if len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP
        return True
    return False


def _require_own_shop_403(db: Session, shop_id: int, current_user: models.User) -> models.Shop:
    """Một số endpoint cũ trả 403 'Not your shop' khi shop không thuộc user."""
    shop = (
        db.query(models.Shop)
        .filter(models.Shop.id == shop_id, models.Shop.owner_id == current_user.id)
        .first()
    )
    if not shop:
        raise HTTPException(status_code=403, detail="Not your shop")
    return shop


# --- Categories ---
def create_category(
    db: Session, current_user: models.User, name: str, shop_id: int
) -> models.Category:
    _require_own_shop_403(db, shop_id, current_user)

    name_stripped = name.strip() if name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên danh mục không được để trống")

    cat = models.Category(name=name_stripped, shop_id=shop_id, is_active=True)
    db.add(cat)
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "CREATE_CATEGORY",
        f"Tạo danh mục '{name_stripped}' cho shop #{shop_id}",
    )
    db.refresh(cat)
    return cat


def update_category(
    db: Session, current_user: models.User, category_id: int, cat: CategoryUpdate
) -> models.Category:
    db_cat = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not db_cat:
        raise HTTPException(status_code=404, detail="Danh mục không tồn tại")

    shop = (
        db.query(models.Shop)
        .filter(models.Shop.id == db_cat.shop_id, models.Shop.owner_id == current_user.id)
        .first()
    )
    if not shop:
        raise HTTPException(
            status_code=403, detail="Không có quyền chỉnh sửa danh mục của cửa hàng này"
        )

    name_stripped = cat.name.strip() if cat.name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên danh mục không được để trống")

    db_cat.name = name_stripped
    db_cat.is_active = cat.is_active
    db.commit()
    db.refresh(db_cat)
    log_system_action(
        db,
        current_user.id,
        "UPDATE_CATEGORY",
        f"Cập nhật danh mục: '{db_cat.name}' (ID: {db_cat.id}, Active: {db_cat.is_active})",
    )
    db.refresh(db_cat)
    return db_cat


def list_categories(
    db: Session, current_user: models.User, shop_id: int
) -> List[models.Category]:
    require_shop_access(db, shop_id, current_user)
    return db.query(models.Category).filter(models.Category.shop_id == shop_id).all()


# --- Products ---
def save_product_image(image: UploadFile) -> str:
    """Kiểm tra loại file, đuôi file, kích thước, magic bytes;
    tự sinh tên file bằng UUID (tránh path traversal). Trả về URL public."""
    if image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=400, detail="Loại file không hợp lệ. Chỉ chấp nhận JPG, PNG, WEBP"
        )

    ext = pathlib.Path(image.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="Đuôi file không hợp lệ")

    contents = image.file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File quá lớn (tối đa 2MB)")
    if not contents:
        raise HTTPException(status_code=400, detail="File rỗng")

    if not is_valid_image(contents):
        raise HTTPException(status_code=400, detail="Nội dung file không phải ảnh hợp lệ")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        buffer.write(contents)
    return f"/uploads/{filename}"


def create_product(
    db: Session,
    current_user: models.User,
    shop_id: int,
    name: str,
    price: float,
    stock: int,
    category_id: int,
    code: Optional[str] = None,
    image: Optional[UploadFile] = None,
) -> models.Product:
    _require_own_shop_403(db, shop_id, current_user)

    existing_prod = (
        db.query(models.Product)
        .filter(models.Product.shop_id == shop_id, models.Product.name == name)
        .first()
    )
    if existing_prod:
        raise HTTPException(
            status_code=400, detail="Sản phẩm với tên này đã tồn tại trong cửa hàng!"
        )

    if price <= 0:
        raise HTTPException(status_code=400, detail="Giá sản phẩm phải lớn hơn 0")
    if stock < 0:
        raise HTTPException(status_code=400, detail="Số lượng tồn kho không được âm")

    image_url = DEFAULT_PRODUCT_IMAGE
    if image and image.filename:
        image_url = save_product_image(image)

    if not code:
        code = f"SP-{int(datetime.utcnow().timestamp())}"

    p = models.Product(
        code=code,
        name=name,
        price=price,
        stock=stock,
        image_url=image_url,
        category_id=category_id,
        shop_id=shop_id,
    )
    db.add(p)
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "CREATE_PRODUCT",
        f"Tạo SP: '{name}' ({code}) - Giá: {price:,.0f}đ, Kho: {stock}",
    )
    db.refresh(p)
    return p


def list_products(db: Session, shop_id: int) -> List[Dict]:
    products = db.query(models.Product).filter(models.Product.shop_id == shop_id).all()
    res: List[Dict] = []
    for p in products:
        cat_active = True
        if p.category:
            cat_active = p.category.is_active if p.category.is_active is not None else True
        res.append(
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "price": p.price,
                "stock": p.stock,
                "image_url": p.image_url,
                "is_active": p.is_active,
                "category_id": p.category_id,
                "shop_id": p.shop_id,
                "category_is_active": cat_active,
            }
        )
    return res


def update_product(
    db: Session,
    current_user: models.User,
    product_id: int,
    name: str,
    price: float,
    category_id: int,
    code: Optional[str] = None,
    image: Optional[UploadFile] = None,
) -> models.Product:
    """Sửa thông tin sản phẩm: tên, giá, mã, danh mục, ảnh.

    CỐ Ý KHÔNG đụng vào `stock`. Ghi đè tồn kho từ form sửa gây mất hàng khi
    có bán song song (seller mở form thấy tồn 100, POS bán vài đơn, seller bấm
    Lưu -> tồn quay lại 100). Thay đổi tồn kho đi qua `adjust_stock` (nhập/xuất
    theo delta, cập nhật nguyên tử).
    """
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)

    name_stripped = name.strip() if name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên sản phẩm không được để trống")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Giá sản phẩm phải lớn hơn 0")

    category = (
        db.query(models.Category)
        .filter(
            models.Category.id == category_id,
            models.Category.shop_id == prod.shop_id,
        )
        .first()
    )
    if not category:
        raise HTTPException(status_code=400, detail="Danh mục không thuộc cửa hàng này")

    duplicate = (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == prod.shop_id,
            models.Product.name == name_stripped,
            models.Product.id != product_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="Sản phẩm với tên này đã tồn tại trong cửa hàng!",
        )

    prod.code = code.strip() if code and code.strip() else prod.code
    prod.name = name_stripped
    prod.price = price
    prod.category_id = category_id
    if image and image.filename:
        prod.image_url = save_product_image(image)

    db.commit()
    log_system_action(
        db,
        current_user.id,
        "UPDATE_PRODUCT",
        f"Cập nhật SP: '{prod.name}' ({prod.code}) - Giá: {price:,.0f}đ",
    )
    db.refresh(prod)
    return prod


_ADJUST_STOCK = text(
    "UPDATE products SET stock = stock + :delta "
    "WHERE id = :product_id AND stock + :delta >= 0"
)


def adjust_stock(
    db: Session, current_user: models.User, product_id: int, delta: int
) -> Dict[str, Any]:
    """Nhập (delta > 0) hoặc xuất (delta < 0) kho theo số lượng thay đổi.

    Dùng UPDATE nguyên tử `stock = stock + delta` thay vì đọc-rồi-ghi, nên
    nhiều thao tác kho / bán hàng chạy song song không ghi đè lẫn nhau. Điều
    kiện `stock + delta >= 0` nằm ngay trong câu UPDATE -> tồn kho không bao
    giờ âm; nếu xuất quá số đang có, rowcount = 0 và ta báo lỗi.
    """
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)

    if delta == 0:
        raise HTTPException(status_code=400, detail="Số lượng thay đổi phải khác 0")

    result = db.execute(_ADJUST_STOCK, {"delta": delta, "product_id": product_id})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Không đủ tồn kho để xuất {abs(delta)} (hiện còn {prod.stock})",
        )
    db.commit()
    db.refresh(prod)

    hanh_dong = "Nhập" if delta > 0 else "Xuất"
    log_system_action(
        db,
        current_user.id,
        "ADJUST_STOCK",
        f"{hanh_dong} kho SP '{prod.name}' ({prod.code}): "
        f"{'+' if delta > 0 else ''}{delta} -> tồn {prod.stock}",
    )
    return {"id": prod.id, "stock": prod.stock, "delta": delta}


def toggle_product_status(
    db: Session, current_user: models.User, product_id: int
) -> Dict[str, bool]:
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    prod.is_active = not prod.is_active
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "TOGGLE_PRODUCT_STATUS",
        f"Đổi trạng thái SP '{prod.name}' ({prod.code}): {'Hiện' if prod.is_active else 'Ẩn'}",
    )
    return {"is_active": prod.is_active}


def delete_product(db: Session, current_user: models.User, product_id: int) -> Dict[str, str]:
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    name, code = prod.name, prod.code
    db.delete(prod)
    db.commit()
    log_system_action(db, current_user.id, "DELETE_PRODUCT", f"Xóa SP '{name}' ({code})")
    return {"msg": "Deleted"}
