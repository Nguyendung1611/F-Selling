"""API xem/mua gói Pro và thao tác gói của ADMIN.

Webhook SUB nằm trong ``routers/webhooks.py`` để dùng chung ranh giới xác thực
secret ngân hàng; không khai lại ở đây.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db, require_admin, require_shop_access
from ..schemas.subscription import (
    SubscriptionCheckoutCreate,
    SubscriptionGiftCreate,
    SubscriptionGiftRevoke,
)
from ..services import subscription_service

router = APIRouter(tags=["subscriptions"])


@router.get("/api/subscriptions/{shop_id}")
def get_subscription(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    require_shop_access(db, shop_id, current_user)
    return subscription_service.subscription_overview(
        db, shop_id, current_user
    )


@router.post("/api/subscriptions/{shop_id}/checkouts")
def create_subscription_checkout(
    shop_id: int,
    data: SubscriptionCheckoutCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return subscription_service.create_checkout(
        db, current_user, shop_id, data
    )


@router.get("/api/admin/subscriptions")
def get_admin_subscriptions(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    return subscription_service.admin_subscription_list(db)


@router.post("/api/admin/subscriptions/{shop_id}/gifts")
def create_admin_subscription_gift(
    shop_id: int,
    data: SubscriptionGiftCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    return subscription_service.create_admin_gift(
        db, admin, shop_id, data
    )


@router.post("/api/admin/subscriptions/grants/{grant_id}/revoke")
def revoke_admin_subscription_gift(
    grant_id: int,
    data: SubscriptionGiftRevoke,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
):
    return subscription_service.revoke_admin_gift(
        db, admin, grant_id, data
    )


@router.get("/api/admin/subscription-payments")
def get_admin_subscription_payments(
    needs_review: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_admin),
):
    return subscription_service.list_subscription_payments(
        db, needs_review=needs_review, limit=limit
    )


__all__ = ["router"]
