"""Nghiệp vụ chương trình khách thân thiết và sổ điểm.

Điểm được dựng lại từ ledger theo thứ tự thời gian. Dòng dương tạo một lô;
dòng âm dùng lô hết hạn sớm nhất trước (FEFO). Nếu phải trừ nhiều hơn số đang
có, phần thiếu trở thành nợ điểm âm và các lần cộng sau bù nợ trước khi tạo lô
mới. Module này không import order/return service để giữ phụ thuộc một chiều.
"""
from __future__ import annotations

import datetime
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.i18n import tr
from ..dependencies import (
    PERMISSION_CUSTOMER,
    PERMISSION_SALE,
    require_any_staff_permission,
    require_own_shop,
    require_shop_access,
)
from ..models.customer import Customer
from ..models.loyalty import LoyaltyPointEntry, LoyaltyProgram
from ..models.system_log import SystemLog
from ..models.user import User
from ..schemas.loyalty import LoyaltyProgramUpdate

ENTRY_EARN = "EARN"
ENTRY_REDEEM = "REDEEM"
ENTRY_CANCEL_RESTORE = "CANCEL_RESTORE"
ENTRY_RETURN_RESTORE = "RETURN_RESTORE"
ENTRY_RETURN_REVERSE = "RETURN_REVERSE"

_PROGRAM_FIELDS = (
    "enabled",
    "earn_amount",
    "earn_points",
    "redeem_points",
    "redeem_amount",
    "min_redeem_points",
    "max_redeem_percent",
    "expiry_days",
)
_RATIO_FIELDS = ("earn_amount", "earn_points", "redeem_points", "redeem_amount")


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=tr(message))


