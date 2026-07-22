"""FastAPI dependencies dùng chung: DB session, xác thực, phân quyền."""
from __future__ import annotations

from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models
from .core.config import log_to_file
from .core.database import SessionLocal
from .core.security import decode_access_token, extract_bearer_token


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    # Chỉ chấp nhận token qua Authorization header, KHÔNG nhận qua query string
    # để tránh lộ token qua browser history / server log / screenshot.
    token = extract_bearer_token(authorization)
    if not token:
        log_to_file("Auth failed: Token missing")
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        sid = payload.get("sid")
        if username is None:
            log_to_file("Auth failed: sub is None")
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.PyJWTError as e:
        log_to_file(f"Auth failed: PyJWTError: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        log_to_file(f"Auth failed: User not found: '{username}'")
        raise HTTPException(status_code=401, detail="User not found")

    # Kiểm tra Session ID để đảm bảo đăng xuất thiết bị cũ
    if user.session_id and sid != user.session_id:
        log_to_file(f"Auth failed: session_id mismatch for user '{username}'")
        raise HTTPException(
            status_code=401,
            detail="Tài khoản đã được đăng nhập ở thiết bị khác. Vui lòng đăng nhập lại.",
        )

    log_to_file(f"Auth success: user='{username}' (ID={user.id})")
    return user


def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


def has_shop_operator_access(shop: models.Shop, current_user: models.User) -> bool:
    """Ai được VẬN HÀNH shop này (bán hàng, quản lý SP/danh mục/voucher/kho,
    xem báo cáo): ADMIN, chủ shop, hoặc nhân viên (STAFF) được gán vào shop đó.

    KHÔNG bao gồm thao tác quản trị (sửa/xóa shop, quản lý nhân viên) - những
    thao tác đó vẫn dùng require_own_shop (chỉ đúng chủ shop)."""
    if current_user.role == "ADMIN":
        return True
    if shop.owner_id == current_user.id:
        return True
    if current_user.role == "STAFF" and current_user.staff_shop_id == shop.id:
        return True
    return False


def require_shop_access(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    """Đảm bảo current_user được vận hành shop (chủ shop, ADMIN, hoặc nhân viên
    được gán vào shop). Nếu không -> 403/404."""
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Không tìm thấy cửa hàng")
    if not has_shop_operator_access(shop, current_user):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập cửa hàng này")
    return shop


def require_own_shop(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    """Một số endpoint cũ chỉ cho phép ĐÚNG chủ shop (ADMIN cũng không được),
    trả 404 khi không khớp. Giữ nguyên hành vi đó."""
    shop = (
        db.query(models.Shop)
        .filter(models.Shop.id == shop_id, models.Shop.owner_id == current_user.id)
        .first()
    )
    if not shop:
        raise HTTPException(status_code=404, detail="Không tìm thấy cửa hàng")
    return shop
