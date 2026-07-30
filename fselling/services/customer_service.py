"""Nghiệp vụ khách hàng (CRM). Chủ shop và nhân viên của shop đều quản lý được.

SĐT là định danh khách trong phạm vi một shop (duy nhất theo shop). Nhập lại
SĐT cũ -> nhận ra khách cũ thay vì tạo trùng.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import (
    PERMISSION_CUSTOMER,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.customer import CustomerCreate, CustomerUpdate
from .log_service import log_system_action


def _to_out(c: models.Customer) -> Dict:
    return {
        "id": c.id,
        "shop_id": c.shop_id,
        "name": c.name,
        "phone": c.phone,
        "address": c.address,
        "note": c.note,
    }


def _clean(name: str, phone: str) -> tuple:
    name_s = (name or "").strip()
    phone_s = (phone or "").strip()
    if not name_s:
        raise HTTPException(status_code=400, detail="Tên khách hàng không được để trống")
    if not phone_s:
        raise HTTPException(status_code=400, detail="Số điện thoại không được để trống")
    return name_s, phone_s


def create_customer(
    db: Session, current_user: models.User, shop_id: int, data: CustomerCreate
) -> Dict:
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_CUSTOMER)
    name, phone = _clean(data.name, data.phone)

    trung = (
        db.query(models.Customer)
        .filter(models.Customer.shop_id == shop_id, models.Customer.phone == phone)
        .first()
    )
    if trung:
        raise HTTPException(
            status_code=400, detail="Số điện thoại này đã có trong danh sách khách hàng"
        )

    kh = models.Customer(
        shop_id=shop_id,
        name=name,
        phone=phone,
        address=(data.address or "").strip() or None,
        note=(data.note or "").strip() or None,
    )
    db.add(kh)
    db.commit()
    db.refresh(kh)
    log_system_action(
        db, current_user.id, "CREATE_CUSTOMER", f"Thêm khách '{name}' ({phone}) cho shop #{shop_id}"
    )
    return _to_out(kh)


def list_customers(
    db: Session, current_user: models.User, shop_id: int, q: Optional[str] = None
) -> List[Dict]:
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_CUSTOMER)
    query = db.query(models.Customer).filter(models.Customer.shop_id == shop_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (models.Customer.name.like(like)) | (models.Customer.phone.like(like))
        )
    khs = query.order_by(models.Customer.name).all()
    return [_to_out(c) for c in khs]


def _get_owned_customer(
    db: Session, current_user: models.User, customer_id: int
) -> models.Customer:
    kh = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not kh:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách hàng")
    require_shop_access(db, kh.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_CUSTOMER)
    return kh


def get_customer(db: Session, current_user: models.User, customer_id: int) -> Dict:
    return _to_out(_get_owned_customer(db, current_user, customer_id))


def update_customer(
    db: Session, current_user: models.User, customer_id: int, data: CustomerUpdate
) -> Dict:
    kh = _get_owned_customer(db, current_user, customer_id)
    name, phone = _clean(data.name, data.phone)

    trung = (
        db.query(models.Customer)
        .filter(
            models.Customer.shop_id == kh.shop_id,
            models.Customer.phone == phone,
            models.Customer.id != customer_id,
        )
        .first()
    )
    if trung:
        raise HTTPException(
            status_code=400, detail="Số điện thoại này đã có trong danh sách khách hàng"
        )

    kh.name = name
    kh.phone = phone
    kh.address = (data.address or "").strip() or None
    kh.note = (data.note or "").strip() or None
    db.commit()
    db.refresh(kh)
    log_system_action(db, current_user.id, "UPDATE_CUSTOMER", f"Cập nhật khách '{name}' ({phone})")
    return _to_out(kh)


def customer_history(db: Session, current_user: models.User, customer_id: int) -> Dict:
    """Lịch sử mua của một khách: thông tin khách + danh sách đơn + tổng đã chi
    (chỉ tính đơn đã thanh toán)."""
    kh = _get_owned_customer(db, current_user, customer_id)
    orders = (
        db.query(models.Order)
        .filter(models.Order.customer_id == customer_id)
        .order_by(models.Order.created_at.desc())
        .all()
    )
    tong_da_chi = sum(o.total_amount or 0 for o in orders if o.status == "PAID")
    return {
        "customer": _to_out(kh),
        "total_paid": tong_da_chi,
        "order_count": len(orders),
        "orders": [
            {
                "id": o.id,
                "total": o.total_amount,
                "status": o.status,
                "date": o.created_at,
            }
            for o in orders
        ],
    }


def delete_customer(db: Session, current_user: models.User, customer_id: int) -> Dict[str, str]:
    kh = _get_owned_customer(db, current_user, customer_id)
    ten = kh.name

    # Không xóa cứng liên kết trên đơn cũ: gỡ tham chiếu để giữ lịch sử đơn,
    # rồi mới xóa hồ sơ khách. Đơn vẫn còn, chỉ không còn gắn khách.
    db.query(models.Order).filter(models.Order.customer_id == customer_id).update(
        {models.Order.customer_id: None}, synchronize_session=False
    )
    db.delete(kh)
    db.commit()
    log_system_action(db, current_user.id, "DELETE_CUSTOMER", f"Xóa khách '{ten}'")
    return {"msg": "Deleted"}
