from __future__ import annotations

import datetime
import hashlib
import json
import unicodedata

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..dependencies import (
    PERMISSION_FNB_MANAGE,
    PERMISSION_FNB_SERVICE,
    has_shop_operator_access,
    require_own_shop,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.fnb import (
    FnbAreaCreate,
    FnbAreaUpdate,
    FnbSettingsUpdate,
    FnbTableCreate,
    FnbTableUpdate,
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
    before=None,
    after=None,
) -> dict:
    _record_operation(
        db,
        shop_id=result["shop_id"],
        session_id=None,
        actor_user_id=current_user.id,
        action=action,
        operation_id=operation_id,
        fingerprint=fingerprint,
        result=result,
        before=before,
        after=after,
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


def get_floor(
    db: Session,
    current_user: models.User,
    shop_id: int,
    after_revision: int | None = None,
) -> dict:
    shop = require_fnb_shop(db, shop_id, current_user)
    revision = int(shop.fnb_revision or 0)
    if after_revision == revision:
        return {"changed": False, "fnb_revision": revision}
    areas = (
        db.query(models.FnbArea)
        .filter(
            models.FnbArea.shop_id == shop_id,
            models.FnbArea.active.is_(True),
        )
        .order_by(models.FnbArea.sort_order, models.FnbArea.id)
        .all()
    )
    tables = (
        db.query(models.FnbTable)
        .filter(
            models.FnbTable.shop_id == shop_id,
            models.FnbTable.active.is_(True),
        )
        .order_by(models.FnbTable.sort_order, models.FnbTable.id)
        .all()
    )
    by_area: dict[int, list[models.FnbTable]] = {}
    for table in tables:
        by_area.setdefault(table.area_id, []).append(table)
    return {
        "changed": True,
        "shop_id": shop.id,
        "fnb_revision": revision,
        "areas": [
            {
                "id": area.id,
                "name": area.name,
                "sort_order": int(area.sort_order),
                "tables": [
                    {
                        "id": table.id,
                        "name": table.name,
                        "state_version": int(table.state_version or 0),
                        "state": "EMPTY",
                        "session": None,
                    }
                    for table in by_area.get(area.id, [])
                ],
            }
            for area in areas
        ],
    }
