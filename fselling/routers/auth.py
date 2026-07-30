"""Router xác thực. Chỉ xử lý HTTP, nghiệp vụ nằm trong auth_service."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.auth import (
    ChangePasswordRequest,
    EmailVerify,
    ForgotPasswordRequest,
    ForgotPasswordReset,
    Login,
    ResendCodeRequest,
    Token,
    UserCreate,
)
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    return auth_service.register(db, user)


@router.post("/verify-email")
def verify_email(data: EmailVerify, db: Session = Depends(get_db)):
    return auth_service.verify_email(db, data)


@router.post("/resend-code")
def resend_code(data: ResendCodeRequest, db: Session = Depends(get_db)):
    return auth_service.resend_code(db, data)


@router.post("/forgot-password-request")
def forgot_password_request(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    return auth_service.forgot_password_request(db, data)


@router.post("/forgot-password-reset")
def forgot_password_reset(data: ForgotPasswordReset, db: Session = Depends(get_db)):
    return auth_service.forgot_password_reset(db, data)


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return auth_service.change_password(db, current_user, data)


@router.post("/login", response_model=Token, response_model_exclude_none=True)
def login(user: Login, db: Session = Depends(get_db)):
    return auth_service.login(db, user)


@router.get("/session-check")
def session_check(current_user: models.User = Depends(get_current_user)):
    return {"status": "ok"}
