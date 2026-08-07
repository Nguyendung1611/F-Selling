"""Nghiệp vụ Free/Pro theo shop, thanh toán và quà tặng của ADMIN.

Mọi mốc giờ lưu UTC-naive giống phần còn lại của dự án. Trạng thái gói được suy
ra tại lúc đọc, không có scheduler đổi ACTIVE -> FREE nên restart/auto-stop cũng
không làm hạn gói sai.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import secrets
import zoneinfo
from typing import Any, Dict, Iterable, Optional
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..schemas.subscription import (
    SubscriptionCheckoutCreate,
    SubscriptionGiftCreate,
    SubscriptionGiftRevoke,
)
from . import payment_service

PLAN_FREE = "FREE"
PLAN_PRO = "PRO"

CYCLE_MONTHLY = "MONTHLY"
CYCLE_YEARLY = "YEARLY"
PRICE_VND = {CYCLE_MONTHLY: 99_000, CYCLE_YEARLY: 831_600}
DURATION_DAYS = {CYCLE_MONTHLY: 30, CYCLE_YEARLY: 365}
TRIAL_DAYS = 30
PAID_GRACE_DAYS = 7
CHECKOUT_HOURS = 24

CHECKOUT_PENDING = "PENDING"
CHECKOUT_UNDERPAID = "UNDERPAID"
CHECKOUT_PAID = "PAID"
CHECKOUT_OVERPAID = "OVERPAID"
CHECKOUT_EXPIRED = "EXPIRED"

REVIEW_UNDERPAID = "UNDERPAID"
REVIEW_OVERPAID = "OVERPAID"
REVIEW_NO_REFERENCE = "NO_REFERENCE"
REVIEW_UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
REVIEW_EXPIRED_CHECKOUT = "EXPIRED_CHECKOUT"
REVIEW_ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"

_VN_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
_UTC = datetime.timezone.utc


def utcnow() -> datetime.datetime:
    """Tách thành hàm để test biên thời gian không phải sửa đồng hồ hệ thống."""
    return datetime.datetime.utcnow()


def _fingerprint(payload: Dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_audit(
    db: Session,
    user_id: Optional[int],
    action: str,
    details: str,
    *,
    shop_id: Optional[int] = None,
) -> None:
    """Thêm audit vào transaction hiện tại; tuyệt đối không commit riêng."""
    db.add(
        models.SystemLog(
            user_id=user_id,
            shop_id=shop_id,
            action=action,
            details=(details or "")[:2000],
        )
    )


def create_trial_for_shop(
    db: Session,
    shop_id: int,
    *,
    now: Optional[datetime.datetime] = None,
) -> models.ShopSubscription:
    """Tạo trial đúng lúc tạo shop, không tự commit transaction của caller."""
    existing = (
        db.query(models.ShopSubscription)
        .filter(models.ShopSubscription.shop_id == shop_id)
        .first()
    )
    if existing is not None:
        return existing
    start = now or utcnow()
    subscription = models.ShopSubscription(
        shop_id=shop_id,
        trial_started_at=start,
        trial_ends_at=start + datetime.timedelta(days=TRIAL_DAYS),
        updated_at=start,
    )
    db.add(subscription)
    return subscription


def _active_grants(
    db: Session, shop_id: int, now: datetime.datetime
) -> list[models.SubscriptionGrant]:
    return (
        db.query(models.SubscriptionGrant)
        .filter(
            models.SubscriptionGrant.shop_id == shop_id,
            models.SubscriptionGrant.revoked_at.is_(None),
            models.SubscriptionGrant.starts_at <= now,
            models.SubscriptionGrant.ends_at > now,
        )
        .order_by(
            models.SubscriptionGrant.ends_at.desc(),
            models.SubscriptionGrant.id.desc(),
        )
        .all()
    )


def _active_grant_until(
    db: Session, shop_id: int, now: datetime.datetime
) -> Optional[datetime.datetime]:
    grants = _active_grants(db, shop_id, now)
    return grants[0].ends_at if grants else None


def _paid_terms(
    db: Session, shop_id: int
) -> list[models.SubscriptionCheckout]:
    """Các kỳ đã trả có segment riêng, theo đúng thứ tự chạy."""
    return (
        db.query(models.SubscriptionCheckout)
        .filter(
            models.SubscriptionCheckout.shop_id == shop_id,
            models.SubscriptionCheckout.activated_at.is_not(None),
            models.SubscriptionCheckout.entitlement_starts_at.is_not(None),
            models.SubscriptionCheckout.entitlement_ends_at.is_not(None),
        )
        .order_by(
            models.SubscriptionCheckout.entitlement_starts_at.asc(),
            models.SubscriptionCheckout.activated_at.asc(),
            models.SubscriptionCheckout.id.asc(),
        )
        .all()
    )


_ACCESS_SOURCE_PRIORITY = {
    "GRACE": 1,
    "TRIAL": 2,
    "GIFT": 3,
    "PAID": 4,
}


def _continuous_access(
    intervals: list[tuple[datetime.datetime, datetime.datetime, str]],
    now: datetime.datetime,
) -> tuple[Optional[datetime.datetime], Optional[str], Optional[str]]:
    """Nối các đoạn phủ liên tục từ ``now`` và trả nguồn hiện tại/cuối chuỗi."""
    current = [item for item in intervals if item[0] <= now < item[1]]
    if not current:
        return None, None, None

    def _strongest_end(item):
        return (item[1], _ACCESS_SOURCE_PRIORITY[item[2]])

    first = max(current, key=_strongest_end)
    cursor = first[1]
    current_source = first[2]
    access_source = current_source
    while True:
        extenders = [
            item
            for item in intervals
            if item[0] <= cursor and item[1] > cursor
        ]
        if not extenders:
            break
        extension = max(extenders, key=_strongest_end)
        cursor = extension[1]
        access_source = extension[2]
    return cursor, current_source, access_source


def _gift_expires_on(grant_until: Optional[datetime.datetime]) -> Optional[datetime.date]:
    """Đổi mốc kết thúc độc quyền UTC thành ngày cuối cùng được dùng ở Việt Nam."""
    if grant_until is None:
        return None
    local_exclusive_end = grant_until.replace(tzinfo=_UTC).astimezone(_VN_TZ)
    return local_exclusive_end.date() - datetime.timedelta(days=1)


def get_subscription_state(
    db: Session,
    shop_id: int,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Đọc trạng thái gói mà không ghi DB/commit ngoài ý muốn."""
    moment = now or utcnow()
    subscription = (
        db.query(models.ShopSubscription)
        .filter(models.ShopSubscription.shop_id == shop_id)
        .first()
    )
    if subscription is None:
        return {
            "shop_id": shop_id,
            "plan": PLAN_FREE,
            "phase": PLAN_FREE,
            "can_use_pro": False,
            "trial_started_at": None,
            "trial_ends_at": None,
            "paid_until": None,
            "paid_grace_until": None,
            "active_grant_until": None,
            "active_grant_expires_on": None,
            "access_until": None,
            "access_source": None,
            "current_access_source": None,
            "server_now": moment,
        }

    terms = _paid_terms(db, shop_id)
    paid_until = (
        max(term.entitlement_ends_at for term in terms)
        if terms
        else subscription.paid_until
    )
    started_paid_ends = [
        term.entitlement_ends_at
        for term in terms
        if term.entitlement_starts_at <= moment
    ]
    # DB legacy không có checkout segment vẫn được đọc an toàn. Khi đã có ít
    # nhất một segment, paid_until aggregate chỉ còn là cache và không được dùng
    # để bịa một đoạn PAID kéo xuyên qua quà tặng.
    legacy_paid = not terms and subscription.paid_until is not None
    if legacy_paid:
        started_paid_ends.append(subscription.paid_until)
    latest_started_paid_end = (
        max(started_paid_ends) if started_paid_ends else None
    )
    paid_grace_until = (
        latest_started_paid_end + datetime.timedelta(days=PAID_GRACE_DAYS)
        if latest_started_paid_end is not None
        else None
    )
    paid_grace = bool(
        latest_started_paid_end is not None
        and paid_grace_until is not None
        and latest_started_paid_end <= moment < paid_grace_until
    )

    intervals: list[tuple[datetime.datetime, datetime.datetime, str]] = []
    if subscription.trial_started_at <= moment < subscription.trial_ends_at:
        intervals.append(
            (subscription.trial_started_at, subscription.trial_ends_at, "TRIAL")
        )
    grants = _active_grants(db, shop_id, moment)
    intervals.extend((grant.starts_at, grant.ends_at, "GIFT") for grant in grants)
    intervals.extend(
        (
            term.entitlement_starts_at,
            term.entitlement_ends_at,
            "PAID",
        )
        for term in terms
        if term.entitlement_ends_at > moment
    )
    if legacy_paid and subscription.paid_until > moment:
        intervals.append((moment, subscription.paid_until, "PAID"))
    if paid_grace and paid_grace_until is not None:
        intervals.append(
            (latest_started_paid_end, paid_grace_until, "GRACE")
        )

    access_until, current_source, access_source = _continuous_access(
        intervals, moment
    )
    can_use_pro = access_until is not None
    phase = access_source or PLAN_FREE
    grant_until = grants[0].ends_at if grants else None

    return {
        "shop_id": shop_id,
        "plan": PLAN_PRO if can_use_pro else PLAN_FREE,
        "phase": phase,
        "can_use_pro": can_use_pro,
        "trial_started_at": subscription.trial_started_at,
        "trial_ends_at": subscription.trial_ends_at,
        "paid_until": paid_until,
        "paid_grace_until": paid_grace_until,
        "active_grant_until": grant_until,
        "active_grant_expires_on": _gift_expires_on(grant_until),
        "access_until": access_until,
        # phase/access_source là nguồn tạo ra mốc access_until. Field current
        # cho biết đoạn đang phủ đúng thời điểm request nếu UI cần diễn đạt sâu.
        "access_source": access_source,
        "current_access_source": current_source,
        "server_now": moment,
    }


