from __future__ import annotations

import datetime
import hashlib
import json
import secrets
import unicodedata

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..core.money import checked_add, checked_multiply, checked_vnd, cumulative_basis
from ..core.numeric_limits import MAX_SAFE_QUANTITY
from ..core.security import burn_password_time, hash_password, verify_password
from ..dependencies import (
    PERMISSION_FNB_MANAGE,
    PERMISSION_FNB_BAR,
    PERMISSION_FNB_KITCHEN,
    PERMISSION_FNB_SERVICE,
    STAFF_ROLE_MANAGER,
    effective_staff_role,
    has_shop_operator_access,
    require_own_shop,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.fnb import (
    FnbAreaCreate,
    FnbAreaUpdate,
    FnbLineCancel,
    FnbLineCreate,
    FnbLineUpdate,
    FnbManagerApprovalCreate,
    FnbManagerPinSet,
    FnbMergeTable,
    FnbMoveTable,
    FnbSessionCancel,
    FnbSessionOpen,
    FnbSessionSend,
    FnbSettingsUpdate,
    FnbStationUpdate,
    FnbTableCreate,
    FnbTableUpdate,
    FnbTicketTransition,
)
from . import inventory_service

_ACTIVE_SESSION_STATUSES = ("OPEN", "PARTIALLY_SETTLED", "PAYMENT_PENDING")


def fnb_error(status_code: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": tr(message), **extra},
    )


def require_fnb_access(
    db: Session, shop_id: int, current_user: models.User, permission: str
) -> models.Shop:
    shop = require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, permission)
    return shop