def _lock_shop_for_program_update(
    db: Session, shop_id: int, owner_id: int
) -> None:
    """Tuần tự hóa lần lưu cấu hình với nút xóa shop trên SQLite."""
    locked = db.execute(
        text(
            "UPDATE shops SET id = id "
            "WHERE id = :shop_id AND owner_id = :owner_id"
        ),
        {"shop_id": shop_id, "owner_id": owner_id},
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy cửa hàng"))


def get_program_model(db: Session, shop_id: int) -> Optional[LoyaltyProgram]:
    """Lấy model cấu hình; không tự tạo và không commit."""
    return (
        db.query(LoyaltyProgram)
        .filter(LoyaltyProgram.shop_id == shop_id)
        .first()
    )


def program_to_dict(
    program: Optional[LoyaltyProgram], shop_id: Optional[int] = None
) -> Dict:
    """Đổi cấu hình thành JSON rõ ràng, kể cả khi shop chưa từng lưu.

    Dòng chưa tồn tại được trình bày là chương trình đang tắt với bốn tỷ lệ
    ``null``. Như vậy migration không âm thầm chọn một chính sách tiền cho shop.
    """
    if program is None:
        return {
            "id": None,
            "shop_id": shop_id,
            "enabled": False,
            "earn_amount": None,
            "earn_points": None,
            "redeem_points": None,
            "redeem_amount": None,
            "min_redeem_points": 0,
            "max_redeem_percent": 100.0,
            "expiry_days": None,
            "updated_by_user_id": None,
            "updated_at": None,
        }
    return {
        "id": program.id,
        "shop_id": program.shop_id,
        "enabled": bool(program.enabled),
        "earn_amount": program.earn_amount,
        "earn_points": program.earn_points,
        "redeem_points": program.redeem_points,
        "redeem_amount": program.redeem_amount,
        "min_redeem_points": int(program.min_redeem_points or 0),
        "max_redeem_percent": float(program.max_redeem_percent),
        "expiry_days": program.expiry_days,
        "updated_by_user_id": program.updated_by_user_id,
        "updated_at": program.updated_at,
    }


def _program_value(program, name: str, default=None):
    if program is None:
        return default
    if isinstance(program, Mapping):
        return program.get(name, default)
    return getattr(program, name, default)


def _positive_finite(value, message: str) -> float:
    if isinstance(value, bool):
        raise _bad_request(message)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _bad_request(message)
    if not math.isfinite(number) or number <= 0:
        raise _bad_request(message)
    return number


def _integer(value, message: str, *, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad_request(message)
    if minimum is not None and value < minimum:
        raise _bad_request(message)
    return value


def _validated_program_values(program, changes: Mapping) -> Dict:
    values = {
        "enabled": bool(_program_value(program, "enabled", False)),
        "earn_amount": _program_value(program, "earn_amount"),
        "earn_points": _program_value(program, "earn_points"),
        "redeem_points": _program_value(program, "redeem_points"),
        "redeem_amount": _program_value(program, "redeem_amount"),
        "min_redeem_points": _program_value(program, "min_redeem_points", 0),
        "max_redeem_percent": _program_value(
            program, "max_redeem_percent", 100.0
        ),
        "expiry_days": _program_value(program, "expiry_days"),
    }
    values.update(changes)

    if not isinstance(values["enabled"], bool):
        raise _bad_request("Trạng thái chương trình tích điểm không hợp lệ")

    for field, message in (
        ("earn_amount", "Số tiền để cộng điểm phải lớn hơn 0"),
        ("redeem_amount", "Số tiền được giảm phải lớn hơn 0"),
    ):
        if values[field] is not None:
            values[field] = _positive_finite(values[field], message)

    for field, message in (
        ("earn_points", "Số điểm được cộng phải là số nguyên lớn hơn 0"),
        ("redeem_points", "Số điểm quy đổi phải là số nguyên lớn hơn 0"),
    ):
        if values[field] is not None:
            values[field] = _integer(values[field], message, minimum=1)

    if values["min_redeem_points"] is None:
        raise _bad_request("Số điểm tối thiểu không được để trống")
    values["min_redeem_points"] = _integer(
        values["min_redeem_points"],
        "Số điểm tối thiểu phải là số nguyên không âm",
        minimum=0,
    )

    if values["max_redeem_percent"] is None:
        raise _bad_request("Tỷ lệ dùng điểm tối đa không được để trống")
    max_percent = _positive_finite(
        values["max_redeem_percent"],
        "Tỷ lệ dùng điểm tối đa phải lớn hơn 0 và không quá 100%",
    )
    if max_percent > 100:
        raise _bad_request(
            "Tỷ lệ dùng điểm tối đa phải lớn hơn 0 và không quá 100%"
        )
    values["max_redeem_percent"] = max_percent

    if values["expiry_days"] is not None:
        values["expiry_days"] = _integer(
            values["expiry_days"],
            "Số ngày hết hạn điểm phải là số nguyên từ 1 trở lên",
            minimum=1,
        )

    if values["enabled"] and any(values[field] is None for field in _RATIO_FIELDS):
        raise _bad_request(
            "Cần nhập đủ tỷ lệ cộng điểm và đổi điểm trước khi bật chương trình"
        )
    return values


def get_program(
    db: Session, current_user: User, shop_id: int
) -> Dict:
    """Chủ shop, thu ngân và quản lý được đọc; thủ kho bị từ chối."""
    require_shop_access(db, shop_id, current_user)
    require_any_staff_permission(
        current_user, PERMISSION_SALE, PERMISSION_CUSTOMER
    )
    return program_to_dict(get_program_model(db, shop_id), shop_id)


def update_program(
    db: Session,
    current_user: User,
    shop_id: int,
    data: LoyaltyProgramUpdate,
) -> Dict:
    """Chỉ đúng chủ shop được thay đổi luật quy đổi tiền/điểm."""
    # Cùng hàng rào ``shops`` với tạo đơn và DELETE shop. Nếu lần lưu này tới
    # trước thì DELETE phải nhìn thấy LoyaltyProgram và bị chặn; nếu DELETE tới
    # trước thì UPDATE không được tạo một dòng cấu hình mồ côi sau đó. Lọc luôn
    # owner_id để giữ phản hồi 404 cũ mà không đọc trước lúc lấy write lock.
    _lock_shop_for_program_update(db, shop_id, current_user.id)
    require_own_shop(db, shop_id, current_user)
    program = get_program_model(db, shop_id)
    old_program = program_to_dict(program, shop_id)
    changes = data.model_dump(exclude_unset=True)
    unknown = set(changes).difference(_PROGRAM_FIELDS)
    if unknown:
        raise _bad_request("Cấu hình chương trình tích điểm không hợp lệ")
    values = _validated_program_values(program, changes)

    if program is None:
        program = LoyaltyProgram(shop_id=shop_id)
        db.add(program)
    for field, value in values.items():
        setattr(program, field, value)
    program.updated_by_user_id = current_user.id
    program.updated_at = datetime.datetime.utcnow()

    # Thay tỷ lệ là thay giá trị tiền tương lai của toàn bộ số điểm đang có.
    # Audit nằm trong CHÍNH transaction cấu hình để không thể có cảnh “đã đổi
    # tiền nhưng màn Ai Làm Gì không thấy” nếu một trong hai lần ghi lỗi.
    old_values = {field: old_program.get(field) for field in _PROGRAM_FIELDS}
    new_values = {field: values.get(field) for field in _PROGRAM_FIELDS}
    db.add(
        SystemLog(
            user_id=current_user.id,
            action="UPDATE_LOYALTY_PROGRAM",
            details=(
                f"Shop #{shop_id}: cấu hình tích điểm từ "
                f"{json.dumps(old_values, ensure_ascii=False, sort_keys=True)} "
                f"thành {json.dumps(new_values, ensure_ascii=False, sort_keys=True)}"
            ),
        )
    )

    db.commit()
    db.refresh(program)
    return program_to_dict(program)


def _decimal(value, message: str) -> Decimal:
    if isinstance(value, bool):
        raise _bad_request(message)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _bad_request(message)
    if not result.is_finite():
        raise _bad_request(message)
    return result


def calculate_redeem(
    program,
    balance: int,
    points_requested: int,
    amount_after_voucher: float,
) -> Dict:
    """Tính số điểm/thành tiền thực áp dụng, không ghi database.

    - Yêu cầu vượt số dư bị từ chối (không âm thầm dùng ít hơn khách yêu cầu).
    - Yêu cầu không tròn một block quy đổi được làm tròn xuống.
    - Nếu chỉ vượt trần % hóa đơn, tự hạ xuống block tối đa và trả cả hai con
      số để POS giải thích rõ cho thu ngân/khách.
    """
    requested = _integer(
        points_requested,
        "Số điểm muốn dùng phải là số nguyên không âm",
        minimum=0,
    )
    available = _integer(
        balance,
        "Số dư điểm không hợp lệ",
    )
    amount = _decimal(
        amount_after_voucher,
        "Số tiền sau voucher không hợp lệ",
    )
    if amount < 0:
        raise _bad_request("Số tiền sau voucher không được âm")

    if requested == 0:
        return {
            "requested_points": 0,
            "applied_points": 0,
            "discount": 0.0,
            "max_discount": 0.0,
            "remaining_balance": available,
        }
    if not bool(_program_value(program, "enabled", False)):
        raise _bad_request("Chương trình tích điểm đang tắt")
    if requested > available:
        raise _bad_request("Số điểm muốn dùng lớn hơn số dư hiện có")

    redeem_points = _integer(
        _program_value(program, "redeem_points"),
        "Tỷ lệ đổi điểm chưa được cấu hình hợp lệ",
        minimum=1,
    )
    redeem_amount = _decimal(
        _positive_finite(
            _program_value(program, "redeem_amount"),
            "Tỷ lệ đổi điểm chưa được cấu hình hợp lệ",
        ),
        "Tỷ lệ đổi điểm chưa được cấu hình hợp lệ",
    )
    max_percent = _decimal(
        _positive_finite(
            _program_value(program, "max_redeem_percent", 100.0),
            "Tỷ lệ dùng điểm tối đa không hợp lệ",
        ),
        "Tỷ lệ dùng điểm tối đa không hợp lệ",
    )
    if max_percent > 100:
        raise _bad_request("Tỷ lệ dùng điểm tối đa không hợp lệ")

    requested_blocks = requested // redeem_points
    max_discount = amount * max_percent / Decimal("100")
    cap_blocks = int(
        (max_discount / redeem_amount).to_integral_value(rounding=ROUND_FLOOR)
    )
    applied_blocks = min(requested_blocks, max(cap_blocks, 0))
    applied_points = applied_blocks * redeem_points

    minimum = _integer(
        _program_value(program, "min_redeem_points", 0),
        "Số điểm tối thiểu không hợp lệ",
        minimum=0,
    )
    if applied_points <= 0 or applied_points < minimum:
        raise _bad_request(
            "Số điểm có thể dùng cho hóa đơn này chưa đạt mức tối thiểu"
        )

    discount = redeem_amount * applied_blocks
    return {
        "requested_points": requested,
        "applied_points": applied_points,
        "discount": float(discount),
        "max_discount": float(max_discount),
        "remaining_balance": available - applied_points,
    }


def calculate_earn(program, amount_after_discounts: float) -> int:
    """Tính điểm nguyên được cộng; chương trình hiện đang tắt trả về 0."""
    if not bool(_program_value(program, "enabled", False)):
        return 0
    amount = _decimal(amount_after_discounts, "Số tiền tính điểm không hợp lệ")
    if amount <= 0:
        return 0
    earn_amount = _decimal(
        _positive_finite(
            _program_value(program, "earn_amount"),
            "Tỷ lệ cộng điểm chưa được cấu hình hợp lệ",
        ),
        "Tỷ lệ cộng điểm chưa được cấu hình hợp lệ",
    )
    earn_points = _integer(
        _program_value(program, "earn_points"),
        "Tỷ lệ cộng điểm chưa được cấu hình hợp lệ",
        minimum=1,
    )
    blocks = int((amount / earn_amount).to_integral_value(rounding=ROUND_FLOOR))
    return blocks * earn_points


def _utc_naive(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value


@dataclass
class _PointLot:
    remaining: int
    expires_at: Optional[datetime.datetime]
    created_at: datetime.datetime
    entry_id: int
    # Đơn đã SINH ra điểm này. RETURN_REVERSE dùng dấu vết này để không lấy
    # nhầm điểm của đơn khác chỉ vì lô kia hết hạn sớm hơn.
    origin_order_id: Optional[int] = None


@dataclass(frozen=True)
class _ConsumedSlice:
    """Một phần lô đã bị một đơn dùng điểm lấy đi theo FEFO."""

    points: int
    expires_at: Optional[datetime.datetime]
    origin_order_id: Optional[int]
    origin_entry_id: int


@dataclass
class _ReplayState:
    lots: List[_PointLot]
    debt: int
    running_after: Dict[int, int]
    # Các lát điểm mà từng đơn REDEEM đã dùng. CANCEL_RESTORE và
    # RETURN_RESTORE phát lại chính danh sách này, không đoán theo số dư hiện tại.
    redeemed_slices: Dict[int, List[_ConsumedSlice]]
    restore_offsets: Dict[Tuple[str, int], int]
    earned_by_order: Dict[int, int]
    spent_by_order: Dict[int, int]
    expired_by_order: Dict[int, int]
    reversed_by_order: Dict[int, int]


def _new_replay_state() -> _ReplayState:
    return _ReplayState(
        lots=[],
        debt=0,
        running_after={},
        redeemed_slices={},
        restore_offsets={},
        earned_by_order={},
        spent_by_order={},
        expired_by_order={},
        reversed_by_order={},
    )


def _cong(mapping: Dict[int, int], key: Optional[int], amount: int) -> None:
    if key is None or amount <= 0:
        return
    mapping[key] = int(mapping.get(key, 0)) + int(amount)


def _tru_toi_da(mapping: Dict[int, int], key: Optional[int], amount: int) -> int:
    """Trừ tối đa số đang có và trả số thực đã trừ."""
    if key is None or amount <= 0:
        return 0
    current = int(mapping.get(key, 0))
    removed = min(current, int(amount))
    if removed:
        mapping[key] = current - removed
    return removed


def _expire_lots(state: _ReplayState, moment: datetime.datetime) -> None:
    active: List[_PointLot] = []
    for lot in state.lots:
        if lot.expires_at is not None and lot.expires_at <= moment:
            # Chỉ phần thực sự còn nằm trong ví mới là "hết hạn chưa dùng".
            # Phần đã REDEEM nằm ở spent_by_order và không được miễn trừ khi
            # đơn nguồn bị trả lại.
            _cong(
                state.expired_by_order,
                lot.origin_order_id,
                int(lot.remaining),
            )
        else:
            active.append(lot)
    state.lots[:] = active


def _lot_sort_key(lot: _PointLot):
    # NULL = không hết hạn nên đi sau mọi lô có hạn.
    return (
        lot.expires_at is None,
        lot.expires_at or datetime.datetime.max,
        lot.created_at,
        lot.entry_id,
    )


def _apply_credit_slices(
    state: _ReplayState,
    entry: LoyaltyPointEntry,
    event_at: datetime.datetime,
    slices: Sequence[_ConsumedSlice],
) -> None:
    """Cộng các lát điểm; nợ âm luôn được bù trước khi tạo lô mới.

    ``slices`` giữ nguồn gốc của điểm. Với EARN caller truyền một lát mới;
    với RESTORE caller truyền đúng các lát mà đơn đó từng REDEEM.
    """
    entry_expiry = _utc_naive(entry.expires_at)
    remaining_delta = int(entry.points_delta or 0)
    prepared: List[_ConsumedSlice] = []
    for source in slices:
        if remaining_delta <= 0:
            break
        amount = min(int(source.points), remaining_delta)
        if amount <= 0:
            continue
        prepared.append(
            _ConsumedSlice(
                points=amount,
                expires_at=entry_expiry,
                origin_order_id=source.origin_order_id,
                origin_entry_id=source.origin_entry_id,
            )
        )
        remaining_delta -= amount

    # Dữ liệu legacy có thể không còn đủ dấu vết allocation. Không bịa nguồn
    # cho phần dư; số học ledger vẫn đúng nhưng RETURN_REVERSE sẽ không được
    # phép lấy phần này làm điểm của một đơn cụ thể.
    if remaining_delta > 0:
        prepared.append(
            _ConsumedSlice(
                points=remaining_delta,
                expires_at=entry_expiry,
                origin_order_id=None,
                origin_entry_id=int(entry.id or 0),
            )
        )

    for source in prepared:
        amount = int(source.points)
        paid_debt = min(amount, state.debt)
        state.debt -= paid_debt
        # Điểm của đơn nguồn đã được dùng để bù nợ cũng là điểm "đã tiêu".
        # Nếu sau này trả chính đơn nguồn, phần này được phép tạo số âm.
        _cong(state.spent_by_order, source.origin_order_id, paid_debt)
        remainder = amount - paid_debt
        if remainder <= 0:
            continue
        expiry = source.expires_at
        if expiry is not None and expiry <= event_at:
            _cong(state.expired_by_order, source.origin_order_id, remainder)
            continue
        state.lots.append(
            _PointLot(
                remaining=remainder,
                expires_at=expiry,
                created_at=event_at,
                entry_id=int(entry.id or 0),
                origin_order_id=source.origin_order_id,
            )
        )


def _consume_fefo(
    state: _ReplayState, needed: int
) -> List[_ConsumedSlice]:
    """Dùng điểm FEFO và trả allocation bất biến để các lần hoàn dựng lại."""
    consumed: List[_ConsumedSlice] = []
    state.lots.sort(key=_lot_sort_key)
    for lot in state.lots:
        if needed <= 0:
            break
        used = min(int(lot.remaining), needed)
        if used <= 0:
            continue
        lot.remaining -= used
        needed -= used
        _cong(state.spent_by_order, lot.origin_order_id, used)
        consumed.append(
            _ConsumedSlice(
                points=used,
                expires_at=lot.expires_at,
                origin_order_id=lot.origin_order_id,
                origin_entry_id=lot.entry_id,
            )
        )
    state.lots[:] = [lot for lot in state.lots if lot.remaining > 0]
    if needed > 0:
        # REDEEM mới bị add_entry chặn trước khi tới đây. Nhánh này chỉ giữ
        # phép phát lại dữ liệu cũ/corrupt có số học xác định.
        state.debt += needed
        consumed.append(
            _ConsumedSlice(
                points=needed,
                expires_at=None,
                origin_order_id=None,
                origin_entry_id=0,
            )
        )
    return consumed


def _slices_for_restore(
    state: _ReplayState,
    entry: LoyaltyPointEntry,
) -> List[_ConsumedSlice]:
    """Lấy phần kế tiếp của allocation REDEEM mà bút toán đang hoàn."""
    order_id = entry.order_id
    amount = int(entry.points_delta or 0)
    if order_id is None or amount <= 0:
        return []
    all_slices = state.redeemed_slices.get(int(order_id), [])
    key = (str(entry.entry_type or ""), int(order_id))
    offset = int(state.restore_offsets.get(key, 0))
    cursor = 0
    remaining = amount
    result: List[_ConsumedSlice] = []
    for source in all_slices:
        source_points = int(source.points)
        if cursor + source_points <= offset:
            cursor += source_points
            continue
        start = max(offset - cursor, 0)
        available = source_points - start
        take = min(available, remaining)
        if take > 0:
            result.append(
                _ConsumedSlice(
                    points=take,
                    # RETURN_RESTORE dùng hạn mới trên entry; CANCEL_RESTORE
                    # cũng đã chép hạn gốc lên entry khi ghi sổ.
                    expires_at=_utc_naive(entry.expires_at),
                    origin_order_id=source.origin_order_id,
                    origin_entry_id=source.origin_entry_id,
                )
            )
            _tru_toi_da(state.spent_by_order, source.origin_order_id, take)
            remaining -= take
        cursor += source_points
        if remaining <= 0:
            break
    state.restore_offsets[key] = offset + amount
    return result


def _reverse_source_order(
    state: _ReplayState,
    order_id: Optional[int],
    amount: int,
) -> None:
    """Thu hồi đúng điểm của đơn nguồn; tuyệt đối không ăn lô đơn khác."""
    if amount <= 0:
        return
    if order_id is None:
        state.debt += amount
        return

    needed = int(amount)
    applied = 0
    source_lots = sorted(
        (lot for lot in state.lots if lot.origin_order_id == order_id),
        key=_lot_sort_key,
    )
    for lot in source_lots:
        if needed <= 0:
            break
        removed = min(int(lot.remaining), needed)
        lot.remaining -= removed
        needed -= removed
        applied += removed
    state.lots[:] = [lot for lot in state.lots if lot.remaining > 0]

    if needed > 0:
        # Phần không còn trong ví nhưng chưa hết hạn-unused chính là phần đã
        # dùng. Trả đơn nguồn được phép biến phần này thành nợ điểm âm.
        spent = _tru_toi_da(state.spent_by_order, order_id, needed)
        state.debt += spent
        applied += spent
    # Nếu ledger cũ/corrupt đòi thu quá phần còn hợp lệ + đã dùng, phần điểm
    # hết hạn-unused được bỏ qua (quy tắc đã chốt), không được bịa thêm nợ.
    _cong(state.reversed_by_order, order_id, applied)


def _replay_state(
    entries: Sequence[LoyaltyPointEntry],
    as_of: Optional[datetime.datetime] = None,
) -> _ReplayState:
    moment = _utc_naive(as_of) or datetime.datetime.utcnow()
    state = _new_replay_state()

    for entry in entries:
        event_at = _utc_naive(entry.created_at) or datetime.datetime.min
        if event_at > moment:
            continue
        _expire_lots(state, event_at)
        delta = int(entry.points_delta or 0)
        kind = str(entry.entry_type or "").upper()

        if delta > 0:
            if kind == ENTRY_EARN:
                origin = int(entry.order_id) if entry.order_id is not None else None
                _cong(state.earned_by_order, origin, delta)
                sources = [
                    _ConsumedSlice(
                        points=delta,
                        expires_at=_utc_naive(entry.expires_at),
                        origin_order_id=origin,
                        origin_entry_id=int(entry.id or 0),
                    )
                ]
            elif kind in {ENTRY_CANCEL_RESTORE, ENTRY_RETURN_RESTORE}:
                sources = _slices_for_restore(state, entry)
            else:
                sources = []
            _apply_credit_slices(state, entry, event_at, sources)
        elif delta < 0 and kind == ENTRY_RETURN_REVERSE:
            _reverse_source_order(state, entry.order_id, -delta)
        elif delta < 0:
            consumed = _consume_fefo(state, -delta)
            if kind == ENTRY_REDEEM and entry.order_id is not None:
                state.redeemed_slices.setdefault(int(entry.order_id), []).extend(
                    consumed
                )

        state.running_after[int(entry.id or 0)] = (
            sum(lot.remaining for lot in state.lots) - state.debt
        )

    _expire_lots(state, moment)
    return state


def _replay_entries(
    entries: Sequence[LoyaltyPointEntry],
    as_of: Optional[datetime.datetime] = None,
) -> Tuple[int, Dict[int, int]]:
    state = _replay_state(entries, as_of)
    return (
        sum(lot.remaining for lot in state.lots) - state.debt,
        state.running_after,
    )


def _customer_entries(
    db: Session,
    shop_id: int,
    customer_id: int,
) -> List[LoyaltyPointEntry]:
    return (
        db.query(LoyaltyPointEntry)
        .filter(
            LoyaltyPointEntry.shop_id == shop_id,
            LoyaltyPointEntry.customer_id == customer_id,
        )
        .order_by(LoyaltyPointEntry.created_at, LoyaltyPointEntry.id)
        .all()
    )


def cancel_restore_plan(
    db: Session,
    shop_id: int,
    customer_id: int,
    order_id: int,
    *,
    as_of: Optional[datetime.datetime] = None,
) -> List[Tuple[int, Optional[datetime.datetime]]]:
    """Các lát REDEEM còn được hoàn khi hủy, theo đúng hạn ban đầu.

    Điểm có hạn đã qua tại lúc hủy bị bỏ qua. Offset lấy từ ledger giúp hàm
    an toàn cả khi gặp dữ liệu cũ đã có một phần CANCEL_RESTORE.
    """
    moment = _utc_naive(as_of) or datetime.datetime.utcnow()
    state = _replay_state(
        _customer_entries(db, shop_id, customer_id),
        moment,
    )
    slices = state.redeemed_slices.get(int(order_id), [])
    offset = int(
        state.restore_offsets.get((ENTRY_CANCEL_RESTORE, int(order_id)), 0)
    )
    cursor = 0
    result: List[Tuple[int, Optional[datetime.datetime]]] = []
    for source in slices:
        source_points = int(source.points)
        if cursor + source_points <= offset:
            cursor += source_points
            continue
        start = max(offset - cursor, 0)
        points = source_points - start
        expiry = _utc_naive(source.expires_at)
        cursor += source_points
        if points <= 0 or (expiry is not None and expiry <= moment):
            continue
        result.append((points, expiry))
    return result


def reversible_points_for_order(
    db: Session,
    shop_id: int,
    customer_id: int,
    order_id: int,
    target_total: int,
    *,
    as_of: Optional[datetime.datetime] = None,
) -> Tuple[int, int]:
    """Điểm thực có thể thu thêm để đạt mục tiêu lũy kế của đơn nguồn.

    Trả ``(cần ghi thêm, đã thu trước đó)``. Chỉ điểm còn trong ví hoặc từng
    được tiêu mới thu; phần hết hạn mà chưa dùng không tạo số dư âm.
    """
    target = _integer(
        target_total,
        "Mục tiêu thu hồi điểm phải là số nguyên không âm",
        minimum=0,
    )
    moment = _utc_naive(as_of) or datetime.datetime.utcnow()
    state = _replay_state(
        _customer_entries(db, shop_id, customer_id),
        moment,
    )
    order_key = int(order_id)
    already = int(state.reversed_by_order.get(order_key, 0))
    wanted = max(target - already, 0)
    live = sum(
        int(lot.remaining)
        for lot in state.lots
        if lot.origin_order_id == order_key
    )
    spent = int(state.spent_by_order.get(order_key, 0))
    return min(wanted, live + spent), already


def balance_for_customer(
    db: Session,
    customer_id: int,
    as_of: Optional[datetime.datetime] = None,
    shop_id: Optional[int] = None,
) -> int:
    """Số dư hiện tại của một khách; có thể âm sau khi trả hàng."""
    return balances_for_customers(
        db, [customer_id], as_of=as_of, shop_id=shop_id
    ).get(customer_id, 0)


def balances_for_customers(
    db: Session,
    customer_ids: Iterable[int],
    as_of: Optional[datetime.datetime] = None,
    shop_id: Optional[int] = None,
) -> Dict[int, int]:
    """Số dư nhiều khách bằng MỘT truy vấn, tránh N+1 ở danh sách khách."""
    ids = list(dict.fromkeys(int(customer_id) for customer_id in customer_ids))
    if not ids:
        return {}
    query = db.query(LoyaltyPointEntry).filter(
        LoyaltyPointEntry.customer_id.in_(ids)
    )
    if shop_id is not None:
        query = query.filter(LoyaltyPointEntry.shop_id == shop_id)
    entries = query.order_by(
        LoyaltyPointEntry.customer_id,
        LoyaltyPointEntry.created_at,
        LoyaltyPointEntry.id,
    ).all()

    grouped: Dict[int, List[LoyaltyPointEntry]] = {customer_id: [] for customer_id in ids}
    for entry in entries:
        grouped.setdefault(entry.customer_id, []).append(entry)
    return {
        customer_id: _replay_entries(grouped.get(customer_id, []), as_of)[0]
        for customer_id in ids
    }


def entry_to_dict(
    entry: LoyaltyPointEntry,
    *,
    balance_after: Optional[int] = None,
    as_of: Optional[datetime.datetime] = None,
) -> Dict:
    moment = _utc_naive(as_of) or datetime.datetime.utcnow()
    expiry = _utc_naive(entry.expires_at)
    return {
        "id": entry.id,
        "shop_id": entry.shop_id,
        "customer_id": entry.customer_id,
        "order_id": entry.order_id,
        "return_id": entry.return_id,
        "entry_type": entry.entry_type,
        "points_delta": entry.points_delta,
        "expires_at": entry.expires_at,
        "expired": bool(expiry is not None and expiry <= moment),
        "idempotency_key": entry.idempotency_key,
        "created_by_user_id": entry.created_by_user_id,
        "customer_name": entry.customer_name,
        "customer_phone": entry.customer_phone,
        "note": entry.note,
        "created_at": entry.created_at,
        "balance_after": balance_after,
    }


def history_for_customer(
    db: Session,
    customer_id: int,
    limit: Optional[int] = None,
    as_of: Optional[datetime.datetime] = None,
    shop_id: Optional[int] = None,
) -> List[Dict]:
    """Lịch sử mới nhất trước; ``balance_after`` là số dư ngay sau bút toán."""
    query = db.query(LoyaltyPointEntry).filter(
        LoyaltyPointEntry.customer_id == customer_id
    )
    if shop_id is not None:
        query = query.filter(LoyaltyPointEntry.shop_id == shop_id)
    entries = query.order_by(
        LoyaltyPointEntry.created_at,
        LoyaltyPointEntry.id,
    ).all()
    _, balances = _replay_entries(entries, as_of)
    processed = [entry for entry in entries if int(entry.id or 0) in balances]
    processed.reverse()
    if limit is not None:
        limit_int = _integer(
            limit,
            "Giới hạn lịch sử điểm phải là số nguyên không âm",
            minimum=0,
        )
        processed = processed[:limit_int]
    return [
        entry_to_dict(
            entry,
            balance_after=balances.get(int(entry.id or 0)),
            as_of=as_of,
        )
        for entry in processed
    ]


def has_history(
    db: Session, customer_id: int, shop_id: Optional[int] = None
) -> bool:
    query = db.query(LoyaltyPointEntry.id).filter(
        LoyaltyPointEntry.customer_id == customer_id
    )
    if shop_id is not None:
        query = query.filter(LoyaltyPointEntry.shop_id == shop_id)
    return query.first() is not None


def _same_idempotent_entry(
    entry: LoyaltyPointEntry,
    *,
    shop_id: int,
    customer_id: int,
    entry_type: str,
    points_delta: int,
    order_id: Optional[int],
    return_id: Optional[int],
) -> bool:
    return (
        entry.shop_id == shop_id
        and entry.customer_id == customer_id
        and entry.entry_type == entry_type
        and entry.points_delta == points_delta
        and entry.order_id == order_id
        and entry.return_id == return_id
    )


def _same_idempotent_expiry(
    entry: LoyaltyPointEntry,
    *,
    expiry_days: Optional[int],
    absolute_expiry: Optional[datetime.datetime],
) -> bool:
    if absolute_expiry is not None:
        expected = absolute_expiry
    elif expiry_days is not None:
        entry_created = _utc_naive(entry.created_at) or datetime.datetime.min
        expected = entry_created + datetime.timedelta(days=expiry_days)
    else:
        expected = None
    return _utc_naive(entry.expires_at) == expected


def add_entry(
    db: Session,
    shop_id: int,
    customer_id: int,
    entry_type: str,
    points_delta: int,
    idempotency_key: str,
    *,
    order_id: Optional[int] = None,
    return_id: Optional[int] = None,
    created_by_user_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    note: Optional[str] = None,
    expiry_days: Optional[int] = None,
    expires_at: Optional[datetime.datetime] = None,
    created_at: Optional[datetime.datetime] = None,
) -> Tuple[LoyaltyPointEntry, bool]:
    """Thêm một bút toán chống lặp, ``flush`` nhưng KHÔNG ``commit``.

    Trả ``(entry, True)`` khi vừa tạo và ``(entry, False)`` khi cùng khóa đã có.
    Cùng khóa nhưng nội dung tài chính khác bị từ chối thay vì giả vờ thành công.
    """
    key = (idempotency_key or "").strip()
    if not key or len(key) > 128:
        raise _bad_request("Khóa chống ghi trùng điểm không hợp lệ")
    kind = (entry_type or "").strip().upper()
    if not kind or len(kind) > 32:
        raise _bad_request("Loại bút toán điểm không hợp lệ")
    allowed_kinds = {
        ENTRY_EARN,
        ENTRY_REDEEM,
        ENTRY_CANCEL_RESTORE,
        ENTRY_RETURN_RESTORE,
        ENTRY_RETURN_REVERSE,
    }
    if kind not in allowed_kinds:
        raise _bad_request("Loại bút toán điểm không hợp lệ")
    delta = _integer(points_delta, "Số điểm phải là số nguyên")
    if delta == 0:
        raise _bad_request("Bút toán điểm phải khác 0")

    if expiry_days is not None and expires_at is not None:
        raise _bad_request("Chỉ được chọn một cách đặt hạn điểm")
    days: Optional[int] = None
    if expiry_days is not None:
        days = _integer(
            expiry_days,
            "Số ngày hết hạn điểm phải là số nguyên từ 1 trở lên",
            minimum=1,
        )
    absolute_expiry = _utc_naive(expires_at)
    if delta < 0 and (days is not None or absolute_expiry is not None):
        raise _bad_request("Bút toán trừ điểm không được có ngày hết hạn")

    existing = (
        db.query(LoyaltyPointEntry)
        .filter(LoyaltyPointEntry.idempotency_key == key)
        .first()
    )
    if existing is not None:
        if not (
            _same_idempotent_entry(
                existing,
                shop_id=shop_id,
                customer_id=customer_id,
                entry_type=kind,
                points_delta=delta,
                order_id=order_id,
                return_id=return_id,
            )
            and _same_idempotent_expiry(
                existing,
                expiry_days=days,
                absolute_expiry=absolute_expiry,
            )
        ):
            raise HTTPException(
                status_code=409,
                detail=tr("Khóa chống ghi trùng đã được dùng cho bút toán khác"),
            )
        return existing, False

    if kind in {ENTRY_EARN, ENTRY_REDEEM}:
        current_program = get_program_model(db, shop_id)
        if current_program is None or not current_program.enabled:
            raise _bad_request("Chương trình tích điểm đang tắt")
    if kind == ENTRY_EARN and delta < 0:
        raise _bad_request("Bút toán cộng điểm phải có số điểm dương")
    if kind == ENTRY_REDEEM and delta > 0:
        raise _bad_request("Bút toán dùng điểm phải có số điểm âm")
    if kind == ENTRY_CANCEL_RESTORE and delta < 0:
        raise _bad_request("Bút toán hoàn điểm khi hủy đơn phải có số điểm dương")
    if kind == ENTRY_RETURN_RESTORE and delta < 0:
        raise _bad_request("Bút toán hoàn điểm phải có số điểm dương")
    if kind == ENTRY_RETURN_REVERSE and delta > 0:
        raise _bad_request("Bút toán trừ lại điểm phải có số điểm âm")

    event_at = _utc_naive(created_at) or datetime.datetime.utcnow()
    if kind == ENTRY_REDEEM:
        available = balance_for_customer(
            db,
            customer_id,
            as_of=event_at,
            shop_id=shop_id,
        )
        if -delta > available:
            raise _bad_request("Số điểm muốn dùng lớn hơn số dư hiện có")
    entry_expiry = absolute_expiry
    if delta > 0 and days is not None:
        entry_expiry = event_at + datetime.timedelta(days=days)

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy khách hàng"))
    if customer.shop_id != shop_id:
        raise HTTPException(
            status_code=400,
            detail=tr("Khách hàng không thuộc cửa hàng này"),
        )

    entry = LoyaltyPointEntry(
        shop_id=shop_id,
        customer_id=customer_id,
        order_id=order_id,
        return_id=return_id,
        entry_type=kind,
        points_delta=delta,
        expires_at=entry_expiry,
        idempotency_key=key,
        created_by_user_id=created_by_user_id,
        customer_name=customer_name if customer_name is not None else customer.name,
        customer_phone=(
            customer_phone if customer_phone is not None else customer.phone
        ),
        note=(note or "").strip() or None,
        created_at=event_at,
    )

    try:
        # SAVEPOINT giữ nguyên transaction của đơn/trả hàng nếu hai request
        # đồng thời đụng unique key. Hàm này tuyệt đối không tự commit.
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except IntegrityError:
        duplicate = (
            db.query(LoyaltyPointEntry)
            .filter(LoyaltyPointEntry.idempotency_key == key)
            .first()
        )
        if duplicate is None or not (
            _same_idempotent_entry(
                duplicate,
                shop_id=shop_id,
                customer_id=customer_id,
                entry_type=kind,
                points_delta=delta,
                order_id=order_id,
                return_id=return_id,
            )
            and _same_idempotent_expiry(
                duplicate,
                expiry_days=days,
                absolute_expiry=absolute_expiry,
            )
        ):
            raise
        return duplicate, False
    return entry, True


__all__ = [
    "ENTRY_EARN",
    "ENTRY_REDEEM",
    "ENTRY_CANCEL_RESTORE",
    "ENTRY_RETURN_RESTORE",
    "ENTRY_RETURN_REVERSE",
    "get_program_model",
    "program_to_dict",
    "get_program",
    "update_program",
    "calculate_redeem",
    "calculate_earn",
    "cancel_restore_plan",
    "reversible_points_for_order",
    "balance_for_customer",
    "balances_for_customers",
    "entry_to_dict",
    "history_for_customer",
    "has_history",
    "add_entry",
]
