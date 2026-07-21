"""Đăng ký, xác minh email, quên/đổi mật khẩu, đăng nhập."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.config import OTP_EXPIRE_MINUTES, log_to_file
from ..core.security import (
    create_access_token,
    generate_otp,
    hash_password,
    is_strong_password,
    new_session_id,
    verify_password,
)
from ..schemas.auth import (
    ChangePasswordRequest,
    EmailVerify,
    ForgotPasswordRequest,
    ForgotPasswordReset,
    Login,
    ResendCodeRequest,
    UserCreate,
)
from . import email_service
from .log_service import log_system_action

PASSWORD_POLICY_MSG = "Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số"


def _otp_expiry() -> datetime:
    return datetime.utcnow() + timedelta(minutes=OTP_EXPIRE_MINUTES)


def register(db: Session, user: UserCreate) -> Dict[str, str]:
    if not is_strong_password(user.password):
        raise HTTPException(status_code=400, detail=PASSWORD_POLICY_MSG)

    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại")

    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email này đã được đăng ký tài khoản khác")

    otp_code = generate_otp()
    db_user = models.User(
        username=user.username,
        hashed_password=hash_password(user.password),
        role="SELLER",  # Ép cứng SELLER, không tin role từ client (tránh tự nâng quyền admin)
        email=user.email,
        is_verified=False,
        verification_code=otp_code,
        verification_code_expires=_otp_expiry(),
    )
    db.add(db_user)
    db.commit()

    email_service.send_otp_email(user.email, otp_code, "F-Selling: Xác minh tài khoản mới")
    return {"msg": "Đăng ký thành công. Vui lòng kiểm tra email để nhận mã kích hoạt tài khoản."}


def verify_email(db: Session, data: EmailVerify) -> Dict[str, str]:
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản với email này")
    if user.is_verified:
        return {"msg": "Tài khoản đã được xác minh trước đó."}

    if not user.verification_code or user.verification_code != data.code:
        raise HTTPException(status_code=400, detail="Mã xác thực không hợp lệ")

    if user.verification_code_expires and datetime.utcnow() > user.verification_code_expires:
        # Xóa tài khoản hết hạn để người dùng có thể đăng ký lại
        print(f"[VERIFY] Verification expired for user {user.username}. Deleting account.")
        db.delete(user)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Mã xác thực đã hết hạn. Vui lòng đăng ký lại để nhận mã mới.",
        )

    user.is_verified = True
    user.verification_code = None
    user.verification_code_expires = None
    db.commit()
    return {"msg": "Xác minh tài khoản thành công! Bây giờ bạn đã có thể đăng nhập."}


def resend_code(db: Session, data: ResendCodeRequest) -> Dict[str, str]:
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản với email này")
    if user.is_verified:
        raise HTTPException(status_code=400, detail="Tài khoản đã được xác minh")

    otp_code = generate_otp()
    user.verification_code = otp_code
    user.verification_code_expires = _otp_expiry()
    db.commit()

    email_service.send_otp_email(user.email, otp_code, "F-Selling: Gửi lại mã xác minh tài khoản")
    return {"msg": "Đã gửi lại mã xác minh mới vào email của bạn."}


def forgot_password_request(db: Session, data: ForgotPasswordRequest) -> Dict[str, str]:
    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản liên kết với email này")

    otp_code = generate_otp()
    user.verification_code = otp_code
    user.verification_code_expires = _otp_expiry()
    db.commit()

    email_service.send_otp_email(user.email, otp_code, "F-Selling: Mã khôi phục mật khẩu")
    return {"msg": "Đã gửi mã xác minh khôi phục mật khẩu vào email của bạn."}


def forgot_password_reset(db: Session, data: ForgotPasswordReset) -> Dict[str, str]:
    if not is_strong_password(data.new_password):
        raise HTTPException(status_code=400, detail=PASSWORD_POLICY_MSG)

    user = db.query(models.User).filter(models.User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản với email này")

    if not user.verification_code or user.verification_code != data.code:
        raise HTTPException(status_code=400, detail="Mã xác nhận không hợp lệ")

    if user.verification_code_expires and datetime.utcnow() > user.verification_code_expires:
        raise HTTPException(status_code=400, detail="Mã xác nhận đã hết hạn")

    user.hashed_password = hash_password(data.new_password)
    user.verification_code = None
    user.verification_code_expires = None
    user.session_id = new_session_id()  # Logout các nơi khác
    db.commit()
    return {"msg": "Đặt lại mật khẩu thành công! Vui lòng đăng nhập lại."}


def change_password(
    db: Session, current_user: models.User, data: ChangePasswordRequest
) -> Dict[str, str]:
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác")

    if not is_strong_password(data.new_password):
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu mới phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số",
        )

    current_user.hashed_password = hash_password(data.new_password)
    new_sid = new_session_id()
    current_user.session_id = new_sid
    db.commit()

    token = create_access_token(current_user.username, new_sid)
    log_system_action(
        db, current_user.id, "CHANGE_PASSWORD", f"User {current_user.username} changed password"
    )
    return {"access_token": token, "token_type": "bearer", "role": current_user.role}


def login(db: Session, user: Login) -> Dict[str, str]:
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không chính xác")

    if db_user.email and not db_user.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản chưa được xác minh email. Vui lòng xác minh trước khi đăng nhập.",
        )

    new_sid = new_session_id()
    db_user.session_id = new_sid
    db.commit()

    token = create_access_token(db_user.username, new_sid)
    log_system_action(db, db_user.id, "LOGIN", f"User {db_user.username} logged in")
    log_to_file(f"Login success: user='{user.username}' (ID={db_user.id})")
    return {"access_token": token, "token_type": "bearer", "role": db_user.role}
