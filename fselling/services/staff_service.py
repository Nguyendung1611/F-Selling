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
from ..core.i18n import tr
from ..core.security import hash_password, is_strong_password, new_session_id
from ..dependencies import effective_staff_role, require_own_shop
from ..schemas.staff import StaffCreate, StaffRoleUpdate
from .log_service import log_system_action

ROLE_STAFF = "STAFF"
PASSWORD_POLICY_MSG = "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số"


def _to_out(staff: models.User) -> Dict:
    return {
        "id": staff.id,
        "username": staff.username,
        "shop_id": staff.staff_shop_id,
        "is_active": staff.is_active is not False,
        "staff_role": effective_staff_role(staff),
    }


def create_staff(
    db: Session, current_user: models.User, shop_id: int, data: StaffCreate
) -> Dict:
    # Chỉ chủ shop mới được tạo nhân viên cho shop của mình.
    require_own_shop(db, shop_id, current_user)

    username = (data.username or "").strip()
    if not username:
        raise HTTPException(
            status_code=400,
            detail=tr("Tên đăng nhập không được để trống"),
        )
    if not is_strong_password(data.password):
        raise HTTPException(status_code=400, detail=tr(PASSWORD_POLICY_MSG))

    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=400, detail=tr("Tên đăng nhập đã tồn tại"))

    staff = models.User(
        username=username,
        hashed_password=hash_password(data.password),
        role=ROLE_STAFF,
        # Nhân viên không cần email/verify: chủ shop chịu trách nhiệm tài khoản này.
        email=None,
        is_verified=True,
        staff_shop_id=shop_id,
        staff_role=data.staff_role,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    log_system_action(
        db,
        current_user.id,
        "CREATE_STAFF",
        f"Tạo nhân viên '{username}' ({data.staff_role}) cho shop #{shop_id}",
    )
    db.refresh(staff)
    return _to_out(staff)


def list_staff(db: Session, current_user: models.User, shop_id: int) -> List[Dict]:
    require_own_shop(db, shop_id, current_user)
    nhan_vien = (
        db.query(models.User)
        .filter(
            models.User.role == ROLE_STAFF,
            models.User.staff_shop_id == shop_id,
            models.User.is_active.is_(True),
        )
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
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy nhân viên"))

    # Chỉ chủ của đúng shop mà nhân viên này thuộc về mới được xóa.
    require_own_shop(db, staff.staff_shop_id, current_user)
    open_shift = (
        db.query(models.CashShift.id)
        .filter(
            models.CashShift.shop_id == staff.staff_shop_id,
            models.CashShift.opened_by_user_id == staff.id,
            models.CashShift.status == "OPEN",
        )
        .first()
    )
    if open_shift:
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Nhân viên còn ca đang mở; hãy kết ca trước khi ngừng tài khoản"
            ),
        )

    username = staff.username
    # Giữ User để Order/CashShift/SystemLog còn truy ra đúng tên thu ngân.
    # Đổi session_id để token đang mở trên web hết hiệu lực ngay.
    staff.is_active = False
    staff.session_id = new_session_id()
    db.commit()
    log_system_action(
        db, current_user.id, "DISABLE_STAFF", f"Ngừng tài khoản nhân viên '{username}'"
    )
    return {"msg": "Disabled"}


def reset_staff_password(
    db: Session, current_user: models.User, staff_id: int, new_password: str
) -> Dict[str, str]:
    staff = (
        db.query(models.User)
        .filter(models.User.id == staff_id, models.User.role == ROLE_STAFF)
        .first()
    )
    if not staff:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy nhân viên"))
    require_own_shop(db, staff.staff_shop_id, current_user)

    if not is_strong_password(new_password):
        raise HTTPException(status_code=400, detail=tr(PASSWORD_POLICY_MSG))

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
    return {"msg": tr("Đã đặt lại mật khẩu nhân viên")}


def update_staff_role(
    db: Session,
    current_user: models.User,
    staff_id: int,
    data: StaffRoleUpdate,
) -> Dict:
    staff = (
        db.query(models.User)
        .filter(models.User.id == staff_id, models.User.role == ROLE_STAFF)
        .first()
    )
    if not staff:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy nhân viên"))
    require_own_shop(db, staff.staff_shop_id, current_user)

    old_role = effective_staff_role(staff)
    staff.staff_role = data.staff_role
    # Buộc tài khoản đăng nhập lại để giao diện nhận preset mới ngay, thay vì
    # tiếp tục hiện các nút cũ rồi chỉ bị backend từ chối.
    staff.session_id = new_session_id()
    db.commit()
    db.refresh(staff)
    result = _to_out(staff)
    log_system_action(
        db,
        current_user.id,
        "UPDATE_STAFF_ROLE",
        f"Đổi vai trò nhân viên '{staff.username}': {old_role} -> {data.staff_role}",
    )
    return result
