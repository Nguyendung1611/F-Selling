"""Nghiệp vụ cửa hàng."""
from __future__ import annotations

from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.config import MAX_SHOPS_PER_USER, log_to_file
from ..core.i18n import tr
from ..core.security import new_session_id
from ..dependencies import require_own_shop
from ..schemas.shop import ShopCreate
from .log_service import log_system_action

# (thuộc tính trên model, giá trị từ request, thông báo lỗi khi rỗng)
_REQUIRED_FIELDS = [
    ("name", "Tên cửa hàng không được để trống"),
    ("business_address", "Địa chỉ kinh doanh không được để trống"),
    ("tax_code", "Mã số thuế không được để trống"),
    ("phone", "Số điện thoại không được để trống"),
    ("email", "Email không được để trống"),
    ("bank_code", "Vui lòng chọn ngân hàng"),
    ("bank_account_no", "Số tài khoản không được để trống"),
    ("bank_account_name", "Tên chủ tài khoản không được để trống"),
]


def _clean_and_validate(shop: ShopCreate) -> Dict[str, str]:
    """Trim toàn bộ field và validate theo đúng thứ tự thông báo lỗi như code cũ."""
    data = {
        "name": (shop.name or "").strip(),
        "business_address": (shop.business_address or "").strip(),
        "tax_code": (shop.tax_code or "").strip(),
        "phone": (shop.phone or "").strip(),
        "email": (shop.email or "").strip(),
        "bank_account_no": (shop.bank_account_no or "").strip(),
        "bank_account_name": (shop.bank_account_name or "").strip(),
        "bank_code": (shop.bank_code or "").strip(),
    }
    for field, message in _REQUIRED_FIELDS:
        if not data[field]:
            raise HTTPException(status_code=400, detail=tr(message))
    return data


def create_shop(db: Session, current_user: models.User, shop: ShopCreate) -> models.Shop:
    # STAFF chỉ vận hành shop được gán; nếu tự tạo shop họ sẽ trở thành owner
    # và đi vòng qua ranh giới quản trị đang được require_own_shop bảo vệ.
    if current_user.role == "STAFF":
        raise HTTPException(
            status_code=403,
            detail=tr("Nhân viên không được tạo cửa hàng"),
        )
    count = db.query(models.Shop).filter(models.Shop.owner_id == current_user.id).count()
    if count >= MAX_SHOPS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Bạn chỉ được tạo tối đa {count} cửa hàng",
                count=MAX_SHOPS_PER_USER,
            ),
        )

    data = _clean_and_validate(shop)
    new_shop = models.Shop(owner_id=current_user.id, **data)
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)
    log_system_action(
        db,
        current_user.id,
        "CREATE_SHOP",
        f"Tạo cửa hàng: '{new_shop.name}' (SĐT: {new_shop.phone}, Bank: {new_shop.bank_code})",
    )
    db.refresh(new_shop)
    return new_shop


def update_shop(
    db: Session, current_user: models.User, shop_id: int, shop: ShopCreate
) -> models.Shop:
    db_shop = require_own_shop(db, shop_id, current_user)
    data = _clean_and_validate(shop)
    for field, value in data.items():
        setattr(db_shop, field, value)
    db.commit()
    db.refresh(db_shop)
    log_system_action(
        db,
        current_user.id,
        "UPDATE_SHOP",
        f"Cập nhật cửa hàng: '{db_shop.name}' (SĐT: {db_shop.phone})",
    )
    db.refresh(db_shop)
    return db_shop


def toggle_shop_status(db: Session, current_user: models.User, shop_id: int) -> Dict[str, bool]:
    db_shop = require_own_shop(db, shop_id, current_user)
    db_shop.is_active = not db_shop.is_active
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "TOGGLE_SHOP_STATUS",
        f"Đổi trạng thái cửa hàng '{db_shop.name}': "
        f"{'Hoạt động' if db_shop.is_active else 'Khóa'}",
    )
    return {"is_active": db_shop.is_active}


def list_shops(db: Session, current_user: models.User) -> List[models.Shop]:
    log_to_file(f"get_shops requested by user='{current_user.username}' (ID={current_user.id})")
    if current_user.role == "STAFF":
        # Nhân viên chỉ thấy đúng shop được gán, không thấy shop nào khác.
        shops = (
            db.query(models.Shop)
            .filter(models.Shop.id == current_user.staff_shop_id)
            .all()
        )
    else:
        shops = db.query(models.Shop).filter(models.Shop.owner_id == current_user.id).all()
    log_to_file(f"get_shops DB query returned: {[s.id for s in shops]}")
    return shops


def delete_shop(db: Session, current_user: models.User, shop_id: int) -> Dict[str, str]:
    db_shop = require_own_shop(db, shop_id, current_user)
    shop_name = db_shop.name

    order_ids = [
        row[0] for row in db.query(models.Order.id).filter(models.Order.shop_id == shop_id).all()
    ]
    shift_ids = [
        row[0]
        for row in db.query(models.CashShift.id)
        .filter(models.CashShift.shop_id == shop_id)
        .all()
    ]
    if shift_ids:
        db.query(models.CashMovement).filter(
            models.CashMovement.shift_id.in_(shift_ids)
        ).delete(synchronize_session=False)
    if order_ids:
        db.query(models.OrderPayment).filter(
            models.OrderPayment.order_id.in_(order_ids)
        ).delete(synchronize_session=False)
        db.query(models.OrderItem).filter(
            models.OrderItem.order_id.in_(order_ids)
        ).delete(synchronize_session=False)
    db.query(models.Order).filter(models.Order.shop_id == shop_id).delete(
        synchronize_session=False
    )
    if shift_ids:
        db.query(models.CashShift).filter(
            models.CashShift.id.in_(shift_ids)
        ).delete(synchronize_session=False)
    db.query(models.Customer).filter(models.Customer.shop_id == shop_id).delete(
        synchronize_session=False
    )
    db.query(models.Product).filter(models.Product.shop_id == shop_id).delete(
        synchronize_session=False
    )
    db.query(models.Category).filter(models.Category.shop_id == shop_id).delete(
        synchronize_session=False
    )
    db.query(models.Voucher).filter(models.Voucher.shop_id == shop_id).delete(
        synchronize_session=False
    )
    # Shop không còn tồn tại thì mọi tài khoản nhân viên gán vào đó phải bị
    # vô hiệu ngay; giữ User để audit cũ vẫn truy ra đúng tên.
    db.query(models.User).filter(
        models.User.role == "STAFF",
        models.User.staff_shop_id == shop_id,
    ).update(
        {
            models.User.is_active: False,
            models.User.session_id: new_session_id(),
            models.User.staff_shop_id: None,
        },
        synchronize_session=False,
    )

    db.delete(db_shop)
    db.commit()
    log_system_action(db, current_user.id, "DELETE_SHOP", f"Xóa cửa hàng '{shop_name}'")
    return {"msg": "Deleted"}