def require_fnb_shop(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
    if not bool(shop.fnb_enabled):
        raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
    return shop


def normalize_name(value: str) -> tuple[str, str]:
    display = unicodedata.normalize("NFC", " ".join((value or "").strip().split()))
    if not display:
        raise fnb_error(400, "FNB_NAME_REQUIRED", "Tên không được để trống")
    return display, unicodedata.normalize("NFKC", display).casefold()


def operation_fingerprint(action: str, payload: dict) -> str:
    canonical = json.dumps(
        {"action": action, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _existing_operation(
    db: Session, shop_id: int, operation_id: str, fingerprint: str
) -> dict | None:
    operation = (
        db.query(models.FnbActionLog)
        .filter(
            models.FnbActionLog.shop_id == shop_id,
            models.FnbActionLog.operation_id == operation_id,
        )
        .first()
    )
    if operation is None:
        return None
    if operation.operation_fingerprint != fingerprint:
        raise fnb_error(
            409,
            "FNB_OPERATION_REUSED",
            "Mã thao tác đã được dùng cho nội dung khác",
        )
    return json.loads(operation.result_json)


def _record_operation(
    db: Session,
    *,
    shop_id: int,
    session_id: int | None,
    actor_user_id: int,
    action: str,
    operation_id: str,
    fingerprint: str,
    result: dict,
    before=None,
    after=None,
    reason: str | None = None,
) -> None:
    db.add(
        models.FnbActionLog(
            shop_id=shop_id,
            session_id=session_id,
            actor_user_id=actor_user_id,
            action=action,
            operation_id=operation_id,
            operation_fingerprint=fingerprint,
            result_json=_json(result),
            before_json=_json(before) if before is not None else None,
            after_json=_json(after) if after is not None else None,
            reason=reason,
        )
    )


def require_floor_revision(shop: models.Shop, expected_revision: int) -> None:
    current = int(shop.fnb_revision or 0)
    if current != int(expected_revision):
        raise fnb_error(
            409,
            "FNB_FLOOR_CHANGED",
            "Sơ đồ bàn vừa được cập nhật",
            revision=current,
        )


def _prepare_locked_shop(db: Session, shop_id: int) -> None:
    # The auth read may have opened a SQLite snapshot. Close it before taking
    # the shared no-op UPDATE lock, then every caller rechecks auth under lock.
    db.rollback()
    inventory_service.lock_shop_for_inventory(db, shop_id)


def _payload(request, **identity) -> dict:
    return {
        **identity,
        **request.model_dump(exclude={"operation_id"}),
    }


def _area_result(area: models.FnbArea, revision: int) -> dict:
    return {
        "id": area.id,
        "shop_id": area.shop_id,
        "name": area.name,
        "sort_order": int(area.sort_order),
        "active": bool(area.active),
        "fnb_revision": int(revision),
    }


def _table_result(table: models.FnbTable, revision: int) -> dict:
    return {
        "id": table.id,
        "shop_id": table.shop_id,
        "area_id": table.area_id,
        "name": table.name,
        "sort_order": int(table.sort_order),
        "active": bool(table.active),
        "state_version": int(table.state_version),
        "fnb_revision": int(revision),
    }


def _finish(
    db: Session,
    current_user: models.User,
    action: str,
    operation_id: str,
    fingerprint: str,
    result: dict,
    *,
    session_id: int | None = None,
    before=None,
    after=None,
    reason: str | None = None,
) -> dict:
    _record_operation(
        db,
        shop_id=result["shop_id"],
        session_id=session_id,
        actor_user_id=current_user.id,
        action=action,
        operation_id=operation_id,
        fingerprint=fingerprint,
        result=result,
        before=before,
        after=after,
        reason=reason,
    )
    db.commit()
    return result


def update_fnb_settings(
    db: Session,
    current_user: models.User,
    shop_id: int,
    request: FnbSettingsUpdate,
) -> dict:
    action = "FNB_SETTINGS_UPDATE"
    fingerprint = operation_fingerprint(action, _payload(request, shop_id=shop_id))
    try:
        require_own_shop(db, shop_id, current_user)
        _prepare_locked_shop(db, shop_id)
        shop = require_own_shop(db, shop_id, current_user)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        require_floor_revision(shop, request.expected_revision)
        before = {
            "fnb_enabled": bool(shop.fnb_enabled),
            "fnb_revision": int(shop.fnb_revision or 0),
        }
        if bool(shop.fnb_enabled) and not request.enabled:
            active = (
                db.query(models.FnbServiceSession.id)
                .filter(
                    models.FnbServiceSession.shop_id == shop_id,
                    models.FnbServiceSession.status.in_(_ACTIVE_SESSION_STATUSES),
                )
                .first()
            )
            if active is not None:
                raise fnb_error(
                    409,
                    "FNB_ACTIVE_SESSION",
                    "Cửa hàng còn bàn đang phục vụ",
                )
        if bool(shop.fnb_enabled) != request.enabled:
            shop.fnb_enabled = request.enabled
            shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = {
            "shop_id": shop.id,
            "fnb_enabled": bool(shop.fnb_enabled),
            "fnb_revision": int(shop.fnb_revision or 0),
        }
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            before=before,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def update_product_station(
    db: Session,
    current_user: models.User,
    product_id: int,
    request: FnbStationUpdate,
) -> dict:
    action = "FNB_PRODUCT_STATION_UPDATE"
    fingerprint = operation_fingerprint(action, _payload(request, product_id=product_id))
    try:
        product = db.get(models.Product, product_id)
        if product is None:
            raise fnb_error(404, "FNB_PRODUCT_NOT_FOUND", "Không tìm thấy món")
        shop_id = int(product.shop_id)
        require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        _prepare_locked_shop(db, shop_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        require_floor_revision(shop, request.expected_revision)
        product = (
            db.query(models.Product)
            .filter(models.Product.id == product_id, models.Product.shop_id == shop_id)
            .first()
        )
        if product is None:
            raise fnb_error(404, "FNB_PRODUCT_NOT_FOUND", "Không tìm thấy món")
        before = {"station": product.fnb_station}
        if product.fnb_station != request.station:
            product.fnb_station = request.station
            shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        result = {
            "id": product.id,
            "shop_id": shop_id,
            "station": product.fnb_station,
            "fnb_revision": int(shop.fnb_revision or 0),
        }
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            before=before,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def set_manager_pin(
    db: Session,
    current_user: models.User,
    shop_id: int,
    request: FnbManagerPinSet,
) -> dict:
    shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
    is_owner = shop.owner_id == current_user.id
    is_manager = (
        current_user.role == "STAFF"
        and effective_staff_role(current_user) == STAFF_ROLE_MANAGER
        and current_user.staff_shop_id == shop_id
    )
    if not (is_owner or is_manager):
        raise fnb_error(403, "FNB_MANAGER_REQUIRED", "Chỉ chủ quán hoặc quản lý được đặt PIN")
    current_user.fnb_manager_pin_hash = hash_password(request.pin)
    db.commit()
    return {"shop_id": shop_id, "manager_pin_configured": True}


def create_manager_approval(
    db: Session,
    current_user: models.User,
    request: FnbManagerApprovalCreate,
) -> dict:
    shop = require_fnb_access(
        db, request.shop_id, current_user, PERMISSION_FNB_SERVICE
    )
    session = (
        db.query(models.FnbServiceSession)
        .filter(
            models.FnbServiceSession.id == request.entity_id,
            models.FnbServiceSession.shop_id == request.shop_id,
        )
        .first()
    )
    if session is None:
        raise fnb_error(404, "FNB_SESSION_NOT_FOUND", "Không tìm thấy phiên phục vụ")
    require_session_revision(db, session, request.revision)
    approver = (
        db.query(models.User)
        .filter(models.User.username == request.approver_username, models.User.is_active == True)  # noqa: E712
        .first()
    )
    valid_approver = approver is not None and (
        approver.id == shop.owner_id
        or (
            approver.role == "STAFF"
            and approver.staff_shop_id == request.shop_id
            and effective_staff_role(approver) == STAFF_ROLE_MANAGER
        )
    )
    now = datetime.datetime.utcnow()
    failed_attempts = (
        db.query(models.FnbManagerApproval)
        .filter(
            models.FnbManagerApproval.shop_id == request.shop_id,
            models.FnbManagerApproval.actor_user_id == current_user.id,
            models.FnbManagerApproval.action == "PIN_FAILED",
            models.FnbManagerApproval.created_at >= now - datetime.timedelta(minutes=15),
        )
        .count()
    )
    if failed_attempts >= 5:
        raise fnb_error(
            429,
            "FNB_PIN_RATE_LIMITED",
            "Đã nhập sai PIN quá nhiều lần; vui lòng thử lại sau",
            retry_after_seconds=900,
        )
    pin_hash = approver.fnb_manager_pin_hash if valid_approver else None
    pin_ok = False
    if pin_hash is None:
        burn_password_time()
    else:
        pin_ok = verify_password(request.pin, pin_hash)
    if not pin_ok:
        db.add(
            models.FnbManagerApproval(
                shop_id=request.shop_id,
                approver_user_id=approver.id if valid_approver else current_user.id,
                actor_user_id=current_user.id,
                action="PIN_FAILED",
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                revision=request.revision,
                token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                expires_at=now,
                used_at=now,
            )
        )
        db.commit()
        raise fnb_error(403, "FNB_PIN_INVALID", "PIN quản lý không đúng")
    token = secrets.token_urlsafe(32)
    db.add(
        models.FnbManagerApproval(
            shop_id=request.shop_id,
            approver_user_id=approver.id,
            actor_user_id=current_user.id,
            action=request.action,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            revision=request.revision,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=5),
        )
    )
    db.commit()
    return {"approval_token": token, "expires_in_seconds": 300}


def create_area(
    db: Session, current_user: models.User, request: FnbAreaCreate
) -> dict:
    action = "FNB_AREA_CREATE"
    fingerprint = operation_fingerprint(action, _payload(request))
    try:
        require_fnb_access(db, request.shop_id, current_user, PERMISSION_FNB_MANAGE)
        _prepare_locked_shop(db, request.shop_id)
        shop = require_fnb_access(
            db, request.shop_id, current_user, PERMISSION_FNB_MANAGE
        )
        existing = _existing_operation(
            db, request.shop_id, request.operation_id, fingerprint
        )
        if existing is not None:
            db.rollback()
            return existing
        require_floor_revision(shop, request.expected_revision)
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        name, name_key = normalize_name(request.name)
        duplicate = (
            db.query(models.FnbArea.id)
            .filter(
                models.FnbArea.shop_id == request.shop_id,
                models.FnbArea.name_key == name_key,
            )
            .first()
        )
        if duplicate is not None:
            raise fnb_error(409, "FNB_NAME_EXISTS", "Tên khu vực đã tồn tại")
        area = models.FnbArea(
            shop_id=request.shop_id,
            name=name,
            name_key=name_key,
            sort_order=request.sort_order,
        )
        db.add(area)
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = _area_result(area, shop.fnb_revision)
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def _area_for_manage(
    db: Session, current_user: models.User, area_id: int
) -> models.FnbArea:
    area = db.query(models.FnbArea).filter(models.FnbArea.id == area_id).first()
    if area is None or not has_shop_operator_access(
        db.query(models.Shop).filter(models.Shop.id == area.shop_id).one(), current_user
    ):
        raise fnb_error(404, "FNB_AREA_NOT_FOUND", "Không tìm thấy khu vực")
    require_staff_permission(current_user, PERMISSION_FNB_MANAGE)
    return area


def update_area(
    db: Session,
    current_user: models.User,
    area_id: int,
    request: FnbAreaUpdate,
) -> dict:
    action = "FNB_AREA_UPDATE"
    fingerprint = operation_fingerprint(action, _payload(request, area_id=area_id))
    try:
        area = _area_for_manage(db, current_user, area_id)
        shop_id = int(area.shop_id)
        _prepare_locked_shop(db, shop_id)
        area = _area_for_manage(db, current_user, area_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        require_floor_revision(shop, request.expected_revision)
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        before = _area_result(area, shop.fnb_revision)
        if request.active is False and bool(area.active):
            active_table = (
                db.query(models.FnbTable.id)
                .filter(
                    models.FnbTable.area_id == area.id,
                    models.FnbTable.active.is_(True),
                )
                .first()
            )
            if active_table is not None:
                raise fnb_error(
                    409,
                    "FNB_AREA_HAS_ACTIVE_TABLES",
                    "Khu vực còn bàn đang hoạt động",
                )
        if request.name is not None:
            name, name_key = normalize_name(request.name)
            duplicate = (
                db.query(models.FnbArea.id)
                .filter(
                    models.FnbArea.shop_id == shop_id,
                    models.FnbArea.name_key == name_key,
                    models.FnbArea.id != area.id,
                )
                .first()
            )
            if duplicate is not None:
                raise fnb_error(409, "FNB_NAME_EXISTS", "Tên khu vực đã tồn tại")
            area.name, area.name_key = name, name_key
        if request.sort_order is not None:
            area.sort_order = request.sort_order
        if request.active is not None:
            area.active = request.active
        area.updated_at = datetime.datetime.utcnow()
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = _area_result(area, shop.fnb_revision)
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            before=before,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def create_table(
    db: Session, current_user: models.User, request: FnbTableCreate
) -> dict:
    action = "FNB_TABLE_CREATE"
    fingerprint = operation_fingerprint(action, _payload(request))
    try:
        require_fnb_access(db, request.shop_id, current_user, PERMISSION_FNB_MANAGE)
        _prepare_locked_shop(db, request.shop_id)
        shop = require_fnb_access(
            db, request.shop_id, current_user, PERMISSION_FNB_MANAGE
        )
        existing = _existing_operation(
            db, request.shop_id, request.operation_id, fingerprint
        )
        if existing is not None:
            db.rollback()
            return existing
        require_floor_revision(shop, request.expected_revision)
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        area = (
            db.query(models.FnbArea)
            .filter(
                models.FnbArea.id == request.area_id,
                models.FnbArea.shop_id == request.shop_id,
            )
            .first()
        )
        if area is None:
            raise fnb_error(404, "FNB_AREA_NOT_FOUND", "Không tìm thấy khu vực")
        if not bool(area.active):
            raise fnb_error(409, "FNB_AREA_INACTIVE", "Khu vực đã ngừng hoạt động")
        name, name_key = normalize_name(request.name)
        duplicate = (
            db.query(models.FnbTable.id)
            .filter(
                models.FnbTable.area_id == area.id,
                models.FnbTable.name_key == name_key,
            )
            .first()
        )
        if duplicate is not None:
            raise fnb_error(409, "FNB_NAME_EXISTS", "Tên bàn đã tồn tại")
        table = models.FnbTable(
            shop_id=request.shop_id,
            area_id=area.id,
            name=name,
            name_key=name_key,
            sort_order=request.sort_order,
        )
        db.add(table)
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = _table_result(table, shop.fnb_revision)
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def _table_for_manage(
    db: Session, current_user: models.User, table_id: int
) -> models.FnbTable:
    table = db.query(models.FnbTable).filter(models.FnbTable.id == table_id).first()
    if table is None or not has_shop_operator_access(
        db.query(models.Shop).filter(models.Shop.id == table.shop_id).one(), current_user
    ):
        raise fnb_error(404, "FNB_TABLE_NOT_FOUND", "Không tìm thấy bàn")
    require_staff_permission(current_user, PERMISSION_FNB_MANAGE)
    return table


def _table_has_active_session(db: Session, table_id: int) -> bool:
    return (
        db.query(models.FnbSessionTable.id)
        .join(
            models.FnbServiceSession,
            models.FnbServiceSession.id == models.FnbSessionTable.session_id,
        )
        .filter(
            models.FnbSessionTable.table_id == table_id,
            models.FnbSessionTable.released_at.is_(None),
            models.FnbServiceSession.status.in_(_ACTIVE_SESSION_STATUSES),
        )
        .first()
        is not None
    )


def update_table(
    db: Session,
    current_user: models.User,
    table_id: int,
    request: FnbTableUpdate,
) -> dict:
    action = "FNB_TABLE_UPDATE"
    fingerprint = operation_fingerprint(action, _payload(request, table_id=table_id))
    try:
        table = _table_for_manage(db, current_user, table_id)
        shop_id = int(table.shop_id)
        _prepare_locked_shop(db, shop_id)
        table = _table_for_manage(db, current_user, table_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        require_floor_revision(shop, request.expected_revision)
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        if int(table.state_version or 0) != request.expected_state_version:
            raise fnb_error(
                409,
                "FNB_TABLE_CHANGED",
                "Bàn vừa được cập nhật",
                state_version=int(table.state_version or 0),
            )
        moving = request.area_id is not None and request.area_id != table.area_id
        deactivating = request.active is False and bool(table.active)
        if (moving or deactivating) and _table_has_active_session(db, table.id):
            raise fnb_error(409, "FNB_TABLE_OCCUPIED", "Bàn đang phục vụ")
        target_area_id = request.area_id if request.area_id is not None else table.area_id
        area = (
            db.query(models.FnbArea)
            .filter(
                models.FnbArea.id == target_area_id,
                models.FnbArea.shop_id == shop_id,
            )
            .first()
        )
        if area is None:
            raise fnb_error(404, "FNB_AREA_NOT_FOUND", "Không tìm thấy khu vực")
        if not bool(area.active):
            raise fnb_error(409, "FNB_AREA_INACTIVE", "Khu vực đã ngừng hoạt động")
        before = _table_result(table, shop.fnb_revision)
        name, name_key = (
            normalize_name(request.name)
            if request.name is not None
            else (table.name, table.name_key)
        )
        duplicate = (
            db.query(models.FnbTable.id)
            .filter(
                models.FnbTable.area_id == target_area_id,
                models.FnbTable.name_key == name_key,
                models.FnbTable.id != table.id,
            )
            .first()
        )
        if duplicate is not None:
            raise fnb_error(409, "FNB_NAME_EXISTS", "Tên bàn đã tồn tại")
        table.area_id = target_area_id
        table.name, table.name_key = name, name_key
        if request.sort_order is not None:
            table.sort_order = request.sort_order
        if request.active is not None:
            table.active = request.active
        table.state_version = int(table.state_version or 0) + 1
        table.updated_at = datetime.datetime.utcnow()
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = _table_result(table, shop.fnb_revision)
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            before=before,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def _active_links(db: Session, session_id: int) -> list[models.FnbSessionTable]:
    return (
        db.query(models.FnbSessionTable)
        .filter(
            models.FnbSessionTable.session_id == session_id,
            models.FnbSessionTable.released_at.is_(None),
        )
        .order_by(models.FnbSessionTable.id)
        .all()
    )


def serialize_session(db: Session, session: models.FnbServiceSession) -> dict:
    tables = []
    for link in _active_links(db, session.id):
        table = (
            db.query(models.FnbTable)
            .filter(
                models.FnbTable.id == link.table_id,
                models.FnbTable.shop_id == session.shop_id,
            )
            .one()
        )
        tables.append(
            {
                "id": table.id,
                "area_id": table.area_id,
                "name": table.name,
                "state_version": int(table.state_version or 0),
            }
        )
    lines = (
        db.query(models.FnbSessionLine)
        .filter(models.FnbSessionLine.session_id == session.id)
        .order_by(models.FnbSessionLine.id)
        .all()
    )
    serialized_lines = [
        {
            "id": line.id,
            "product_id": line.product_id,
            "product_name": line.product_name,
            "unit_price_vnd": int(line.unit_price_vnd),
            "station": line.station,
            "note": line.note,
            "quantity": int(line.quantity),
            "cancelled_quantity": int(line.cancelled_quantity or 0),
            "sent_quantity": int(line.sent_quantity or 0),
            "sent_cancelled_quantity": int(line.sent_cancelled_quantity or 0),
            "active_sent_quantity": int(line.sent_quantity or 0)
            - int(line.sent_cancelled_quantity or 0),
            "unsent_quantity": int(line.quantity)
            - int(line.sent_quantity or 0)
            - int(line.cancelled_quantity or 0)
            + int(line.sent_cancelled_quantity or 0),
            "billable_quantity": int(line.quantity)
            - int(line.cancelled_quantity or 0),
            "state_version": int(line.state_version or 0),
        }
        for line in lines
    ]
    try:
        subtotal = checked_add(
            *(
                checked_multiply(line["billable_quantity"], line["unit_price_vnd"])
                for line in serialized_lines
            )
        )
    except ValueError as exc:
        raise fnb_error(
            400, "FNB_AMOUNT_TOO_LARGE", "Tổng tiền vượt giới hạn hỗ trợ"
        ) from exc
    return {
        "id": session.id,
        "shop_id": session.shop_id,
        "status": session.status,
        "revision": int(session.revision or 0),
        "opened_at": session.opened_at.isoformat() + "Z",
        "tables": tables,
        "lines": serialized_lines,
        "subtotal_vnd": subtotal,
        "unsent_quantity": sum(line["unsent_quantity"] for line in serialized_lines),
    }


def require_session_revision(
    db: Session, session: models.FnbServiceSession, expected_revision: int
) -> None:
    if int(session.revision or 0) != int(expected_revision):
        raise fnb_error(
            409,
            "FNB_SESSION_CHANGED",
            "Bàn vừa được cập nhật trên thiết bị khác",
            revision=int(session.revision or 0),
            snapshot=serialize_session(db, session),
        )


def _session_for_access(
    db: Session,
    current_user: models.User,
    session_id: int,
    permission: str = PERMISSION_FNB_SERVICE,
) -> models.FnbServiceSession:
    session = (
        db.query(models.FnbServiceSession)
        .filter(models.FnbServiceSession.id == session_id)
        .first()
    )
    shop = db.get(models.Shop, session.shop_id) if session is not None else None
    if session is None or shop is None or not has_shop_operator_access(shop, current_user):
        raise fnb_error(404, "FNB_SESSION_NOT_FOUND", "Không tìm thấy phiên phục vụ")
    require_staff_permission(current_user, permission)
    return session


def _line_for_access(
    db: Session, current_user: models.User, line_id: int
) -> tuple[models.FnbSessionLine, models.FnbServiceSession]:
    line = db.get(models.FnbSessionLine, line_id)
    session = db.get(models.FnbServiceSession, line.session_id) if line else None
    shop = db.get(models.Shop, session.shop_id) if session else None
    if line is None or shop is None or not has_shop_operator_access(shop, current_user):
        raise fnb_error(404, "FNB_LINE_NOT_FOUND", "Không tìm thấy món")
    require_staff_permission(current_user, PERMISSION_FNB_SERVICE)
    return line, session


def _require_open(session: models.FnbServiceSession) -> None:
    if session.status != "OPEN":
        raise fnb_error(409, "FNB_SESSION_NOT_OPEN", "Phiên phục vụ không còn mở")


def _require_table_version(
    table: models.FnbTable, expected: int, code: str = "FNB_TABLE_CHANGED"
) -> None:
    if int(table.state_version or 0) != int(expected):
        raise fnb_error(
            409,
            code,
            "Bàn vừa được cập nhật",
            state_version=int(table.state_version or 0),
        )


def _normalize_note(note: str | None) -> str | None:
    normalized = " ".join(note.strip().split()) if note else ""
    return normalized or None


def _session_result_finish(
    db: Session,
    current_user: models.User,
    session: models.FnbServiceSession,
    action: str,
    operation_id: str,
    fingerprint: str,
    *,
    before=None,
    reason: str | None = None,
) -> dict:
    db.flush()
    result = serialize_session(db, session)
    return _finish(
        db,
        current_user,
        action,
        operation_id,
        fingerprint,
        result,
        session_id=session.id,
        before=before,
        after=result,
        reason=reason,
    )


def open_session(
    db: Session, current_user: models.User, request: FnbSessionOpen
) -> dict:
    action = "FNB_SESSION_OPEN"
    fingerprint = operation_fingerprint(action, _payload(request))
    try:
        require_fnb_access(db, request.shop_id, current_user, PERMISSION_FNB_SERVICE)
        _prepare_locked_shop(db, request.shop_id)
        shop = require_fnb_access(
            db, request.shop_id, current_user, PERMISSION_FNB_SERVICE
        )
        existing = _existing_operation(
            db, request.shop_id, request.operation_id, fingerprint
        )
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        require_floor_revision(shop, request.expected_revision)
        table = (
            db.query(models.FnbTable)
            .filter(
                models.FnbTable.id == request.table_id,
                models.FnbTable.shop_id == request.shop_id,
            )
            .first()
        )
        if table is None:
            raise fnb_error(404, "FNB_TABLE_NOT_FOUND", "Không tìm thấy bàn")
        area = db.get(models.FnbArea, table.area_id)
        if not bool(table.active) or area is None or not bool(area.active):
            raise fnb_error(409, "FNB_TABLE_INACTIVE", "Bàn đã ngừng hoạt động")
        _require_table_version(table, request.expected_table_version)
        if _table_has_active_session(db, table.id):
            raise fnb_error(409, "FNB_TABLE_OCCUPIED", "Bàn đang phục vụ")
        session = models.FnbServiceSession(
            shop_id=shop.id,
            status="OPEN",
            revision=0,
            opened_by_user_id=current_user.id,
        )
        db.add(session)
        db.flush()
        db.add(models.FnbSessionTable(session_id=session.id, table_id=table.id))
        table.state_version = int(table.state_version or 0) + 1
        table.updated_at = datetime.datetime.utcnow()
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db, current_user, session, action, request.operation_id, fingerprint
        )
    except Exception:
        db.rollback()
        raise


def get_session(
    db: Session, current_user: models.User, session_id: int
) -> dict:
    session = _session_for_access(db, current_user, session_id)
    require_fnb_shop(db, session.shop_id, current_user)
    return serialize_session(db, session)


def add_line(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbLineCreate,
) -> dict:
    action = "FNB_LINE_ADD"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        session = _session_for_access(db, current_user, session_id)
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        session = _session_for_access(db, current_user, session_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        product = (
            db.query(models.Product)
            .filter(
                models.Product.id == request.product_id,
                models.Product.shop_id == shop_id,
            )
            .first()
        )
        if product is None:
            raise fnb_error(404, "FNB_PRODUCT_NOT_FOUND", "Không tìm thấy món")
        if not bool(product.is_active):
            raise fnb_error(409, "FNB_PRODUCT_INACTIVE", "Món đã ngừng bán")
        try:
            price = checked_vnd(product.price)
        except ValueError as exc:
            raise fnb_error(400, "FNB_INVALID_PRICE", "Giá món không hợp lệ") from exc
        before = serialize_session(db, session)
        db.add(
            models.FnbSessionLine(
                session_id=session.id,
                product_id=product.id,
                product_name=product.name,
                unit_price_vnd=price,
                station=product.fnb_station,
                note=_normalize_note(request.note),
                quantity=request.quantity,
                cancelled_quantity=0,
                created_by_user_id=current_user.id,
            )
        )
        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db,
            current_user,
            session,
            action,
            request.operation_id,
            fingerprint,
            before=before,
        )
    except Exception:
        db.rollback()
        raise


def _ticket_result(db: Session, ticket: models.FnbKitchenTicket) -> dict:
    items = (
        db.query(models.FnbKitchenTicketItem)
        .filter(models.FnbKitchenTicketItem.ticket_id == ticket.id)
        .order_by(models.FnbKitchenTicketItem.id)
        .all()
    )
    session = db.get(models.FnbServiceSession, ticket.session_id)
    tables = [row["name"] for row in serialize_session(db, session)["tables"]]
    return {
        "id": ticket.id,
        "shop_id": ticket.shop_id,
        "session_id": ticket.session_id,
        "station": ticket.station,
        "sequence": int(ticket.sequence),
        "status": ticket.status,
        "state_version": int(ticket.state_version or 0),
        "out_of_stock_reason": ticket.out_of_stock_reason,
        "created_at": ticket.created_at.isoformat() + "Z",
        "tables": tables,
        "items": [
            {
                "id": item.id,
                "line_id": item.session_line_id,
                "product_name": item.product_name,
                "quantity": int(item.quantity) - int(item.cancelled_quantity or 0),
                "original_quantity": int(item.quantity),
                "cancelled_quantity": int(item.cancelled_quantity or 0),
                "note": item.note,
            }
            for item in items
            if int(item.quantity) > int(item.cancelled_quantity or 0)
        ],
    }


def send_session(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbSessionSend,
) -> dict:
    action = "FNB_SESSION_SEND"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        session = _session_for_access(db, current_user, session_id)
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        session = _session_for_access(db, current_user, session_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        lines = (
            db.query(models.FnbSessionLine)
            .filter(models.FnbSessionLine.session_id == session.id)
            .order_by(models.FnbSessionLine.id)
            .all()
        )
        pending = []
        wanted: dict[int, int] = {}
        products: dict[int, models.Product] = {}
        for line in lines:
            quantity = (
                int(line.quantity)
                - int(line.sent_quantity or 0)
                - int(line.cancelled_quantity or 0)
                + int(line.sent_cancelled_quantity or 0)
            )
            if quantity <= 0:
                continue
            product = (
                db.query(models.Product)
                .filter(
                    models.Product.id == line.product_id,
                    models.Product.shop_id == shop_id,
                )
                .first()
            )
            if product is None:
                raise fnb_error(409, "FNB_PRODUCT_MISSING", "Món nguồn không còn tồn tại")
            pending.append((line, product, quantity))
            products[product.id] = product
            wanted[product.id] = wanted.get(product.id, 0) + quantity
        if not pending:
            raise fnb_error(409, "FNB_NOTHING_TO_SEND", "Không có món mới để gửi")
        for product_id, quantity in wanted.items():
            available = inventory_service.ton_kha_dung(db, products[product_id])
            if available < quantity:
                raise fnb_error(
                    409,
                    "FNB_STOCK_SHORTAGE",
                    "Món không đủ tồn kho để gửi",
                    product_id=product_id,
                    product_name=products[product_id].name,
                    requested=quantity,
                    available=available,
                )

        before = serialize_session(db, session)
        ticket_by_station: dict[str, models.FnbKitchenTicket] = {}
        for station in sorted({line.station for line, _, _ in pending} & {"KITCHEN", "BAR"}):
            sequence = int(
                db.query(func.max(models.FnbKitchenTicket.sequence))
                .filter(
                    models.FnbKitchenTicket.shop_id == shop_id,
                    models.FnbKitchenTicket.station == station,
                )
                .scalar()
                or 0
            ) + 1
            ticket = models.FnbKitchenTicket(
                shop_id=shop_id,
                session_id=session.id,
                station=station,
                sequence=sequence,
                status="NEW",
                operation_id=request.operation_id,
                created_by_user_id=current_user.id,
            )
            db.add(ticket)
            db.flush()
            ticket_by_station[station] = ticket

        for line, product, quantity in pending:
            ticket_item = None
            ticket = ticket_by_station.get(line.station)
            if ticket is not None:
                ticket_item = models.FnbKitchenTicketItem(
                    ticket_id=ticket.id,
                    session_line_id=line.id,
                    quantity=quantity,
                    product_name=line.product_name,
                    note=line.note,
                )
                db.add(ticket_item)
                db.flush()
            allocations = inventory_service.deduct_stock(db, [(product, quantity)])[product.id]
            for allocation in allocations:
                db.add(
                    models.FnbStockAllocation(
                        shop_id=shop_id,
                        session_id=session.id,
                        session_line_id=line.id,
                        ticket_item_id=ticket_item.id if ticket_item else None,
                        product_id=product.id,
                        batch_id=allocation.batch.id if allocation.batch else None,
                        quantity=allocation.quantity,
                        cost_known_qty=allocation.known_qty,
                        cost_unknown_qty=allocation.unknown_qty,
                        cost_basis_vnd=allocation.cost_basis_vnd,
                        state="CONSUMED",
                        operation_id=request.operation_id,
                    )
                )
            line.sent_quantity = int(line.sent_quantity or 0) + quantity
            line.state_version = int(line.state_version or 0) + 1

        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = serialize_session(db, session)
        result["tickets"] = [
            _ticket_result(db, ticket) for ticket in ticket_by_station.values()
        ]
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            session_id=session.id,
            before=before,
            after=result,
        )
    except Exception:
        db.rollback()
        raise


def get_station_tickets(
    db: Session,
    current_user: models.User,
    shop_id: int,
    station: str,
    after_revision: int | None = None,
) -> dict:
    station = station.upper()
    permission = {
        "KITCHEN": PERMISSION_FNB_KITCHEN,
        "BAR": PERMISSION_FNB_BAR,
    }.get(station)
    if permission is None:
        raise fnb_error(400, "FNB_STATION_INVALID", "Khu chế biến không hợp lệ")
    shop = require_fnb_access(db, shop_id, current_user, permission)
    if not bool(shop.fnb_enabled):
        raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
    revision = int(shop.fnb_revision or 0)
    if after_revision is not None and int(after_revision) == revision:
        return {"changed": False, "station": station, "revision": revision}
    tickets = (
        db.query(models.FnbKitchenTicket)
        .filter(
            models.FnbKitchenTicket.shop_id == shop_id,
            models.FnbKitchenTicket.station == station,
            models.FnbKitchenTicket.status.in_(("NEW", "IN_PROGRESS")),
        )
        .order_by(models.FnbKitchenTicket.sequence)
        .all()
    )
    return {
        "changed": True,
        "shop_id": shop_id,
        "station": station,
        "revision": revision,
        "tickets": [_ticket_result(db, ticket) for ticket in tickets],
    }


def transition_ticket(
    db: Session,
    current_user: models.User,
    ticket_id: int,
    transition: str,
    request: FnbTicketTransition,
) -> dict:
    transitions = {
        "start": ("FNB_TICKET_START", "NEW", "IN_PROGRESS"),
        "done": ("FNB_TICKET_DONE", "IN_PROGRESS", "DONE"),
        "out-of-stock": ("FNB_TICKET_OUT_OF_STOCK", None, None),
    }
    if transition not in transitions:
        raise fnb_error(400, "FNB_TICKET_ACTION_INVALID", "Thao tác phiếu không hợp lệ")
    action, required_status, next_status = transitions[transition]
    fingerprint = operation_fingerprint(
        action, _payload(request, ticket_id=ticket_id)
    )
    try:
        ticket = db.get(models.FnbKitchenTicket, ticket_id)
        if ticket is None:
            raise fnb_error(404, "FNB_TICKET_NOT_FOUND", "Không tìm thấy phiếu")
        shop_id = int(ticket.shop_id)
        permission = (
            PERMISSION_FNB_KITCHEN
            if ticket.station == "KITCHEN"
            else PERMISSION_FNB_BAR
        )
        require_fnb_access(db, shop_id, current_user, permission)
        _prepare_locked_shop(db, shop_id)
        shop = require_fnb_access(db, shop_id, current_user, permission)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        ticket = (
            db.query(models.FnbKitchenTicket)
            .filter(
                models.FnbKitchenTicket.id == ticket_id,
                models.FnbKitchenTicket.shop_id == shop_id,
            )
            .first()
        )
        if ticket is None:
            raise fnb_error(404, "FNB_TICKET_NOT_FOUND", "Không tìm thấy phiếu")
        if int(ticket.state_version or 0) != request.expected_state_version:
            raise fnb_error(
                409,
                "FNB_TICKET_CHANGED",
                "Phiếu vừa được cập nhật",
                state_version=int(ticket.state_version or 0),
                snapshot=_ticket_result(db, ticket),
            )
        if transition == "out-of-stock":
            reason = _normalize_note(request.reason)
            if not reason:
                raise fnb_error(400, "FNB_REASON_REQUIRED", "Cần nhập lý do hết món")
            if ticket.status not in ("NEW", "IN_PROGRESS"):
                raise fnb_error(409, "FNB_TICKET_CLOSED", "Phiếu đã hoàn tất")
            ticket.out_of_stock_reason = reason
        else:
            if request.reason is not None:
                raise fnb_error(400, "FNB_REASON_NOT_ALLOWED", "Thao tác này không cần lý do")
            if ticket.status != required_status:
                raise fnb_error(409, "FNB_TICKET_STATE_INVALID", "Trạng thái phiếu không phù hợp")
            ticket.status = next_status
            now = datetime.datetime.utcnow()
            if transition == "start":
                ticket.started_by_user_id = current_user.id
                ticket.started_at = now
            else:
                ticket.done_by_user_id = current_user.id
                ticket.done_at = now
        ticket.state_version = int(ticket.state_version or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = _ticket_result(db, ticket)
        result["revision"] = int(shop.fnb_revision or 0)
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            session_id=ticket.session_id,
            after=result,
            reason=ticket.out_of_stock_reason if transition == "out-of-stock" else None,
        )
    except Exception:
        db.rollback()
        raise


def update_line(
    db: Session,
    current_user: models.User,
    line_id: int,
    request: FnbLineUpdate,
) -> dict:
    action = "FNB_LINE_UPDATE"
    fingerprint = operation_fingerprint(action, _payload(request, line_id=line_id))
    try:
        _, session = _line_for_access(db, current_user, line_id)
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        line, session = _line_for_access(db, current_user, line_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        if int(line.state_version or 0) != request.expected_line_version:
            raise fnb_error(
                409,
                "FNB_LINE_CHANGED",
                "Món vừa được cập nhật",
                state_version=int(line.state_version or 0),
                snapshot=serialize_session(db, session),
            )
        if int(line.sent_quantity or 0) > 0:
            raise fnb_error(409, "FNB_LINE_ALREADY_SENT", "Món đã gửi không thể sửa")
        if request.quantity < int(line.cancelled_quantity or 0):
            raise fnb_error(
                409, "FNB_QUANTITY_CANCELLED", "Số lượng thấp hơn phần đã hủy"
            )
        before = serialize_session(db, session)
        line.quantity = request.quantity
        line.note = _normalize_note(request.note)
        line.state_version = int(line.state_version or 0) + 1
        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db,
            current_user,
            session,
            action,
            request.operation_id,
            fingerprint,
            before=before,
        )
    except Exception:
        db.rollback()
        raise


def _sent_allocation_parts(
    db: Session, line_id: int, quantity: int
) -> list[tuple[models.FnbStockAllocation, int]]:
    rows = (
        db.query(models.FnbStockAllocation)
        .filter(
            models.FnbStockAllocation.session_line_id == line_id,
            models.FnbStockAllocation.state == "CONSUMED",
        )
        .order_by(models.FnbStockAllocation.id)
        .all()
    )
    parts = []
    remaining = quantity
    for row in rows:
        take = min(remaining, int(row.quantity))
        if take:
            parts.append((row, take))
            remaining -= take
        if not remaining:
            break
    if remaining:
        raise fnb_error(409, "FNB_ALLOCATION_MISMATCH", "Phân bổ tồn món bị lệch")
    return parts


def _approval_for_sent_cancel(
    db: Session,
    current_user: models.User,
    session: models.FnbServiceSession,
    token: str | None,
) -> models.FnbManagerApproval:
    if not token:
        raise fnb_error(403, "FNB_APPROVAL_REQUIRED", "Cần PIN quản lý để hủy món đang làm")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    approval = (
        db.query(models.FnbManagerApproval)
        .filter(
            models.FnbManagerApproval.token_hash == token_hash,
            models.FnbManagerApproval.shop_id == session.shop_id,
            models.FnbManagerApproval.actor_user_id == current_user.id,
            models.FnbManagerApproval.action == "CANCEL_SENT_LINE",
            models.FnbManagerApproval.entity_type == "SESSION",
            models.FnbManagerApproval.entity_id == session.id,
            models.FnbManagerApproval.revision == session.revision,
            models.FnbManagerApproval.used_at.is_(None),
            models.FnbManagerApproval.expires_at > datetime.datetime.utcnow(),
        )
        .first()
    )
    if approval is None:
        raise fnb_error(403, "FNB_APPROVAL_INVALID", "Lượt duyệt không còn hợp lệ")
    approval.used_at = datetime.datetime.utcnow()
    return approval


def _resolve_sent_allocations(
    db: Session,
    parts: list[tuple[models.FnbStockAllocation, int]],
    resolution: str,
    reason: str | None,
    operation_id: str,
) -> None:
    now = datetime.datetime.utcnow()
    allocation_state = "RESTOCKED" if resolution == "RESTOCK" else resolution
    for row, take in parts:
        unknown_take = min(take, int(row.cost_unknown_qty or 0))
        known_take = take - unknown_take
        basis_take = (
            cumulative_basis(
                int(row.cost_basis_vnd or 0),
                int(row.cost_known_qty or 0),
                known_take,
            )
            if known_take
            else 0
        )
        terminal = row
        if take < int(row.quantity):
            row.quantity = int(row.quantity) - take
            row.cost_known_qty = int(row.cost_known_qty or 0) - known_take
            row.cost_unknown_qty = int(row.cost_unknown_qty or 0) - unknown_take
            row.cost_basis_vnd = int(row.cost_basis_vnd or 0) - basis_take
            terminal = models.FnbStockAllocation(
                shop_id=row.shop_id,
                session_id=row.session_id,
                session_line_id=row.session_line_id,
                ticket_item_id=row.ticket_item_id,
                product_id=row.product_id,
                batch_id=row.batch_id,
                quantity=take,
                cost_known_qty=known_take,
                cost_unknown_qty=unknown_take,
                cost_basis_vnd=basis_take,
                operation_id=operation_id,
            )
            db.add(terminal)
        terminal.state = allocation_state
        terminal.resolved_at = now
        terminal.resolution_reason = reason
        if row.ticket_item_id is not None:
            item = db.get(models.FnbKitchenTicketItem, row.ticket_item_id)
            item.cancelled_quantity = int(item.cancelled_quantity or 0) + take
        if resolution != "RESTOCK":
            continue
        product = db.get(models.Product, row.product_id)
        if product is None or product.shop_id != row.shop_id:
            raise fnb_error(409, "FNB_PRODUCT_MISSING", "Món nguồn không còn tồn tại")
        if int(product.stock or 0) > MAX_SAFE_QUANTITY - take:
            raise fnb_error(409, "FNB_STOCK_OVERFLOW", "Tồn kho sau hoàn vượt giới hạn")
        source = product
        if row.batch_id is not None:
            source = db.get(models.ProductBatch, row.batch_id)
            if source is None or source.product_id != product.id:
                raise fnb_error(409, "FNB_BATCH_MISSING", "Lô nguồn không còn tồn tại")
            if int(source.quantity or 0) > MAX_SAFE_QUANTITY - take:
                raise fnb_error(409, "FNB_STOCK_OVERFLOW", "Tồn lô sau hoàn vượt giới hạn")
        inventory_service.restore_cost_pool(source, known_take, unknown_take, basis_take)
        if row.batch_id is not None:
            source.quantity = int(source.quantity or 0) + take
        product.stock = int(product.stock or 0) + take


def cancel_line(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbLineCancel,
) -> dict:
    action = "FNB_LINE_CANCEL"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        session = _session_for_access(db, current_user, session_id)
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        session = _session_for_access(db, current_user, session_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        line = (
            db.query(models.FnbSessionLine)
            .filter(
                models.FnbSessionLine.id == request.line_id,
                models.FnbSessionLine.session_id == session.id,
            )
            .first()
        )
        if line is None:
            raise fnb_error(404, "FNB_LINE_NOT_FOUND", "Không tìm thấy món")
        if int(line.state_version or 0) != request.expected_line_version:
            raise fnb_error(
                409,
                "FNB_LINE_CHANGED",
                "Món vừa được cập nhật",
                state_version=int(line.state_version or 0),
                snapshot=serialize_session(db, session),
            )
        billable = int(line.quantity) - int(line.cancelled_quantity or 0)
        if request.quantity > billable:
            raise fnb_error(
                409, "FNB_CANCEL_EXCEEDS_QUANTITY", "Số lượng hủy vượt phần còn lại"
            )
        before = serialize_session(db, session)
        unsent = (
            int(line.quantity)
            - int(line.sent_quantity or 0)
            - int(line.cancelled_quantity or 0)
            + int(line.sent_cancelled_quantity or 0)
        )
        sent_to_cancel = max(0, int(request.quantity) - max(0, unsent))
        approval = None
        reason = _normalize_note(request.reason)
        if sent_to_cancel:
            parts = _sent_allocation_parts(db, line.id, sent_to_cancel)
            item_ids = [row.ticket_item_id for row, _ in parts if row.ticket_item_id]
            progressed = False
            if item_ids:
                progressed = (
                    db.query(models.FnbKitchenTicket.id)
                    .join(
                        models.FnbKitchenTicketItem,
                        models.FnbKitchenTicketItem.ticket_id == models.FnbKitchenTicket.id,
                    )
                    .filter(
                        models.FnbKitchenTicketItem.id.in_(item_ids),
                        models.FnbKitchenTicket.status.in_(("IN_PROGRESS", "DONE")),
                    )
                    .first()
                    is not None
                )
            if progressed:
                if request.resolution not in ("RESTOCK", "WASTE") or not reason:
                    raise fnb_error(
                        400,
                        "FNB_CANCELLATION_DECISION_REQUIRED",
                        "Cần chọn hoàn tồn hoặc hao hụt và nhập lý do",
                    )
                approval = _approval_for_sent_cancel(
                    db, current_user, session, request.approval_token
                )
                resolution = request.resolution
            else:
                resolution = "RESTOCK"
            _resolve_sent_allocations(
                db, parts, resolution, reason, request.operation_id
            )
        line.cancelled_quantity = int(line.cancelled_quantity or 0) + request.quantity
        line.sent_cancelled_quantity = (
            int(line.sent_cancelled_quantity or 0) + sent_to_cancel
        )
        line.state_version = int(line.state_version or 0) + 1
        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        db.flush()
        result = serialize_session(db, session)
        if approval is not None:
            result["manager_approval_id"] = approval.id
        return _finish(
            db,
            current_user,
            action,
            request.operation_id,
            fingerprint,
            result,
            session_id=session.id,
            before=before,
            after=result,
            reason=reason,
        )
    except Exception:
        db.rollback()
        raise


def move_table(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbMoveTable,
) -> dict:
    action = "FNB_TABLE_MOVE"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        session = _session_for_access(
            db, current_user, session_id, PERMISSION_FNB_MANAGE
        )
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        session = _session_for_access(
            db, current_user, session_id, PERMISSION_FNB_MANAGE
        )
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        source_link = (
            db.query(models.FnbSessionTable)
            .filter(
                models.FnbSessionTable.session_id == session.id,
                models.FnbSessionTable.table_id == request.from_table_id,
                models.FnbSessionTable.released_at.is_(None),
            )
            .first()
        )
        if source_link is None:
            raise fnb_error(
                409, "FNB_TABLE_NOT_ATTACHED", "Bàn nguồn không thuộc phiên phục vụ"
            )
        source = db.get(models.FnbTable, request.from_table_id)
        target = (
            db.query(models.FnbTable)
            .filter(
                models.FnbTable.id == request.to_table_id,
                models.FnbTable.shop_id == shop_id,
            )
            .first()
        )
        if target is None:
            raise fnb_error(404, "FNB_TABLE_NOT_FOUND", "Không tìm thấy bàn")
        area = db.get(models.FnbArea, target.area_id)
        if not bool(target.active) or area is None or not bool(area.active):
            raise fnb_error(409, "FNB_TABLE_INACTIVE", "Bàn đã ngừng hoạt động")
        _require_table_version(source, request.expected_from_state_version)
        _require_table_version(target, request.expected_to_state_version)
        if _table_has_active_session(db, target.id):
            raise fnb_error(409, "FNB_TABLE_OCCUPIED", "Bàn đang phục vụ")
        before = serialize_session(db, session)
        now = datetime.datetime.utcnow()
        source_link.released_at = now
        db.add(models.FnbSessionTable(session_id=session.id, table_id=target.id))
        for table in (source, target):
            table.state_version = int(table.state_version or 0) + 1
            table.updated_at = now
        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db,
            current_user,
            session,
            action,
            request.operation_id,
            fingerprint,
            before=before,
        )
    except Exception:
        db.rollback()
        raise


def session_has_only_r1a_drafts(
    db: Session, session: models.FnbServiceSession
) -> bool:
    # ponytail: R1A has no ticket/check tables; replace with explicit queries in R1B.
    return True


def merge_table(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbMergeTable,
) -> dict:
    action = "FNB_TABLE_MERGE"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        source = _session_for_access(
            db, current_user, session_id, PERMISSION_FNB_MANAGE
        )
        shop_id = int(source.shop_id)
        _prepare_locked_shop(db, shop_id)
        source = _session_for_access(
            db, current_user, session_id, PERMISSION_FNB_MANAGE
        )
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_MANAGE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(source)
        require_session_revision(db, source, request.expected_revision)
        target_table = (
            db.query(models.FnbTable)
            .filter(
                models.FnbTable.id == request.target_table_id,
                models.FnbTable.shop_id == shop_id,
            )
            .first()
        )
        if target_table is None:
            raise fnb_error(404, "FNB_TABLE_NOT_FOUND", "Không tìm thấy bàn")
        area = db.get(models.FnbArea, target_table.area_id)
        if not bool(target_table.active) or area is None or not bool(area.active):
            raise fnb_error(409, "FNB_TABLE_INACTIVE", "Bàn đã ngừng hoạt động")
        _require_table_version(target_table, request.expected_target_table_version)
        target_link = (
            db.query(models.FnbSessionTable)
            .filter(
                models.FnbSessionTable.table_id == target_table.id,
                models.FnbSessionTable.released_at.is_(None),
            )
            .first()
        )
        if target_link is not None and target_link.session_id == source.id:
            raise fnb_error(
                409, "FNB_TABLE_ALREADY_ATTACHED", "Bàn đã thuộc phiên phục vụ này"
            )
        before = serialize_session(db, source)
        now = datetime.datetime.utcnow()
        if target_link is None:
            db.add(models.FnbSessionTable(session_id=source.id, table_id=target_table.id))
            target_table.state_version = int(target_table.state_version or 0) + 1
            target_table.updated_at = now
        else:
            target = db.get(models.FnbServiceSession, target_link.session_id)
            if target is None or target.shop_id != shop_id:
                raise fnb_error(404, "FNB_SESSION_NOT_FOUND", "Không tìm thấy phiên phục vụ")
            _require_open(target)
            if request.expected_target_session_revision is None:
                raise fnb_error(
                    409,
                    "FNB_TARGET_REVISION_REQUIRED",
                    "Cần phiên bản mới nhất của bàn đích",
                )
            require_session_revision(
                db, target, request.expected_target_session_revision
            )
            if not session_has_only_r1a_drafts(db, target):
                raise fnb_error(
                    409,
                    "FNB_SESSION_HAS_FUTURE_ARTIFACTS",
                    "Phiên đích không thể gộp",
                )
            target_links = _active_links(db, target.id)
            for link in target_links:
                link.released_at = now
                db.add(
                    models.FnbSessionTable(
                        session_id=source.id, table_id=link.table_id
                    )
                )
                table = db.get(models.FnbTable, link.table_id)
                table.state_version = int(table.state_version or 0) + 1
                table.updated_at = now
            db.query(models.FnbSessionLine).filter(
                models.FnbSessionLine.session_id == target.id
            ).update({models.FnbSessionLine.session_id: source.id})
            target.status = "CANCELLED"
            target.merged_into_session_id = source.id
            target.closed_by_user_id = current_user.id
            target.closed_at = now
            target.revision = int(target.revision or 0) + 1
        source.revision = int(source.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db,
            current_user,
            source,
            action,
            request.operation_id,
            fingerprint,
            before=before,
        )
    except Exception:
        db.rollback()
        raise


def cancel_session(
    db: Session,
    current_user: models.User,
    session_id: int,
    request: FnbSessionCancel,
) -> dict:
    action = "FNB_SESSION_CANCEL"
    fingerprint = operation_fingerprint(action, _payload(request, session_id=session_id))
    try:
        session = _session_for_access(db, current_user, session_id)
        shop_id = int(session.shop_id)
        _prepare_locked_shop(db, shop_id)
        session = _session_for_access(db, current_user, session_id)
        shop = require_fnb_access(db, shop_id, current_user, PERMISSION_FNB_SERVICE)
        existing = _existing_operation(db, shop_id, request.operation_id, fingerprint)
        if existing is not None:
            db.rollback()
            return existing
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
        _require_open(session)
        require_session_revision(db, session, request.expected_revision)
        if (
            db.query(models.FnbSessionLine.id)
            .filter(
                models.FnbSessionLine.session_id == session.id,
                models.FnbSessionLine.quantity
                > models.FnbSessionLine.cancelled_quantity,
            )
            .first()
            is not None
        ):
            raise fnb_error(
                409,
                "FNB_SESSION_NOT_EMPTY",
                "Hãy hủy hết số lượng món nháp trước khi hủy phiên",
            )
        before = serialize_session(db, session)
        now = datetime.datetime.utcnow()
        for link in _active_links(db, session.id):
            link.released_at = now
            table = db.get(models.FnbTable, link.table_id)
            table.state_version = int(table.state_version or 0) + 1
            table.updated_at = now
        session.status = "CANCELLED"
        session.closed_by_user_id = current_user.id
        session.closed_at = now
        session.revision = int(session.revision or 0) + 1
        shop.fnb_revision = int(shop.fnb_revision or 0) + 1
        return _session_result_finish(
            db,
            current_user,
            session,
            action,
            request.operation_id,
            fingerprint,
            before=before,
            reason=_normalize_note(request.reason),
        )
    except Exception:
        db.rollback()
        raise


def get_floor(
    db: Session,
    current_user: models.User,
    shop_id: int,
    after_revision: int | None = None,
    include_inactive: bool = False,
) -> dict:
    if include_inactive:
        shop = require_fnb_access(
            db, shop_id, current_user, PERMISSION_FNB_MANAGE
        )
        if not bool(shop.fnb_enabled):
            raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
    else:
        shop = require_fnb_shop(db, shop_id, current_user)
    revision = int(shop.fnb_revision or 0)
    if after_revision == revision:
        return {"changed": False, "fnb_revision": revision}
    area_query = db.query(models.FnbArea).filter(models.FnbArea.shop_id == shop_id)
    table_query = db.query(models.FnbTable).filter(models.FnbTable.shop_id == shop_id)
    if not include_inactive:
        area_query = area_query.filter(models.FnbArea.active.is_(True))
        table_query = table_query.filter(models.FnbTable.active.is_(True))
    areas = area_query.order_by(models.FnbArea.sort_order, models.FnbArea.id).all()
    tables = table_query.order_by(models.FnbTable.sort_order, models.FnbTable.id).all()
    by_area: dict[int, list[models.FnbTable]] = {}
    for table in tables:
        by_area.setdefault(table.area_id, []).append(table)
    links = (
        db.query(models.FnbSessionTable, models.FnbServiceSession)
        .join(
            models.FnbServiceSession,
            models.FnbServiceSession.id == models.FnbSessionTable.session_id,
        )
        .filter(
            models.FnbSessionTable.table_id.in_([table.id for table in tables]),
            models.FnbSessionTable.released_at.is_(None),
            models.FnbServiceSession.status.in_(_ACTIVE_SESSION_STATUSES),
        )
        .all()
        if tables
        else []
    )
    occupied = {link.table_id: session for link, session in links}
    summaries = {}
    for session in occupied.values():
        if session.id not in summaries:
            snapshot = serialize_session(db, session)
            summaries[session.id] = {
                "id": session.id,
                "revision": int(session.revision or 0),
                "opened_at": session.opened_at.isoformat() + "Z",
                "subtotal_vnd": snapshot["subtotal_vnd"],
                "unsent_quantity": snapshot["unsent_quantity"],
                "table_count": len(snapshot["tables"]),
            }
    return {
        "changed": True,
        "shop_id": shop.id,
        "fnb_revision": revision,
        "areas": [
            {
                "id": area.id,
                "name": area.name,
                "sort_order": int(area.sort_order),
                **({"active": bool(area.active)} if include_inactive else {}),
                "tables": [
                    {
                        "id": table.id,
                        "name": table.name,
                        **({"active": bool(table.active)} if include_inactive else {}),
                        **(
                            {"sort_order": int(table.sort_order)}
                            if include_inactive
                            else {}
                        ),
                        "state_version": int(table.state_version or 0),
                        "state": "SERVING" if table.id in occupied else "EMPTY",
                        "session": (
                            summaries[occupied[table.id].id]
                            if table.id in occupied
                            else None
                        ),
                    }
                    for table in by_area.get(area.id, [])
                ],
            }
            for area in areas
        ],
    }