def require_pro(
    db: Session,
    shop_id: int,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Hàng rào backend cho tính năng Pro; không bao giờ nhét plan vào JWT."""
    state = get_subscription_state(db, shop_id, now=now)
    if not state["can_use_pro"]:
        raise HTTPException(
            status_code=402,
            detail=tr(
                "Tính năng này cần gói Pro. Bạn có thể mở tab Gói cước để gia hạn."
            ),
        )
    return state


def _require_shop_owner(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if shop is None:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy cửa hàng"))
    if current_user.role != "SELLER" or shop.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail=tr("Chỉ chủ cửa hàng mới quản lý được gói cước"),
        )
    return shop


def _platform_bank() -> Dict[str, str]:
    return {
        "bank_code": (os.getenv("SUBSCRIPTION_BANK_CODE") or "").strip().upper(),
        "account_no": (os.getenv("SUBSCRIPTION_BANK_ACCOUNT_NO") or "").strip(),
        "account_name": (os.getenv("SUBSCRIPTION_BANK_ACCOUNT_NAME") or "").strip(),
    }


def _require_platform_bank() -> Dict[str, str]:
    bank = _platform_bank()
    if not all(bank.values()):
        raise HTTPException(
            status_code=503,
            detail=tr("Thanh toán gói Pro chưa được cấu hình tài khoản nhận tiền"),
        )
    return bank


def _qr_url(bank: Dict[str, str], amount: int, reference_code: str) -> str:
    query = urlencode(
        {
            "amount": amount,
            "addInfo": reference_code,
            "accountName": bank["account_name"],
        }
    )
    bank_code = quote(bank["bank_code"], safe="")
    account_no = quote(bank["account_no"], safe="")
    return (
        f"https://img.vietqr.io/image/{bank_code}-{account_no}-compact2.png?{query}"
    )


def _serialize_checkout(
    checkout: models.SubscriptionCheckout,
    *,
    bank: Optional[Dict[str, str]] = None,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    moment = now or utcnow()
    status = checkout.status
    if (
        status in {CHECKOUT_PENDING, CHECKOUT_UNDERPAID}
        and checkout.activated_at is None
        and moment >= checkout.expires_at
    ):
        status = CHECKOUT_EXPIRED
    remaining_vnd = max(
        checkout.amount_due_vnd - checkout.received_amount_vnd, 0
    )
    result = {
        "id": checkout.id,
        "shop_id": checkout.shop_id,
        # Chỉ xuất hiện trong contract billing của owner/Admin. UI dùng khóa này
        # để retry đúng lần bấm, không nhầm checkout PAID/EXPIRED cũ là mã mới.
        "operation_id": checkout.operation_id,
        "reference_code": checkout.reference_code,
        "cycle": checkout.cycle,
        "amount_due_vnd": checkout.amount_due_vnd,
        "duration_days": checkout.duration_days,
        "status": status,
        "received_amount_vnd": checkout.received_amount_vnd,
        "refund_due_amount_vnd": checkout.refund_due_amount_vnd,
        # Alias ngắn là contract giao diện; giữ tên dài để API tự mô tả rõ và
        # không buộc code tích hợp nội bộ đổi theo UI.
        "received_vnd": checkout.received_amount_vnd,
        "refund_due_vnd": checkout.refund_due_amount_vnd,
        "remaining_vnd": remaining_vnd,
        "created_at": checkout.created_at,
        "expires_at": checkout.expires_at,
        "activated_at": checkout.activated_at,
        "entitlement_starts_at": checkout.entitlement_starts_at,
        "entitlement_ends_at": checkout.entitlement_ends_at,
        "paid_until_after": checkout.paid_until_after,
    }
    if bank is not None:
        result.update(
            {
                "bank_code": bank["bank_code"],
                "bank_account_no": bank["account_no"],
                "bank_account_name": bank["account_name"],
            }
        )
        # Sau khi trả thiếu, QR phải mang đúng số CÒN THIẾU; dùng lại giá gốc
        # sẽ biến lần quét thứ hai thành chuyển thừa. Mã đã đủ tiền/hết hạn
        # không còn QR để tránh người dùng vô tình chuyển thêm vào checkout cũ.
        if status in {CHECKOUT_PENDING, CHECKOUT_UNDERPAID} and remaining_vnd > 0:
            result["qr_url"] = _qr_url(
                bank, remaining_vnd, checkout.reference_code
            )
    return result


def _same_operation(existing_fingerprint: str, fingerprint: str) -> None:
    if existing_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Mã thao tác đã được dùng với nội dung khác. Hãy tải lại màn hình."
            ),
        )


def create_checkout(
    db: Session,
    current_user: models.User,
    shop_id: int,
    data: SubscriptionCheckoutCreate,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    _require_shop_owner(db, shop_id, current_user)
    bank = _require_platform_bank()
    moment = now or utcnow()
    amount = PRICE_VND[data.cycle]
    duration = DURATION_DAYS[data.cycle]
    fingerprint = _fingerprint(
        {
            "shop_id": shop_id,
            "cycle": data.cycle,
            "amount_due_vnd": amount,
            "duration_days": duration,
        }
    )

    existing = (
        db.query(models.SubscriptionCheckout)
        .filter(models.SubscriptionCheckout.operation_id == data.operation_id)
        .first()
    )
    if existing is not None:
        _same_operation(existing.operation_fingerprint, fingerprint)
        return _serialize_checkout(existing, bank=bank, now=moment)

    for _attempt in range(5):
        _ensure_subscription_aggregate(db, shop_id, moment)
        _lock_subscription_aggregate(db, shop_id)

        # Một request cùng operation_id có thể vừa thắng race trong lúc request
        # này chờ lock. Đọc lại sau lock để retry trả đúng checkout cũ.
        concurrent_operation = (
            db.query(models.SubscriptionCheckout)
            .filter(models.SubscriptionCheckout.operation_id == data.operation_id)
            .first()
        )
        if concurrent_operation is not None:
            _same_operation(
                concurrent_operation.operation_fingerprint, fingerprint
            )
            result = _serialize_checkout(
                concurrent_operation, bank=bank, now=moment
            )
            db.rollback()
            return result

        # Status lưu ở DB phải hết hiệu lực trước khi kiểm unique partial; chỉ
        # đổi các QR thật sự quá 24 giờ, không đụng checkout đã kích hoạt.
        db.query(models.SubscriptionCheckout).filter(
            models.SubscriptionCheckout.shop_id == shop_id,
            models.SubscriptionCheckout.activated_at.is_(None),
            models.SubscriptionCheckout.status.in_(
                {CHECKOUT_PENDING, CHECKOUT_UNDERPAID}
            ),
            models.SubscriptionCheckout.expires_at <= moment,
        ).update(
            {models.SubscriptionCheckout.status: CHECKOUT_EXPIRED},
            synchronize_session=False,
        )
        open_checkout = (
            db.query(models.SubscriptionCheckout)
            .filter(
                models.SubscriptionCheckout.shop_id == shop_id,
                models.SubscriptionCheckout.activated_at.is_(None),
                models.SubscriptionCheckout.status.in_(
                    {CHECKOUT_PENDING, CHECKOUT_UNDERPAID}
                ),
                models.SubscriptionCheckout.expires_at > moment,
            )
            .order_by(models.SubscriptionCheckout.created_at.desc())
            .first()
        )
        if open_checkout is not None:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=tr(
                    "Cửa hàng đang có một mã thanh toán còn hiệu lực. "
                    "Hãy dùng mã đó hoặc chờ mã hết hạn."
                ),
            )

        reference_code = "SUB" + secrets.token_hex(6).upper()
        checkout = models.SubscriptionCheckout(
            shop_id=shop_id,
            reference_code=reference_code,
            cycle=data.cycle,
            amount_due_vnd=amount,
            duration_days=duration,
            status=CHECKOUT_PENDING,
            received_amount_vnd=0,
            refund_due_amount_vnd=0,
            operation_id=data.operation_id,
            operation_fingerprint=fingerprint,
            created_by_user_id=current_user.id,
            created_at=moment,
            expires_at=moment + datetime.timedelta(hours=CHECKOUT_HOURS),
        )
        db.add(checkout)
        _add_audit(
            db,
            current_user.id,
            "SUBSCRIPTION_CHECKOUT_CREATED",
            f"Shop #{shop_id}: tạo mã {checkout.reference_code}, "
            f"{data.cycle}, {amount:,}đ/{duration} ngày",
            shop_id=shop_id,
        )
        try:
            db.commit()
            db.refresh(checkout)
            return _serialize_checkout(checkout, bank=bank, now=moment)
        except IntegrityError:
            db.rollback()
            concurrent = (
                db.query(models.SubscriptionCheckout)
                .filter(
                    models.SubscriptionCheckout.operation_id == data.operation_id
                )
                .first()
            )
            if concurrent is not None:
                _same_operation(concurrent.operation_fingerprint, fingerprint)
                return _serialize_checkout(concurrent, bank=bank, now=moment)
            concurrent_open = (
                db.query(models.SubscriptionCheckout.id)
                .filter(
                    models.SubscriptionCheckout.shop_id == shop_id,
                    models.SubscriptionCheckout.status.in_(
                        {CHECKOUT_PENDING, CHECKOUT_UNDERPAID}
                    ),
                    models.SubscriptionCheckout.expires_at > moment,
                )
                .first()
            )
            if concurrent_open is not None:
                raise HTTPException(
                    status_code=409,
                    detail=tr(
                        "Cửa hàng vừa tạo một mã thanh toán ở phiên khác. "
                        "Hãy tải lại để dùng đúng mã đó."
                    ),
                )
            # Chỉ retry khi đúng mã SUB ngẫu nhiên đụng nhau. IntegrityError
            # khác là lỗi DB/lập trình và phải nổi lên, không được nuốt thành
            # thông báo chung rồi che mất nguyên nhân.
            reference_collision = (
                db.query(models.SubscriptionCheckout.id)
                .filter(
                    models.SubscriptionCheckout.reference_code
                    == reference_code
                )
                .first()
            )
            if reference_collision:
                continue
            raise
    raise HTTPException(
        status_code=503,
        detail=tr("Chưa tạo được mã thanh toán. Vui lòng thử lại"),
    )


def subscription_overview(
    db: Session,
    shop_id: int,
    current_user: models.User,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    moment = now or utcnow()
    state = get_subscription_state(db, shop_id, now=moment)
    latest = (
        db.query(models.SubscriptionCheckout)
        .filter(models.SubscriptionCheckout.shop_id == shop_id)
        .order_by(models.SubscriptionCheckout.created_at.desc(), models.SubscriptionCheckout.id.desc())
        .first()
    )
    owner_id = (
        db.query(models.Shop.owner_id).filter(models.Shop.id == shop_id).scalar()
    )
    can_see_billing = current_user.role == "ADMIN" or current_user.id == owner_id
    bank = _platform_bank()
    checkout_bank = bank if can_see_billing and all(bank.values()) else None
    current_checkout = (
        _serialize_checkout(latest, bank=checkout_bank, now=moment)
        if latest is not None and can_see_billing
        else None
    )
    state.update(
        {
            # Contract giao diện gói cước.
            "status": state["phase"],
            "pro_until": state["access_until"],
            "grace_until": state["paid_grace_until"],
            "prices": {
                "monthly_vnd": PRICE_VND[CYCLE_MONTHLY],
                "yearly_vnd": PRICE_VND[CYCLE_YEARLY],
            },
            "monthly_price_vnd": PRICE_VND[CYCLE_MONTHLY],
            "monthly_days": DURATION_DAYS[CYCLE_MONTHLY],
            "yearly_price_vnd": PRICE_VND[CYCLE_YEARLY],
            "yearly_days": DURATION_DAYS[CYCLE_YEARLY],
            "paid_grace_days": PAID_GRACE_DAYS,
            "checkout_hours": CHECKOUT_HOURS,
            # STAFF cần biết shop còn Pro hay không nhưng không cần xem tài khoản
            # ngân hàng/lịch sử thanh toán của chủ shop.
            "current_checkout": current_checkout,
            "latest_checkout": current_checkout,
        }
    )
    return state


def _gift_end_utc(expires_on: datetime.date) -> datetime.datetime:
    """00:00 ngày kế tiếp giờ VN = độc quyền sau 23:59:59 ngày đã chọn."""
    try:
        next_day = expires_on + datetime.timedelta(days=1)
    except OverflowError as exc:
        raise HTTPException(
            status_code=400,
            detail=tr("Ngày hết hạn gói tặng không hợp lệ"),
        ) from exc
    local_end = datetime.datetime.combine(
        next_day, datetime.time.min, tzinfo=_VN_TZ
    )
    return local_end.astimezone(_UTC).replace(tzinfo=None)


def _serialize_grant(grant: models.SubscriptionGrant) -> Dict[str, Any]:
    return {
        "id": grant.id,
        "shop_id": grant.shop_id,
        "starts_at": grant.starts_at,
        "ends_at": grant.ends_at,
        "expires_on": grant.expires_on,
        "reason": grant.reason,
        "granted_by_user_id": grant.granted_by_user_id,
        "created_at": grant.created_at,
        "revoked_at": grant.revoked_at,
        "revoked_by_user_id": grant.revoked_by_user_id,
        "revoke_reason": grant.revoke_reason,
    }


def create_admin_gift(
    db: Session,
    admin: models.User,
    shop_id: int,
    data: SubscriptionGiftCreate,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if shop is None:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy cửa hàng"))
    moment = now or utcnow()
    fingerprint = _fingerprint(
        {
            "shop_id": shop_id,
            "expires_on": data.expires_on.isoformat(),
            "reason": data.reason,
        }
    )
    existing = (
        db.query(models.SubscriptionGrant)
        .filter(models.SubscriptionGrant.operation_id == data.operation_id)
        .first()
    )
    if existing is not None:
        _same_operation(existing.operation_fingerprint, fingerprint)
        return {
            "grant": _serialize_grant(existing),
            "subscription": get_subscription_state(db, shop_id, now=moment),
        }

    # Idempotency phải được xét trước validation phụ thuộc thời gian. Một thao
    # tác đã thành công vẫn phải trả lại đúng grant cũ khi Admin retry sau ngày
    # hết hạn, thay vì đổi thành lỗi 400 chỉ vì đồng hồ đã đi tiếp.
    ends_at = _gift_end_utc(data.expires_on)
    if ends_at <= moment:
        raise HTTPException(
            status_code=400,
            detail=tr("Ngày hết hạn gói tặng phải nằm trong tương lai"),
        )

    grant = models.SubscriptionGrant(
        shop_id=shop_id,
        starts_at=moment,
        ends_at=ends_at,
        expires_on=data.expires_on.isoformat(),
        reason=data.reason,
        operation_id=data.operation_id,
        operation_fingerprint=fingerprint,
        granted_by_user_id=admin.id,
        created_at=moment,
    )
    db.add(grant)
    _add_audit(
        db,
        admin.id,
        "SUBSCRIPTION_ADMIN_GIFT",
        f"Shop #{shop_id} '{shop.name}': tặng Pro đến hết "
        f"{data.expires_on.isoformat()}; lý do: {data.reason}",
        shop_id=shop_id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(models.SubscriptionGrant)
            .filter(models.SubscriptionGrant.operation_id == data.operation_id)
            .first()
        )
        if concurrent is None:
            raise
        _same_operation(concurrent.operation_fingerprint, fingerprint)
        grant = concurrent
    db.refresh(grant)
    return {
        "grant": _serialize_grant(grant),
        "subscription": get_subscription_state(db, shop_id, now=moment),
    }


def revoke_admin_gift(
    db: Session,
    admin: models.User,
    grant_id: int,
    data: SubscriptionGiftRevoke,
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    moment = now or utcnow()
    # SQLite không có SELECT FOR UPDATE: no-op UPDATE lấy write lock trước khi
    # kiểm revoked_at, để hai ADMIN không cùng thu hồi một món quà hai lần.
    locked = db.execute(
        text("UPDATE subscription_grants SET id = id WHERE id = :grant_id"),
        {"grant_id": grant_id},
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy gói Pro được tặng"))
    grant = (
        db.query(models.SubscriptionGrant)
        .filter(models.SubscriptionGrant.id == grant_id)
        .first()
    )
    fingerprint = _fingerprint(
        {"grant_id": grant_id, "reason": data.reason}
    )
    if grant.revoked_at is not None:
        if grant.revoke_operation_id == data.operation_id:
            _same_operation(grant.revoke_fingerprint or "", fingerprint)
            db.rollback()
            return {
                "grant": _serialize_grant(grant),
                "subscription": get_subscription_state(
                    db, grant.shop_id, now=moment
                ),
            }
        db.rollback()
        raise HTTPException(status_code=409, detail=tr("Gói tặng này đã được thu hồi"))

    collision = (
        db.query(models.SubscriptionGrant.id)
        .filter(
            models.SubscriptionGrant.revoke_operation_id == data.operation_id,
            models.SubscriptionGrant.id != grant_id,
        )
        .first()
    )
    if collision:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác thu hồi đã được dùng cho gói tặng khác"),
        )

    subscription = _ensure_subscription_aggregate(db, grant.shop_id, moment)
    _lock_subscription_aggregate(db, grant.shop_id)
    db.expire(subscription)
    db.refresh(subscription)
    grant.revoked_at = moment
    grant.revoked_by_user_id = admin.id
    grant.revoke_reason = data.reason
    grant.revoke_operation_id = data.operation_id
    grant.revoke_fingerprint = fingerprint
    # Rebase phải đọc danh sách quà SAU khi món này đã biến mất. Flush tường
    # minh, không dựa vào autoflush ngầm của từng kiểu query/driver.
    db.flush()
    moved_terms = _rebase_future_paid_terms(db, subscription, moment)
    _add_audit(
        db,
        admin.id,
        "SUBSCRIPTION_ADMIN_GIFT_REVOKED",
        f"Shop #{grant.shop_id}: thu hồi gói tặng #{grant.id}; "
        f"lý do: {data.reason}; kéo sớm {moved_terms} kỳ đã trả",
        shop_id=grant.shop_id,
    )
    db.commit()
    db.refresh(grant)
    return {
        "grant": _serialize_grant(grant),
        "subscription": get_subscription_state(db, grant.shop_id, now=moment),
    }


def admin_subscription_list(
    db: Session, *, now: Optional[datetime.datetime] = None
) -> list[Dict[str, Any]]:
    moment = now or utcnow()
    rows = []
    shops = db.query(models.Shop).order_by(models.Shop.id).all()
    for shop in shops:
        state = get_subscription_state(db, shop.id, now=moment)
        active_grant = (
            db.query(models.SubscriptionGrant)
            .filter(
                models.SubscriptionGrant.shop_id == shop.id,
                models.SubscriptionGrant.revoked_at.is_(None),
                models.SubscriptionGrant.starts_at <= moment,
                models.SubscriptionGrant.ends_at > moment,
            )
            .order_by(
                models.SubscriptionGrant.ends_at.desc(),
                models.SubscriptionGrant.id.desc(),
            )
            .first()
        )
        normal_review_count = (
            db.query(func.count(models.SubscriptionPayment.id))
            .filter(
                models.SubscriptionPayment.shop_id == shop.id,
                models.SubscriptionPayment.needs_review.is_(True),
                or_(
                    models.SubscriptionPayment.review_reason != REVIEW_OVERPAID,
                    models.SubscriptionPayment.review_reason.is_(None),
                    models.SubscriptionPayment.checkout_id.is_(None),
                ),
            )
            .scalar()
            or 0
        )
        overpaid_review_count = (
            db.query(
                func.count(
                    func.distinct(models.SubscriptionPayment.checkout_id)
                )
            )
            .filter(
                models.SubscriptionPayment.shop_id == shop.id,
                models.SubscriptionPayment.needs_review.is_(True),
                models.SubscriptionPayment.review_reason == REVIEW_OVERPAID,
                models.SubscriptionPayment.checkout_id.is_not(None),
            )
            .scalar()
            or 0
        )
        rows.append(
            {
                **state,
                "shop_name": shop.name,
                "owner_id": shop.owner_id,
                "owner_username": shop.owner.username if shop.owner else None,
                "shop_is_active": shop.is_active is not False,
                "status": state["phase"],
                "pro_until": state["access_until"],
                "grace_until": state["paid_grace_until"],
                "active_grant_id": active_grant.id if active_grant else None,
                "payments_needing_review": (
                    normal_review_count + overpaid_review_count
                ),
            }
        )
    return rows


def list_subscription_payments(
    db: Session,
    *,
    needs_review: Optional[bool] = None,
    limit: int = 100,
) -> list[Dict[str, Any]]:
    query = db.query(models.SubscriptionPayment)
    if needs_review is not None:
        query = query.filter(models.SubscriptionPayment.needs_review.is_(needs_review))
    grouped_overpaid = needs_review is True
    if grouped_overpaid:
        # OVERPAID là một vấn đề của CHECKOUT, không phải từng lần chuyển. Chỉ
        # lấy payment mới nhất mỗi checkout để Admin không hoàn lặp nhiều dòng.
        latest_overpaid_ids = (
            db.query(func.max(models.SubscriptionPayment.id))
            .filter(
                models.SubscriptionPayment.needs_review.is_(True),
                models.SubscriptionPayment.review_reason == REVIEW_OVERPAID,
                models.SubscriptionPayment.checkout_id.is_not(None),
            )
            .group_by(models.SubscriptionPayment.checkout_id)
        )
        query = query.filter(
            or_(
                models.SubscriptionPayment.review_reason != REVIEW_OVERPAID,
                models.SubscriptionPayment.review_reason.is_(None),
                models.SubscriptionPayment.checkout_id.is_(None),
                models.SubscriptionPayment.id.in_(latest_overpaid_ids),
            )
        )
    rows = query.order_by(
        models.SubscriptionPayment.created_at.desc(),
        models.SubscriptionPayment.id.desc(),
    ).limit(min(max(int(limit), 1), 200)).all()
    checkout_ids = {row.checkout_id for row in rows if row.checkout_id is not None}
    checkout_by_id = {
        checkout.id: checkout
        for checkout in (
            db.query(models.SubscriptionCheckout)
            .filter(models.SubscriptionCheckout.id.in_(checkout_ids))
            .all()
            if checkout_ids
            else []
        )
    }
    result = []
    for row in rows:
        checkout = checkout_by_id.get(row.checkout_id)
        is_overpaid_issue = bool(
            grouped_overpaid
            and row.review_reason == REVIEW_OVERPAID
            and checkout is not None
        )
        aggregate_received = (
            checkout.received_amount_vnd if checkout is not None else None
        )
        aggregate_due = checkout.amount_due_vnd if checkout is not None else None
        aggregate_refund = (
            checkout.refund_due_amount_vnd if checkout is not None else None
        )
        result.append({
            "id": row.id,
            "latest_payment_id": row.id,
            "checkout_id": row.checkout_id,
            "shop_id": row.shop_id,
            "reference_code": row.reference_code,
            # Với issue OVERPAID, amount_vnd là tổng checkout để cột "Đã nhận"
            # không đánh lừa Admin bằng riêng giao dịch cuối. Giá trị riêng lần
            # chuyển mới nhất vẫn có field tường minh bên dưới.
            "amount_vnd": (
                aggregate_received if is_overpaid_issue else row.amount_vnd
            ),
            "latest_payment_amount_vnd": row.amount_vnd,
            "checkout_amount_due_vnd": aggregate_due,
            "checkout_received_vnd": aggregate_received,
            "checkout_refund_due_vnd": aggregate_refund,
            "amount_due_vnd": aggregate_due,
            "received_vnd": aggregate_received,
            "refund_due_vnd": aggregate_refund,
            "provider": row.provider,
            "bank_txn_id": row.bank_txn_id,
            "account_no": row.account_no,
            "needs_review": row.needs_review,
            "review_reason": row.review_reason,
            "review_reason_code": row.review_reason,
            "review_group": (
                f"checkout:{row.checkout_id}:OVERPAID"
                if is_overpaid_issue
                else f"payment:{row.id}"
            ),
            "is_aggregate_issue": is_overpaid_issue,
            "created_at": row.created_at,
        })
    return result


def _tx_value(transaction: Any, name: str, default: Any = None) -> Any:
    if isinstance(transaction, dict):
        return transaction.get(name, default)
    return getattr(transaction, name, default)


def _normalize_account(value: Any) -> str:
    normalized = "".join(c for c in str(value or "").upper() if c.isalnum())
    return normalized.lstrip("0") or "0"


def _payment_idempotency_key(transaction: Any, fallback_account: str) -> str:
    helper = getattr(payment_service, "bank_idempotency_key", None)
    if helper is not None:
        try:
            return helper(
                transaction,
                fallback_account,
                namespace="sub-bank",
            )
        except TypeError:
            return "sub:" + helper(transaction, fallback_account)
    provider = str(_tx_value(transaction, "provider", "unknown") or "unknown").lower()
    account = _normalize_account(
        _tx_value(transaction, "account_no") or fallback_account
    )
    txn_id = _tx_value(transaction, "txn_id")
    if txn_id not in (None, ""):
        raw = f"txn|{provider}|{account}|{str(txn_id).strip()}"
    else:
        raw = (
            f"payload|{provider}|{account}|"
            f"{_tx_value(transaction, 'payload_fingerprint', '') or ''}"
        )
    return "sub-bank:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _amount_vnd(transaction: Any) -> Optional[int]:
    raw = _tx_value(transaction, "amount")
    if raw is None:
        return None
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount <= 0 or not amount.is_integer():
        return None
    return int(amount)


def _same_payment(
    existing: models.SubscriptionPayment,
    amount: int,
    reference_code: Optional[str],
    transaction: Any,
) -> bool:
    if existing.amount_vnd != amount:
        return False
    if (existing.reference_code or None) != (reference_code or None):
        return False
    txn_id = _tx_value(transaction, "txn_id")
    if existing.bank_txn_id and txn_id:
        return existing.bank_txn_id == str(txn_id)
    return True


def _extension_base(
    db: Session,
    subscription: models.ShopSubscription,
    now: datetime.datetime,
) -> datetime.datetime:
    terms = _paid_terms(db, subscription.shop_id)
    intervals: list[tuple[datetime.datetime, datetime.datetime, str]] = []
    if subscription.trial_started_at <= now < subscription.trial_ends_at:
        intervals.append(
            (subscription.trial_started_at, subscription.trial_ends_at, "TRIAL")
        )
    intervals.extend(
        (grant.starts_at, grant.ends_at, "GIFT")
        for grant in _active_grants(db, subscription.shop_id, now)
    )
    intervals.extend(
        (term.entitlement_starts_at, term.entitlement_ends_at, "PAID")
        for term in terms
        if term.entitlement_ends_at > now
    )
    legacy_paid = not terms and subscription.paid_until is not None
    if legacy_paid and subscription.paid_until > now:
        intervals.append((now, subscription.paid_until, "PAID"))

    access_until, _current_source, _access_source = _continuous_access(
        intervals, now
    )
    if access_until is not None:
        return access_until

    started_ends = [
        term.entitlement_ends_at
        for term in terms
        if term.entitlement_starts_at <= now
    ]
    if legacy_paid:
        started_ends.append(subscription.paid_until)
    latest_paid_end = max(started_ends) if started_ends else None
    if (
        latest_paid_end is not None
        and latest_paid_end <= now
        and now
        < latest_paid_end + datetime.timedelta(days=PAID_GRACE_DAYS)
    ):
        # Trong grace nối từ cuối segment thật, không biến 7 ngày grace thành
        # 7 ngày miễn phí cộng thêm vào kỳ vừa mua.
        return latest_paid_end
    return now


def _ensure_subscription_aggregate(
    db: Session, shop_id: int, now: datetime.datetime
) -> models.ShopSubscription:
    subscription = (
        db.query(models.ShopSubscription)
        .filter(models.ShopSubscription.shop_id == shop_id)
        .first()
    )
    if subscription is None:
        # Trạng thái bất thường sau startup: tạo aggregate trial đã hết, tuyệt
        # đối không cấp trial muộn lúc mở QR/webhook.
        subscription = models.ShopSubscription(
            shop_id=shop_id,
            trial_started_at=now,
            trial_ends_at=now,
            updated_at=now,
        )
        db.add(subscription)
        db.flush()
    return subscription


def _lock_subscription_aggregate(db: Session, shop_id: int) -> None:
    locked = db.execute(
        text(
            "UPDATE shop_subscriptions SET shop_id = shop_id "
            "WHERE shop_id = :shop_id"
        ),
        {"shop_id": shop_id},
    )
    if locked.rowcount != 1:
        raise RuntimeError("Không khóa được aggregate gói cước của shop")


def _sync_paid_until_cache(
    subscription: models.ShopSubscription,
    terms: list[models.SubscriptionCheckout],
    now: datetime.datetime,
) -> None:
    # Không có segment nghĩa là dữ liệu paid legacy; không được xóa mốc cache
    # duy nhất còn lại chỉ vì một quà Admin được thu hồi.
    if terms:
        subscription.paid_until = max(
            term.entitlement_ends_at for term in terms
        )
    subscription.updated_at = now


def _rebase_future_paid_terms(
    db: Session,
    subscription: models.ShopSubscription,
    now: datetime.datetime,
) -> int:
    """Đóng khoảng trống do thu hồi quà mà không đẩy/cắt segment paid."""
    terms = _paid_terms(db, subscription.shop_id)
    intervals: list[tuple[datetime.datetime, datetime.datetime, str]] = []
    if subscription.trial_started_at <= now < subscription.trial_ends_at:
        intervals.append(
            (subscription.trial_started_at, subscription.trial_ends_at, "TRIAL")
        )
    intervals.extend(
        (grant.starts_at, grant.ends_at, "GIFT")
        for grant in _active_grants(db, subscription.shop_id, now)
    )
    intervals.extend(
        (term.entitlement_starts_at, term.entitlement_ends_at, "PAID")
        for term in terms
        if term.entitlement_starts_at <= now < term.entitlement_ends_at
    )
    legacy_paid = not terms and subscription.paid_until is not None
    if legacy_paid and subscription.paid_until > now:
        intervals.append((now, subscription.paid_until, "PAID"))

    cursor, _current_source, _access_source = _continuous_access(intervals, now)
    if cursor is None:
        ended_paid = [
            term.entitlement_ends_at
            for term in terms
            if term.entitlement_starts_at <= now
            and term.entitlement_ends_at <= now
        ]
        if legacy_paid and subscription.paid_until <= now:
            ended_paid.append(subscription.paid_until)
        latest_paid_end = max(ended_paid) if ended_paid else None
        if (
            latest_paid_end is not None
            and now
            < latest_paid_end + datetime.timedelta(days=PAID_GRACE_DAYS)
        ):
            # Nếu quà bị gỡ trong grace, kỳ đã mua phải nối ngược từ hạn paid
            # cũ như lúc gia hạn trực tiếp; dùng `now` sẽ tặng miễn phần grace.
            cursor = latest_paid_end
        else:
            cursor = now
    moved = 0
    for term in terms:
        if term.entitlement_starts_at <= now:
            continue
        original_start = term.entitlement_starts_at
        original_end = term.entitlement_ends_at
        if original_start > cursor:
            # Chỉ kéo SỚM để lấp phần quà vừa gỡ. Segment đang chồng một quyền
            # khác được giữ nguyên, không âm thầm đẩy ngày khách đã mua ra xa.
            term.entitlement_starts_at = cursor
            term.entitlement_ends_at = cursor + datetime.timedelta(
                days=term.duration_days
            )
            term.paid_until_after = term.entitlement_ends_at
            moved += 1
        cursor = max(cursor, term.entitlement_ends_at)
        if original_end <= original_start:
            raise RuntimeError("Segment ngày Pro không hợp lệ")

    _sync_paid_until_cache(subscription, terms, now)
    return moved


def _record_review_payment(
    db: Session,
    transaction: Any,
    *,
    key: str,
    amount: int,
    reference_code: Optional[str],
    checkout: Optional[models.SubscriptionCheckout],
    reason: str,
) -> models.SubscriptionPayment:
    payment = models.SubscriptionPayment(
        checkout_id=checkout.id if checkout else None,
        shop_id=checkout.shop_id if checkout else None,
        reference_code=reference_code,
        amount_vnd=amount,
        idempotency_key=key,
        provider=(
            str(_tx_value(transaction, "provider"))
            if _tx_value(transaction, "provider")
            else None
        ),
        bank_txn_id=(
            str(_tx_value(transaction, "txn_id"))
            if _tx_value(transaction, "txn_id")
            else None
        ),
        account_no=(
            str(_tx_value(transaction, "account_no"))
            if _tx_value(transaction, "account_no")
            else None
        ),
        payload_fingerprint=_tx_value(transaction, "payload_fingerprint"),
        needs_review=True,
        review_reason=reason,
    )
    db.add(payment)
    return payment


def apply_subscription_transactions(
    db: Session,
    transactions: Iterable[Any],
    *,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, list]:
    """Ghi danh sách tiền vào, cộng dồn checkout và cấp đúng một kỳ Pro."""
    moment = now or utcnow()
    bank = _require_platform_bank()
    configured_account = bank["account_no"]
    activated_shops: set[int] = set()
    underpaid: set[int] = set()
    review_payments: set[int] = set()
    duplicates: set[int] = set()
    rejected: list[str] = []

    for transaction in transactions:
        reference_raw = _tx_value(transaction, "reference_code")
        reference_code = (
            str(reference_raw).strip().upper() if reference_raw else None
        )
        direction = str(_tx_value(transaction, "direction") or "").lower()
        amount = _amount_vnd(transaction)
        if direction == "out" or amount is None:
            rejected.append(reference_code or "(không mã)")
            _add_audit(
                db,
                None,
                "SUBSCRIPTION_WEBHOOK_REJECTED",
                "Từ chối giao dịch gói Pro: tiền ra, thiếu số tiền hoặc số tiền "
                "không phải VND nguyên dương",
            )
            db.commit()
            continue

        key = _payment_idempotency_key(transaction, configured_account)
        existing = (
            db.query(models.SubscriptionPayment)
            .filter(models.SubscriptionPayment.idempotency_key == key)
            .first()
        )
        if existing is not None:
            if _same_payment(existing, amount, reference_code, transaction):
                duplicates.add(existing.id)
            else:
                rejected.append(reference_code or "(không mã)")
                _add_audit(
                    db,
                    None,
                    "SUBSCRIPTION_IDEMPOTENCY_COLLISION",
                    "Khóa giao dịch gói Pro đã tồn tại nhưng payload mới không khớp",
                    shop_id=existing.shop_id,
                )
                db.commit()
            continue

        checkout = None
        if reference_code:
            checkout = (
                db.query(models.SubscriptionCheckout)
                .filter(
                    models.SubscriptionCheckout.reference_code == reference_code
                )
                .first()
            )

        account_no = _tx_value(transaction, "account_no")
        account_mismatch = bool(
            configured_account
            and account_no
            and _normalize_account(account_no)
            != _normalize_account(configured_account)
        )
        if account_mismatch:
            reason = REVIEW_ACCOUNT_MISMATCH
        elif not reference_code:
            reason = REVIEW_NO_REFERENCE
        elif checkout is None:
            reason = REVIEW_UNKNOWN_REFERENCE
        elif (
            checkout.activated_at is None
            and moment >= checkout.expires_at
        ):
            reason = REVIEW_EXPIRED_CHECKOUT
        else:
            reason = ""

        if reason:
            if checkout is not None and reason == REVIEW_EXPIRED_CHECKOUT:
                checkout.status = CHECKOUT_EXPIRED
            payment = _record_review_payment(
                db,
                transaction,
                key=key,
                amount=amount,
                reference_code=reference_code,
                checkout=checkout,
                reason=reason,
            )
            _add_audit(
                db,
                None,
                "SUBSCRIPTION_PAYMENT_REVIEW",
                f"Tiền gói Pro {amount:,}đ cần xử lý: {reason}; "
                f"mã {reference_code or '(không mã)'}",
                shop_id=checkout.shop_id if checkout is not None else None,
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                concurrent = (
                    db.query(models.SubscriptionPayment)
                    .filter(models.SubscriptionPayment.idempotency_key == key)
                    .first()
                )
                if concurrent is None:
                    raise
                if not _same_payment(
                    concurrent, amount, reference_code, transaction
                ):
                    rejected.append(reference_code or "(không mã)")
                    continue
                payment = concurrent
                duplicates.add(payment.id)
            db.refresh(payment)
            review_payments.add(payment.id)
            continue

        payment = models.SubscriptionPayment(
            checkout_id=checkout.id,
            shop_id=checkout.shop_id,
            reference_code=reference_code,
            amount_vnd=amount,
            idempotency_key=key,
            provider=(
                str(_tx_value(transaction, "provider"))
                if _tx_value(transaction, "provider")
                else None
            ),
            bank_txn_id=(
                str(_tx_value(transaction, "txn_id"))
                if _tx_value(transaction, "txn_id")
                else None
            ),
            account_no=(str(account_no) if account_no else None),
            payload_fingerprint=_tx_value(transaction, "payload_fingerprint"),
            needs_review=False,
        )
        db.add(payment)
        try:
            db.flush()  # lấy write lock + unique idempotency trước khi cộng tiền
        except IntegrityError:
            db.rollback()
            concurrent = (
                db.query(models.SubscriptionPayment)
                .filter(models.SubscriptionPayment.idempotency_key == key)
                .first()
            )
            if concurrent is not None and _same_payment(
                concurrent, amount, reference_code, transaction
            ):
                duplicates.add(concurrent.id)
                continue
            # Không tìm thấy dòng thắng race nghĩa là IntegrityError khác
            # idempotency; phải nổi 500 để không che lỗi DB/lập trình.
            raise

        db.expire(checkout)
        db.refresh(checkout)
        if checkout.activated_at is not None:
            checkout.received_amount_vnd += amount
            checkout.refund_due_amount_vnd = max(
                checkout.received_amount_vnd - checkout.amount_due_vnd, 0
            )
            checkout.status = CHECKOUT_OVERPAID
            payment.needs_review = True
            payment.review_reason = REVIEW_OVERPAID
            _add_audit(
                db,
                None,
                "SUBSCRIPTION_PAYMENT_OVERPAID",
                f"Checkout #{checkout.id} đã kích hoạt nhưng nhận thêm "
                f"{amount:,}đ; chờ xử lý {checkout.refund_due_amount_vnd:,}đ",
                shop_id=checkout.shop_id,
            )
            db.commit()
            db.refresh(payment)
            review_payments.add(payment.id)
            continue

        # Cộng bằng SQL để hai giao dịch khác nhau không ghi đè tổng của nhau.
        db.execute(
            text(
                "UPDATE subscription_checkouts "
                "SET received_amount_vnd = received_amount_vnd + :amount "
                "WHERE id = :checkout_id"
            ),
            {"amount": amount, "checkout_id": checkout.id},
        )
        db.expire(checkout)
        db.refresh(checkout)

        if checkout.received_amount_vnd < checkout.amount_due_vnd:
            checkout.status = CHECKOUT_UNDERPAID
            payment.needs_review = True
            payment.review_reason = REVIEW_UNDERPAID
            underpaid.add(checkout.id)
            _add_audit(
                db,
                None,
                "SUBSCRIPTION_PAYMENT_UNDERPAID",
                f"Checkout #{checkout.id}: đã nhận "
                f"{checkout.received_amount_vnd:,}/{checkout.amount_due_vnd:,}đ",
                shop_id=checkout.shop_id,
            )
            db.commit()
            db.refresh(payment)
            review_payments.add(payment.id)
            continue

        subscription = _ensure_subscription_aggregate(
            db, checkout.shop_id, moment
        )
        # Khóa aggregate trước khi đọc lịch trial/gift/paid và nối segment mới.
        _lock_subscription_aggregate(db, checkout.shop_id)
        db.expire(subscription)
        db.refresh(subscription)
        extension_base = _extension_base(db, subscription, moment)
        new_paid_until = extension_base + datetime.timedelta(
            days=checkout.duration_days
        )
        subscription.paid_until = new_paid_until
        subscription.updated_at = moment
        checkout.activated_at = moment
        checkout.entitlement_starts_at = extension_base
        checkout.entitlement_ends_at = new_paid_until
        checkout.paid_until_after = new_paid_until
        checkout.refund_due_amount_vnd = max(
            checkout.received_amount_vnd - checkout.amount_due_vnd, 0
        )
        checkout.status = (
            CHECKOUT_OVERPAID
            if checkout.refund_due_amount_vnd > 0
            else CHECKOUT_PAID
        )
        if checkout.status == CHECKOUT_OVERPAID:
            payment.needs_review = True
            payment.review_reason = REVIEW_OVERPAID
        # Các khoản thiếu trước đã được bù đủ; chỉ khoản dư hiện tại cần review.
        db.query(models.SubscriptionPayment).filter(
            models.SubscriptionPayment.checkout_id == checkout.id,
            models.SubscriptionPayment.review_reason == REVIEW_UNDERPAID,
        ).update(
            {
                models.SubscriptionPayment.needs_review: False,
                models.SubscriptionPayment.review_reason: None,
            },
            synchronize_session=False,
        )
        _add_audit(
            db,
            None,
            "SUBSCRIPTION_ACTIVATED",
            f"Shop #{checkout.shop_id}: checkout #{checkout.id} kích hoạt "
            f"{checkout.duration_days} ngày, paid_until={new_paid_until.isoformat()}"
            + (
                f", dư {checkout.refund_due_amount_vnd:,}đ chờ xử lý"
                if checkout.refund_due_amount_vnd
                else ""
            ),
            shop_id=checkout.shop_id,
        )
        db.commit()
        db.refresh(payment)
        activated_shops.add(checkout.shop_id)
        if payment.needs_review:
            review_payments.add(payment.id)

    return {
        "activated_shop_ids": sorted(activated_shops),
        "underpaid_checkout_ids": sorted(underpaid),
        "review_payment_ids": sorted(review_payments),
        "duplicate_payment_ids": sorted(duplicates),
        "rejected_references": rejected,
    }


def apply_webhook_payment(
    db: Session, request_data: Dict[str, Any]
) -> Dict[str, list]:
    """Interface ổn định để ``routers/webhooks.py`` gọi cho gói cước."""
    extractor = getattr(payment_service, "extract_subscription_transactions", None)
    if extractor is None:
        raise RuntimeError("payment_service chưa có bộ tách giao dịch SUB")
    return apply_subscription_transactions(db, extractor(request_data))


__all__ = [
    "PRICE_VND",
    "DURATION_DAYS",
    "TRIAL_DAYS",
    "PAID_GRACE_DAYS",
    "CHECKOUT_HOURS",
    "create_trial_for_shop",
    "get_subscription_state",
    "require_pro",
    "subscription_overview",
    "create_checkout",
    "create_admin_gift",
    "revoke_admin_gift",
    "admin_subscription_list",
    "list_subscription_payments",
    "apply_subscription_transactions",
    "apply_webhook_payment",
]
