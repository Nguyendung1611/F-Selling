"""Quản lý nhân viên (role=STAFF) của một shop. Chỉ chủ shop được thao tác.

Nhân viên là một User role=STAFF, gắn đúng một shop qua users.staff_shop_id.
Ở commit này mới chỉ CRUD nhân viên; việc staff đăng nhập và được cấp quyền
truy cập shop nằm ở C1c/C1d.
"""
from __future__ import annotations

from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.security import hash_password, is_strong_password, new_session_id
from ..dependencies import require_own_shop
from ..schemas.staff import StaffCreate
from .log_service import log_system_action

ROLE_STAFF = "STAFF"
PASSWORD_POLICY_MSG = "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số"


def _to_out(staff: models.User) -> Dict:
    return {
        "id": staff.id,
        "username": staff.username,
        "shop_id": staff.staff_shop_id,
        # is_active: tài khoản còn hiệu lực. Ta dùng session_id != None để suy ra
        # "đang có phiên", nhưng trạng thái hoạt động thực chất luôn True khi tồn tại.
        "is_active": True,
    }


def create_staff(
    db: Session, current_user: models.User, shop_id: int, data: StaffCreate
) -> Dict:
    # Chỉ chủ shop mới được tạo nhân viên cho shop của mình.
    require_own_shop(db, shop_id, current_user)

    username = (data.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Tên đăng nhập không được để trống")
    if not is_strong_password(data.password):
        raise HTTPException(status_code=400, detail=PASSWORD_POLICY_MSG)

    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại")

    staff = models.User(
        username=username,
        hashed_password=hash_password(data.password),
        role=ROLE_STAFF,
        # Nhân viên không cần email/verify: chủ shop chịu trách nhiệm tài khoản này.
        email=None,
        is_verified=True,
        staff_shop_id=shop_id,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    log_system_action(
        db,
        current_user.id,
        "CREATE_STAFF",
        f"Tạo nhân viên '{username}' cho shop #{shop_id}",
    )
    return _to_out(staff)


def list_staff(db: Session, current_user: models.User, shop_id: int) -> List[Dict]:
    require_own_shop(db, shop_id, current_user)
    nhan_vien = (
        db.query(models.User)
        .filter(models.User.role == ROLE_STAFF, models.User.staff_shop_id == shop_id)
        .order_by(models.User.username)
        .all()
    )
    return [_to_out(s) for s in nhan_vien]


def delete_staff(db: Session, current_user: models.User, staff_id: int) -> Dict[str, str]:
    staff = (
        db.query(models.User)
        .filter(models.User.id == staff_id, models.User.role == ROLE_STAFF)
        .first()
    )
    if not staff:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân viên")

    # Chỉ chủ của đúng shop mà nhân viên này thuộc về mới được xóa.
    require_own_shop(db, staff.staff_shop_id, current_user)

    username = staff.username
    db.delete(staff)
    db.commit()
    log_system_action(
        db, current_user.id, "DELETE_STAFF", f"Xóa nhân viên '{username}'"
    )
    return {"msg": "Deleted"}


def reset_staff_password(
    db: Session, current_user: models.User, staff_id: int, new_password: str
) -> Dict[str, str]:
    staff = (
        db.query(models.User)
        .filter(models.User.id == staff_id, models.User.role == ROLE_STAFF)
        .first()
    )
    if not staff:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân viên")
    require_own_shop(db, staff.staff_shop_id, current_user)

    if not is_strong_password(new_password):
        raise HTTPException(status_code=400, detail=PASSWORD_POLICY_MSG)

    staff.hashed_password = hash_password(new_password)
    # Vô hiệu mọi phiên đăng nhập cũ của nhân viên này.
    staff.session_id = new_session_id()
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "RESET_STAFF_PASSWORD",
        f"Đặt lại mật khẩu nhân viên '{staff.username}'",
    )
    return {"msg": "Đã đặt lại mật khẩu nhân viên"}
