"""Scheduler dọn tài khoản chưa xác minh đã hết hạn."""
from datetime import datetime, timedelta

from conftest import SELLER_PASSWORD

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services.maintenance_service import cleanup_expired_unverified_users


def _tao_user_chua_xac_minh(client, username, expires_delta):
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": SELLER_PASSWORD,
            "email": f"{username}@example.com",
        },
    )
    session = SessionLocal()
    try:
        user = session.query(models.User).filter(models.User.username == username).first()
        user.verification_code_expires = datetime.utcnow() + expires_delta
        session.commit()
    finally:
        session.close()


def _ton_tai(username):
    session = SessionLocal()
    try:
        return (
            session.query(models.User).filter(models.User.username == username).first() is not None
        )
    finally:
        session.close()


def test_xoa_user_chua_xac_minh_da_het_han(client):
    _tao_user_chua_xac_minh(client, "hethan_user", timedelta(minutes=-10))
    cleanup_expired_unverified_users()
    assert not _ton_tai("hethan_user")


def test_giu_lai_user_chua_het_han(client):
    _tao_user_chua_xac_minh(client, "conhan_user", timedelta(minutes=10))
    cleanup_expired_unverified_users()
    assert _ton_tai("conhan_user")


def test_khong_xoa_user_da_xac_minh(client):
    from conftest import register_seller

    username = register_seller(client)
    cleanup_expired_unverified_users()
    assert _ton_tai(username)
