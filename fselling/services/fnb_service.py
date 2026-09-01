from __future__ import annotations

import datetime
import hashlib
import json
import unicodedata

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..core.money import checked_add, checked_multiply, checked_vnd
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
    FnbLineCancel,
    FnbLineCreate,
    FnbLineUpdate,
    FnbMergeTable,
    FnbMoveTable,
    FnbSessionCancel,
    FnbSessionOpen,
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
            "note": line.note,
            "quantity": int(line.quantity),
            "cancelled_quantity": int(line.cancelled_quantity or 0),
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
        "unsent_quantity": sum(
            line["billable_quantity"] for line in serialized_lines
        ),
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
    if line is None:
        raise fnb_error(404, "FNB_LINE_NOT_FOUND", "Không tìm thấy món")
    session = _session_for_access(db, current_user, line.session_id)
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
        line.cancelled_quantity = int(line.cancelled_quantity or 0) + request.quantity
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
                "tables": [
                    {
                        "id": table.id,
                        "name": table.name,
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
