"""Nhận phiếu bán hàng đã bán khi mất mạng.

**Đây KHÔNG phải `create_order` với tham số khác.** Hai nghiệp vụ ngược chiều
nhau, và ép chung một cửa là đẻ ra lỗi tiền im lặng:

|                | `create_order`                | ở đây                          |
|----------------|-------------------------------|--------------------------------|
| Giao dịch      | đang xảy ra, trên server      | **đã xảy ra rồi**, ở máy bán   |
| Giá            | tính lại từ DB, bỏ giá client | **lấy giá trên phiếu**         |
| Hết hàng       | từ chối đơn                   | vẫn ghi, cho tồn âm, báo chủ   |
| Ca thu ngân    | ca đang mở lúc gọi hàm        | **ca đang mở lúc BÁN**         |
| Thanh toán     | chuyển khoản / mặt / nợ       | **chỉ tiền mặt**               |

Ba lý do cho ba dòng in đậm:

1. **Giá phải lấy từ phiếu.** Bán lúc 9h giá 100k, chủ shop đổi 120k lúc 11h,
   sync lúc 14h. Tính lại theo giá hôm nay là ghi 120k trong khi khách đã đưa
   100k — két lệch 20k và không ai tra ra vì sao.
2. **Hết hàng vẫn phải ghi.** Hàng đã ra khỏi cửa thật. Từ chối đơn thì tiền
   trong két thừa so với sổ, và cửa hàng mất luôn dấu vết giao dịch. Cho tồn âm
   rồi báo chủ shop đi kiểm kê là cách duy nhất giữ được cả doanh thu lẫn két.
3. **Ca theo giờ bán.** Bán 14h ca sáng, sync 18h. Gắn vào ca chiều là ca sáng
   đã chốt quỹ xong mà doanh thu lại rơi sang ca sau — sổ ca sai vĩnh viễn.

Chỉ tiền mặt vì voucher cần đếm lượt dùng trên server và ghi nợ cần kiểm hạn
mức trên server. Offline không kiểm được, mà đoán bừa thì hậu quả là tiền.

Chống ghi hai lần dựa vào unique index `ux_orders_offline_uuid`. Nó nằm trong
`financial_indexes` của bootstrap: thiếu index đó thì app KHÔNG khởi động, vì
máy bán gửi lại phiếu là chuyện bình thường và mỗi lần gửi lại sẽ là một đơn
mới — doanh thu và tồn kho cùng nhân đôi.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..core import config
from ..core.money import checked_add, checked_multiply, exact_vnd
from ..dependencies import (
    PERMISSION_SALE,
    has_cost_visibility,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.order import (
    OfflineIssueAcknowledge,
    OfflineOrderCreate,
    OfflineOrderCreateV1,
)
from . import inventory_service, order_service
from .offline_fingerprint import (
    OfflineFingerprintV0,
    OfflineFingerprintV1,
    OfflineTotalOverflowError,
    canonical_time_text,
    canonical_time_text_v1,
    fingerprint_offline_receipt_v0,
    fingerprint_offline_receipt_v1,
)

# Vướng mắc lúc ghi phiếu. Đơn KHÔNG bị chặn vì lý do nào trong số này.
#
# Mỗi vướng mắc sinh MỘT DÒNG `offline_receipt_issues` — đó mới là sự thật của
# màn Đối Soát. `orders.offline_issue` vẫn được ghi y như cũ nhưng chỉ còn là
# bản sao tương thích: một chuỗi nối bằng dấu phẩy không nói được dòng nào,
# còn thiếu bao nhiêu, hay ai đã xác nhận cái gì.
ISSUE_TON_AM = "TON_AM"              # kho không đủ hàng lúc sync
ISSUE_CA_DA_CHOT = "CA_DA_CHOT"      # ca lúc bán nay đã kết ca
ISSUE_KHONG_CO_CA = "KHONG_CO_CA"    # không ca nào phủ giờ bán
ISSUE_SP_KHONG_CON = "SP_KHONG_CON"  # sản phẩm đã bị xóa giữa bán và sync
ISSUE_GIA_DOI = "GIA_DOI"            # giá trên phiếu khác giá hiện tại

EVIDENCE_STOCK_DEFICIT = "OFFLINE_STOCK_DEFICIT"
EVIDENCE_BATCH_DEFICIT = "OFFLINE_BATCH_DEFICIT"
EVIDENCE_SHIFT = "SHIFT"
EVIDENCE_CATALOG = "CATALOG"
EVIDENCE_LEGACY_AMBIGUOUS = "LEGACY_AMBIGUOUS"

SEVERITY_INFO = "INFO"
SEVERITY_ACTION = "ACTION"

STATE_OPEN = "OPEN"
STATE_ACKNOWLEDGED = "ACKNOWLEDGED"
STATE_RESOLVED = "RESOLVED"

# GIA_DOI là thông tin, không phải việc phải làm: đơn đã ghi đúng giá khách trả
# lúc mua, giá hôm nay khác là chuyện bình thường. Ghi thẳng RESOLVED để nó nằm
# trong lịch sử mà không chiếm chỗ trên màn "Cần xử lý".
RESOLUTION_INFORMATIONAL = "INFORMATIONAL_AT_INGEST"
RESOLUTION_STOCKTAKE = "STOCKTAKE"

# Acknowledging is NOT a resolution: it records that a human looked, and 0005
# rejects any ACKNOWLEDGED row that carries a `resolution_kind`.
ISSUE_STATES = (STATE_OPEN, STATE_ACKNOWLEDGED, STATE_RESOLVED)

# Codes chỉ được acknowledge khi không có bằng chứng exact nào để đóng.
ACKNOWLEDGEABLE_ISSUE_CODES = (ISSUE_CA_DA_CHOT, ISSUE_KHONG_CO_CA)

# Đã nằm trong `CASH_PAYMENT_IN_TYPES` của shift_service nên tự được tính vào
# két của ca. ĐỪNG thêm `CashMovement` kèm theo — sẽ cộng két hai lần.
ENTRY_SALE_CASH = "SALE_CASH"

ERROR_FINGERPRINT_CONFLICT = "OFFLINE_RECEIPT_FINGERPRINT_CONFLICT"
ERROR_UUID_OTHER_SHOP = "OFFLINE_UUID_OTHER_SHOP"
# Source-compatible alias for callers that imported the pre-ADR Python name.
ERROR_RECEIPT_UUID_OTHER_SHOP = ERROR_UUID_OTHER_SHOP
ERROR_REGISTRY_INCONSISTENT = "OFFLINE_RECEIPT_REGISTRY_INCONSISTENT"
ERROR_UUID_UNAVAILABLE = "OFFLINE_RECEIPT_UUID_UNAVAILABLE"
ERROR_V0_CUTOFF_RECOVERY_REQUIRED = "OFFLINE_CONTRACT_V0_RECOVERY_REQUIRED"

# Bằng chứng exact chỉ đóng được bằng kiểm kê thật; nút "đã xem" không làm số
# hàng thiếu quay lại. Map lại sản phẩm / chấp nhận giá vốn unknown thuộc I09-G.
ERROR_ISSUE_EVIDENCE_REQUIRED = "OFFLINE_ISSUE_EVIDENCE_REQUIRED"
ERROR_ISSUE_RECOVERY_REQUIRED = "OFFLINE_ISSUE_RECOVERY_REQUIRED"
ERROR_ISSUE_STATE_CONFLICT = "OFFLINE_ISSUE_STATE_CONFLICT"

MONEY_EPSILON = 0


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": code, "message": tr(message)},
    )


def _tien(x: Any) -> int:
    return exact_vnd(x or 0)


def _phan_hoi(order: models.Order, moi: bool) -> Dict[str, Any]:
    return {
        "order_id": order.id,
        "offline_uuid": order.offline_uuid,
        "total": _tien(order.total_amount),
        "shift_id": order.shift_id,
        "issues": [x for x in (order.offline_issue or "").split(",") if x],
        # `False` = phiếu này đã được ghi trước đó, lần gửi này không tạo gì mới.
        # Máy bán dựa vào đây để xóa phiếu khỏi hàng chờ mà không sợ mất đơn.
        "created": moi,
    }


def _xung_dot(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": code, "message": tr(message)},
    )


def _reject_new_v0_after_cutoff() -> None:
    """The caller has already ruled out an idempotent durable v0 winner."""
    if config.OFFLINE_CONTRACT_MIN_VERSION >= 1:
        raise _xung_dot(
            ERROR_V0_CUTOFF_RECOVERY_REQUIRED,
            "Phiếu offline v0 mới cần chủ shop phục hồi sau đợt chuyển contract",
        )


def _canonical_order_time(value: Optional[datetime]) -> Optional[str]:
    return canonical_time_text(value) if value is not None else None


def _receipt_v0_consistent(
    order: models.Order,
    registry: models.OfflineReceiptRegistry,
    receipt: models.OfflineReceipt,
) -> bool:
    """Validate the durable v0 evidence needed to classify a retry safely."""
    sold_at = receipt.sold_at_effective
    try:
        canonical_registry_created = canonical_time_text(
            datetime.strptime(registry.created_at, "%Y-%m-%d %H:%M:%S.%f")
        )
        canonical_registry_updated = canonical_time_text(
            datetime.strptime(registry.updated_at, "%Y-%m-%d %H:%M:%S.%f")
        )
        canonical_sold_at = canonical_time_text(
            datetime.strptime(sold_at, "%Y-%m-%d %H:%M:%S.%f")
        )
        canonical_ingested = canonical_time_text(
            datetime.strptime(receipt.ingested_at, "%Y-%m-%d %H:%M:%S.%f")
        )
    except (TypeError, ValueError):
        return False
    return bool(
        registry.state == "INGESTED"
        and registry.order_id == order.id == receipt.order_id
        and registry.offline_uuid == order.offline_uuid == receipt.offline_uuid
        and registry.shop_id == order.shop_id
        and registry.contract_version == receipt.contract_version == 0
        and registry.server_fingerprint == receipt.server_fingerprint
        and registry.superseded_by_offline_uuid is None
        and canonical_registry_created == registry.created_at
        and canonical_registry_updated == registry.updated_at
        and canonical_sold_at == sold_at == receipt.sold_at_client_utc
        and canonical_ingested == receipt.ingested_at
        and _canonical_order_time(order.created_at) == sold_at
        and _canonical_order_time(order.sold_offline_at) == sold_at
        and receipt.sold_by_claimed_user_id == order.created_by_user_id
        and receipt.synced_by_user_id == order.created_by_user_id
        and receipt.attribution_kind == "LEGACY_UNKNOWN"
        and receipt.time_confidence == "LEGACY"
        and receipt.client_fingerprint is None
        and receipt.client_fingerprint_mismatch == 0
        and receipt.lease_id is None
        and receipt.device_id is None
        and receipt.offline_session_id is None
        and receipt.sequence is None
        and receipt.sold_at_upper_bound is None
        and receipt.client_monotonic_ms is None
        and receipt.server_anchor_id is None
    )


def _tim_theo_uuid(
    db: Session,
    shop_id: int,
    uuid: str,
    fingerprint: str,
) -> Optional[models.Order]:
    don_theo_uuid = (
        db.query(models.Order)
        .filter(models.Order.offline_uuid == uuid)
        .first()
    )
    registry = db.get(models.OfflineReceiptRegistry, uuid)
    receipt = (
        db.query(models.OfflineReceipt)
        .filter(models.OfflineReceipt.offline_uuid == uuid)
        .first()
    )

    # Check scope before returning any order-derived response.  The error body
    # contains no order id, fingerprint or UUID from the other shop.
    if (
        don_theo_uuid is not None
        and don_theo_uuid.shop_id != shop_id
        or registry is not None
        and registry.shop_id != shop_id
    ):
        raise _xung_dot(
            ERROR_UUID_OTHER_SHOP,
            "Mã phiếu offline đã được dùng cho một cửa hàng khác",
        )

    if registry is None:
        if receipt is not None:
            raise _xung_dot(
                ERROR_REGISTRY_INCONSISTENT,
                "Dữ liệu bằng chứng phiếu offline không nhất quán",
            )
        if don_theo_uuid is not None:
            # Residual compatibility: this order predates I09-B1.  Its retry is
            # a no-op, but no payload can prove or reconstruct its fingerprint.
            return don_theo_uuid
        return None

    if registry.state != "INGESTED":
        if receipt is not None or registry.order_id is not None or don_theo_uuid is not None:
            raise _xung_dot(
                ERROR_REGISTRY_INCONSISTENT,
                "Dữ liệu bằng chứng phiếu offline không nhất quán",
            )
        raise _xung_dot(
            ERROR_UUID_UNAVAILABLE,
            "Mã phiếu offline đã được giữ bởi một bản ghi không thể đồng bộ lại",
        )
    if registry.order_id is None:
        raise _xung_dot(
            ERROR_REGISTRY_INCONSISTENT,
            "Dữ liệu bằng chứng phiếu offline không nhất quán",
        )
    don_theo_registry = db.get(models.Order, registry.order_id)
    if (
        registry.contract_version != 0
        or receipt is not None
        and receipt.contract_version != 0
    ):
        # A UUID cannot be promoted or demoted between v0 and v1.  This is a
        # document conflict, not durable corruption.
        raise _xung_dot(
            ERROR_FINGERPRINT_CONFLICT,
            "Mã phiếu offline đã được dùng với contract khác",
        )
    if (
        don_theo_uuid is None
        or don_theo_registry is None
        or don_theo_registry.id != don_theo_uuid.id
        or receipt is None
        or not _receipt_v0_consistent(don_theo_registry, registry, receipt)
    ):
        raise _xung_dot(
            ERROR_REGISTRY_INCONSISTENT,
            "Dữ liệu bằng chứng phiếu offline không nhất quán",
        )
    if registry.server_fingerprint != fingerprint:
        raise _xung_dot(
            ERROR_FINGERPRINT_CONFLICT,
            "Mã phiếu offline đã được dùng với nội dung khác",
        )
    return don_theo_registry


def _is_uuid_uniqueness_error(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return (
        "unique constraint failed: orders.offline_uuid" in message
        or "unique constraint failed: offline_receipt_registry.offline_uuid" in message
        or "ux_orders_offline_uuid" in message
        or "offline_receipt_registry_pkey" in message
    )


def _durable_retry_after_integrity(
    db: Session,
    shop_id: int,
    canonical: OfflineFingerprintV0,
) -> Optional[Dict[str, Any]]:
    """Classify only a known UUID race using a clean Session after rollback."""
    fresh = Session(bind=db.get_bind())
    try:
        order = _tim_theo_uuid(
            fresh,
            shop_id,
            canonical.offline_uuid,
            canonical.fingerprint,
        )
        return _phan_hoi(order, moi=False) if order is not None else None
    finally:
        fresh.close()


def _issue_moi(
    *,
    order_id: int,
    issue_code: str,
    evidence_kind: str,
    severity: str,
    opened_at: str,
    order_item_id: Optional[int] = None,
    product_id: Optional[int] = None,
    evidence_id: Optional[int] = None,
    resolution_kind: Optional[str] = None,
    resolved_by_user_id: Optional[int] = None,
) -> models.OfflineReceiptIssue:
    """Build one issue row. Version 0 and no ACK path: 0005 enforces both.

    A row is either born OPEN, or born RESOLVED when it is purely informational.
    It can never be born ACKNOWLEDGED — that is somebody taking responsibility,
    so it has to be an audited transition with a reason.
    """
    resolved = resolution_kind is not None
    return models.OfflineReceiptIssue(
        order_id=order_id,
        order_item_id=order_item_id,
        product_id=product_id,
        issue_code=issue_code,
        evidence_kind=evidence_kind,
        evidence_id=evidence_id,
        severity=severity,
        state=STATE_RESOLVED if resolved else STATE_OPEN,
        reason=None,
        opened_at=opened_at,
        resolved_at=opened_at if resolved else None,
        resolved_by_user_id=resolved_by_user_id if resolved else None,
        resolution_kind=resolution_kind,
        state_version=0,
    )


def _ca_phu_gio_ban(
    db: Session, shop_id: int, user_id: int, luc_ban: datetime
) -> Optional[models.CashShift]:
    """Ca của chính người bán, đang mở vào ĐÚNG thời điểm bán.

    Lấy cả ca đã đóng: doanh thu phải nằm đúng kỳ của nó. Ca đã đóng thì gắn cờ
    `CA_DA_CHOT` để chủ shop biết con số chốt ca cũ không còn khớp.
    """
    return (
        db.query(models.CashShift)
        .filter(
            models.CashShift.shop_id == shop_id,
            models.CashShift.opened_by_user_id == user_id,
            models.CashShift.opened_at <= luc_ban,
            or_(
                models.CashShift.closed_at.is_(None),
                models.CashShift.closed_at >= luc_ban,
            ),
        )
        .order_by(models.CashShift.opened_at.desc())
        .first()
    )


def _tru_ton_chiu_thieu(
    db: Session, prod: models.Product, so_luong: int
) -> Tuple[List[inventory_service.CostAllocation], int]:
    """Trừ tồn kho, KHÔNG chặn khi thiếu. Trả về (lô đã lấy, số còn thiếu).

    Khác `inventory_service.deduct_stock` ở đúng một điểm: hàm kia ném 400 khi
    lô không đủ, còn ở đây hàng đã ra khỏi cửa nên phải ghi.

    `Product.stock` bị trừ ĐỦ số lượng đã bán, kể cả khi lô không phủ hết. Với
    hàng theo lô, điều đó tạm phá bất biến "stock = tổng mọi lô" (bẫy 21) — và
    đó là **có chủ ý**: chính khoảng lệch ấy là bằng chứng có hàng ra khỏi kho mà
    không có lô nào chịu. Cờ `TON_AM` bảo chủ shop đi kiểm kê, và kiểm kê theo lô
    (bẫy 24) dựng lại `stock` bằng tổng mọi lô — đúng cách chữa.
    """
    if not prod.track_batches:
        con_truoc = int(prod.stock or 0)
        allocation = inventory_service.consume_cost_pool(
            prod, so_luong, allow_deficit=True
        )
        prod.stock = con_truoc - so_luong
        return [allocation], max(so_luong - max(con_truoc, 0), 0)

    con_lai = so_luong
    da_lay: List[inventory_service.CostAllocation] = []
    for lo in inventory_service.lo_con_ban_duoc(db, prod.id):
        if con_lai <= 0:
            break
        lay = min(int(lo.quantity or 0), con_lai)
        if lay <= 0:
            continue
        allocation = inventory_service.consume_cost_pool(lo, lay)
        lo.quantity = int(lo.quantity or 0) - lay
        con_lai -= lay
        da_lay.append(allocation)
    prod.stock = int(prod.stock or 0) - so_luong
    return da_lay, con_lai


def _prepare_offline_sale_lines(
    db: Session,
    *,
    shop_id: int,
    canonical_items: Tuple[Any, ...],
) -> Tuple[int, List[Dict[str, Any]], List[str]]:
    """Shared v0/v1 exact-money preparation in canonical item order."""
    total = 0
    lines: List[Dict[str, Any]] = []
    issues: List[str] = []
    for item in canonical_items:
        product = (
            db.query(models.Product)
            .filter(
                models.Product.id == item.product_id,
                models.Product.shop_id == shop_id,
            )
            .first()
        )
        total = checked_add(
            total,
            checked_multiply(item.quantity, item.unit_price_vnd),
        )
        missing = product is None
        price_changed = (
            product is not None and _tien(product.price) != item.unit_price_vnd
        )
        lines.append(
            {
                "prod": product,
                "mh": item,
                "thieu_sp": missing,
                "gia_doi": price_changed,
            }
        )
        code = ISSUE_SP_KHONG_CON if missing else ISSUE_GIA_DOI if price_changed else None
        if code is not None and code not in issues:
            issues.append(code)
    return total, lines, issues


def _add_offline_cash_payment(
    db: Session,
    *,
    order_id: int,
    amount: int,
    offline_uuid: str,
    actor_user_id: int,
    shift_id: Optional[int],
    sold_at: datetime,
    note: str,
) -> None:
    """Shared append-only cash ledger entry for both offline contracts."""
    db.add(
        models.OrderPayment(
            order_id=order_id,
            entry_type=ENTRY_SALE_CASH,
            amount=amount,
            idempotency_key=f"offline:{offline_uuid}",
            created_by_user_id=actor_user_id,
            shift_id=shift_id,
            note=note,
            created_at=sold_at,
        )
    )


def dong_bo_phieu(
    db: Session,
    current_user: models.User,
    shop_id: int,
    phieu: OfflineOrderCreate,
) -> Dict[str, Any]:
    """Ghi một phiếu v0; retry chỉ là no-op khi fingerprint vẫn tương thích."""
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    user_id = int(current_user.id)

    try:
        canonical = fingerprint_offline_receipt_v0(
            shop_id=shop_id,
            offline_uuid=phieu.offline_uuid,
            sold_at=phieu.sold_at,
            items=phieu.items,
            cash_tendered_vnd=phieu.cash_tendered,
            device_label=phieu.device_label,
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=tr("Phiếu offline chứa dữ liệu không thể chuẩn hóa an toàn"),
        )

    uuid = canonical.offline_uuid
    if not uuid:
        raise _bad_request("OFFLINE_UUID_MISSING", "Thiếu mã phiếu offline")

    # Fingerprint is already known before the first duplicate decision.  A
    # matching durable registry is a retry; a different document is a conflict.
    da_co = _tim_theo_uuid(db, shop_id, uuid, canonical.fingerprint)
    if da_co is not None:
        return _phan_hoi(da_co, moi=False)
    _reject_new_v0_after_cutoff()

    # Close the read snapshot before upgrading to SQLite's write lock.  This is
    # the same pattern used by webhook handling: a concurrent winner may commit
    # while this request is waiting, and must be visible to the post-lock read.
    db.rollback()

    # Cùng hàng rào với `create_order`: mọi phép đọc quyết định việc ghi (tồn
    # kho) phải nằm sau một write lock của shop.
    try:
        order_service._lock_shop_for_order(db, shop_id)

        # Một lần sync song song có thể đã ghi xong trong lúc request này chờ lock.
        da_co = _tim_theo_uuid(db, shop_id, uuid, canonical.fingerprint)
        if da_co is not None:
            response = _phan_hoi(da_co, moi=False)
            db.rollback()
            return response
        # Recheck only after the write lock: a parallel durable winner remains
        # idempotent, while a new v0 receipt cannot reach any financial write.
        _reject_new_v0_after_cutoff()

        luc_ban = canonical.sold_at_utc
        ingested_at = datetime.utcnow()
        if luc_ban > ingested_at:
            # Đồng hồ máy bán chạy nhanh. Nhận giờ tương lai thì đơn rơi ra ngoài mọi
            # báo cáo theo ngày và không ca nào phủ được nó.
            raise _bad_request(
                "OFFLINE_TIME_FUTURE",
                "Giờ bán nằm ở tương lai; kiểm lại đồng hồ máy bán",
            )

        van_de: List[str] = []

        # ---- Dựng các dòng hàng theo GIÁ TRÊN PHIẾU ----
        # Đi theo `canonical.items`, KHÔNG theo `phieu.items`. Fingerprint coi
        # `items` là tập không thứ tự và đã sắp lại; nếu tác động nghiệp vụ vẫn
        # chạy theo thứ tự client gửi thì hai request cùng fingerprint có thể
        # trừ pool giá vốn khác nhau — dòng nào nhận unknown, dòng nào nhận
        # known/cost basis lại phụ thuộc request nào thắng. Lãi và trả hàng từng
        # phần sẽ khác nhau trên cùng một phiếu. Thứ tự canonical giữ nguyên bội
        # số dòng trùng, không bao giờ gộp dòng.
        try:
            tong, dong_hang, line_issues = _prepare_offline_sale_lines(
                db,
                shop_id=shop_id,
                canonical_items=canonical.items,
            )
        except ValueError:
            raise _bad_request(
                "OFFLINE_TOTAL_OVERFLOW",
                "Tổng tiền phiếu vượt giới hạn",
            )
        van_de.extend(line_issues)

        tendered = _tien(phieu.cash_tendered)
        if tendered < tong:
            # Tiền khách đưa ít hơn tổng đơn là phiếu sai, không phải xung đột dữ
            # liệu. Nhận vào là ghi một khoản thu không có thật.
            raise _bad_request(
                "OFFLINE_TENDER_TOO_LOW",
                tr(
                    "Tiền khách đưa ({tendered}) nhỏ hơn tổng đơn ({total})",
                    tendered=f"{tendered:,.0f}đ",
                    total=f"{tong:,.0f}đ",
                ),
            )

        # ---- Ca thu ngân theo GIỜ BÁN ----
        ca = _ca_phu_gio_ban(db, shop_id, user_id, luc_ban)
        if ca is None:
            van_de.append(ISSUE_KHONG_CO_CA)
        elif ca.status != "OPEN":
            van_de.append(ISSUE_CA_DA_CHOT)

        # ---- Ghi đơn + bằng chứng registry/receipt trong cùng transaction ----
        don = models.Order(
            shop_id=shop_id,
            created_by_user_id=user_id,
            shift_id=ca.id if ca else None,
            total_amount=tong,
            discount_amount=0,
            payment_method=order_service.PAYMENT_METHOD_CASH,
            status=order_service.STATUS_PAID,
            cash_paid_amount=tong,
            cash_tendered_amount=tendered,
            cash_change_amount=max(tendered - tong, 0),
            # Cùng UTC-naive instant đã canonicalize; offset không bao giờ bị drop.
            created_at=luc_ban,
            sold_offline_at=luc_ban,
            offline_uuid=uuid,
            offline_device=canonical.device_label,
        )
        db.add(don)
        db.flush()  # cần id để gắn receipt, dòng hàng và bút toán

        now_text = canonical_time_text(ingested_at)
        registry = models.OfflineReceiptRegistry(
            offline_uuid=uuid,
            shop_id=shop_id,
            order_id=don.id,
            server_fingerprint=canonical.fingerprint,
            contract_version=0,
            state="INGESTED",
            superseded_by_offline_uuid=None,
            created_at=now_text,
            updated_at=now_text,
            state_version=0,
        )
        db.add(registry)
        db.flush()
        db.add(
            models.OfflineReceipt(
                order_id=don.id,
                offline_uuid=uuid,
                contract_version=0,
                lease_id=None,
                device_id=None,
                offline_session_id=None,
                sequence=None,
                server_fingerprint=canonical.fingerprint,
                client_fingerprint=None,
                client_fingerprint_mismatch=0,
                sold_by_claimed_user_id=user_id,
                synced_by_user_id=user_id,
                attribution_kind="LEGACY_UNKNOWN",
                sold_at_effective=canonical.sold_at_text,
                sold_at_client_utc=canonical.sold_at_text,
                sold_at_upper_bound=None,
                time_confidence="LEGACY",
                client_monotonic_ms=None,
                server_anchor_id=None,
                ingested_at=now_text,
            )
        )

        for cap in dong_hang:
            prod: Optional[models.Product] = cap["prod"]
            mh = cap["mh"]

            da_lay: List[inventory_service.CostAllocation] = []
            thieu = mh.quantity if prod is None else 0
            if prod is not None:
                da_lay, thieu = _tru_ton_chiu_thieu(db, prod, mh.quantity)
                if thieu > 0 and ISSUE_TON_AM not in van_de:
                    van_de.append(ISSUE_TON_AM)

            known_qty, allocated_unknown_qty, cost_basis = (
                inventory_service.allocation_totals(da_lay)
            )
            # A non-batch deficit allocation already spans the full sold quantity
            # (the uncovered part is canonical unknown cost).  Batch allocations
            # span only physical source batches, so only their unallocated tail is
            # added here.  Adding ``thieu`` blindly counted a non-batch deficit
            # twice and persisted K+U > quantity.
            allocated_qty = sum(a.quantity for a in da_lay)
            unallocated_qty = max(int(mh.quantity) - allocated_qty, 0)
            unknown_qty = allocated_unknown_qty + unallocated_qty
            line_total = checked_multiply(mh.quantity, mh.unit_price_vnd)

            dong = models.OrderItem(
                order_id=don.id,
                product_id=prod.id if prod else None,
                # Đã NFC/trim/collapse ở bước canonicalize, và không bao giờ rỗng.
                product_name=mh.product_name,
                price=mh.unit_price_vnd,
                quantity=mh.quantity,
                discount_vnd=0,
                loyalty_discount_vnd=0,
                net_amount_vnd=line_total,
                cost_known_qty=known_qty,
                cost_unknown_qty=unknown_qty,
                cost_basis_vnd=cost_basis,
            )
            db.add(dong)
            db.flush()

            if cap["thieu_sp"]:
                # Không auto-resolve: map lại sản phẩm hoặc chấp nhận giá vốn
                # unknown là việc của owner ở I09-G, không phải nút "đã xem".
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_SP_KHONG_CON,
                        evidence_kind=EVIDENCE_CATALOG,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                    )
                )
            elif cap["gia_doi"]:
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_GIA_DOI,
                        evidence_kind=EVIDENCE_CATALOG,
                        severity=SEVERITY_INFO,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id if prod else None,
                        resolution_kind=RESOLUTION_INFORMATIONAL,
                        resolved_by_user_id=user_id,
                    )
                )

            if prod is not None and prod.track_batches and unallocated_qty > 0:
                # Do not invent a batch for goods that had already left the shop.
                # This row is the durable, per-product/exact-quantity evidence that
                # makes the deliberate Product.stock < SUM(batch.quantity) gap
                # restart-verifiable until a batch stocktake reconciles it.
                bang_chung_lo = models.OfflineBatchStockDeficit(
                    order_item_id=dong.id,
                    product_id=prod.id,
                    deficit_quantity=unallocated_qty,
                    remaining_quantity=unallocated_qty,
                    resolution_kind=None,
                    state_version=0,
                )
                db.add(bang_chung_lo)
                db.flush()  # cần id để issue trỏ đúng bằng chứng
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_TON_AM,
                        evidence_kind=EVIDENCE_BATCH_DEFICIT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id,
                        evidence_id=bang_chung_lo.id,
                    )
                )
            elif prod is not None and not prod.track_batches and thieu > 0:
                # Exact per-line evidence for a product without batches. The only
                # other trace is the aggregate `products.cost_deficit_qty`, which
                # can never be attributed back to a line — so it can never say
                # which issue a stocktake just closed.
                bang_chung = models.OfflineStockDeficit(
                    order_item_id=dong.id,
                    product_id=prod.id,
                    deficit_quantity=thieu,
                    remaining_quantity=thieu,
                    state_version=0,
                )
                db.add(bang_chung)
                db.flush()
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_TON_AM,
                        evidence_kind=EVIDENCE_STOCK_DEFICIT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id,
                        evidence_id=bang_chung.id,
                    )
                )

            if prod is not None and prod.track_batches:
                for allocation in da_lay:
                    lo = allocation.batch
                    if lo is None:
                        raise HTTPException(
                            status_code=409,
                            detail=tr("Thiếu provenance lô offline"),
                        )
                    db.add(
                        models.OrderItemBatch(
                            order_item_id=dong.id,
                            batch_id=lo.id,
                            quantity=allocation.quantity,
                            cost_known_qty=allocation.known_qty,
                            cost_unknown_qty=allocation.unknown_qty,
                            cost_basis_vnd=allocation.cost_basis_vnd,
                        )
                    )

        # Vấn đề về ca thuộc về cả phiếu, không thuộc dòng hàng nào.
        for ma_ca in (ISSUE_CA_DA_CHOT, ISSUE_KHONG_CO_CA):
            if ma_ca in van_de:
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ma_ca,
                        evidence_kind=EVIDENCE_SHIFT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                    )
                )

        # Bản sao tương thích. Màn Đối Soát đọc `offline_receipt_issues`, nhưng
        # chuỗi này vẫn được ghi để lịch sử, verifier 0005 và client cũ khớp nhau.
        if van_de:
            don.offline_issue = ",".join(van_de)

        # ---- Bút toán tiền mặt vào két của ca ----
        # `idempotency_key` là lớp chặn thứ hai sau registry/order UUID.
        _add_offline_cash_payment(
            db,
            order_id=don.id,
            amount=tong,
            offline_uuid=uuid,
            actor_user_id=user_id,
            shift_id=ca.id if ca else None,
            sold_at=luc_ban,
            note="Bán tiền mặt khi mất mạng",
        )

        # Transaction-local audit: no device label, UUID or raw payload.
        order_service._them_nhat_ky(
            db,
            user_id,
            "OFFLINE_SALE",
            (
                f"Đơn #{don.id} bán offline lúc {luc_ban:%Y-%m-%d %H:%M} "
                f"- {tong:,.0f}đ"
                + (f" - vướng: {don.offline_issue}" if don.offline_issue else "")
            ),
            shop_id=shop_id,
        )
        # Order/items/payment/inventory/cost/registry/receipt/audit become durable
        # together.  No helper on this path commits independently.
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_uuid_uniqueness_error(exc):
            durable = _durable_retry_after_integrity(db, shop_id, canonical)
            if durable is not None:
                return durable
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(don)
    return _phan_hoi(don, moi=True)


def _remaining_theo_evidence(
    db: Session, issues: List[models.OfflineReceiptIssue]
) -> Dict[Tuple[str, int], int]:
    """Đọc phần còn thiếu của từng bằng chứng, gom theo (kind, id)."""
    can_ids: Dict[str, List[int]] = {
        EVIDENCE_STOCK_DEFICIT: [],
        EVIDENCE_BATCH_DEFICIT: [],
    }
    for issue in issues:
        if issue.evidence_kind in can_ids and issue.evidence_id is not None:
            can_ids[issue.evidence_kind].append(int(issue.evidence_id))

    remaining: Dict[Tuple[str, int], int] = {}
    if can_ids[EVIDENCE_STOCK_DEFICIT]:
        for row in (
            db.query(models.OfflineStockDeficit)
            .filter(models.OfflineStockDeficit.id.in_(can_ids[EVIDENCE_STOCK_DEFICIT]))
            .all()
        ):
            remaining[(EVIDENCE_STOCK_DEFICIT, int(row.id))] = int(
                row.remaining_quantity or 0
            )
    if can_ids[EVIDENCE_BATCH_DEFICIT]:
        for row in (
            db.query(models.OfflineBatchStockDeficit)
            .filter(
                models.OfflineBatchStockDeficit.id.in_(can_ids[EVIDENCE_BATCH_DEFICIT])
            )
            .all()
        ):
            remaining[(EVIDENCE_BATCH_DEFICIT, int(row.id))] = int(
                row.remaining_quantity or 0
            )
    return remaining


def danh_sach_can_xu_ly(
    db: Session, shop_id: int, state: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Đơn offline có vướng mắc, để chủ shop xử lý. Mới nhất trước.

    Đọc `offline_receipt_issues`, KHÔNG lọc bằng chuỗi `orders.offline_issue`:
    chuỗi đó không nói được dòng nào hỏng, còn thiếu bao nhiêu hay ai đã xác
    nhận, nên một đơn đã xử lý xong vẫn nằm mãi trên màn "Cần xử lý".

    Mặc định chỉ trả `OPEN`. Đơn đã ACK/RESOLVED rời khỏi danh sách việc phải
    làm nhưng vẫn tra lại được bằng `state=ACKNOWLEDGED|RESOLVED|ALL`.

    KHÔNG trả fingerprint, UUID, `reason` thô, token hay giá vốn: đây là màn
    danh sách, và mấy thứ đó hoặc là bằng chứng nội bộ hoặc là số nhạy cảm.
    """
    state = (state or STATE_OPEN).strip().upper()
    if state != "ALL" and state not in ISSUE_STATES:
        raise HTTPException(
            status_code=400,
            detail=tr("Trạng thái vướng mắc không hợp lệ"),
        )

    query = (
        db.query(models.OfflineReceiptIssue, models.Order)
        .join(models.Order, models.Order.id == models.OfflineReceiptIssue.order_id)
        .filter(models.Order.shop_id == shop_id)
    )
    if state != "ALL":
        query = query.filter(models.OfflineReceiptIssue.state == state)
    cap = query.order_by(models.OfflineReceiptIssue.id).all()

    issues = [issue for issue, _order in cap]
    remaining = _remaining_theo_evidence(db, issues)

    theo_don: Dict[int, Dict[str, Any]] = {}
    for issue, order in cap:
        muc = theo_don.get(order.id)
        if muc is None:
            muc = {
                "order_id": order.id,
                "sold_at": order.sold_offline_at,
                "total": _tien(order.total_amount),
                "device": order.offline_device,
                "shift_id": order.shift_id,
                "issues": [],
                "issue_details": [],
            }
            theo_don[order.id] = muc
        if issue.issue_code not in muc["issues"]:
            muc["issues"].append(issue.issue_code)
        muc["issue_details"].append({
            "id": issue.id,
            "code": issue.issue_code,
            "severity": issue.severity,
            "state": issue.state,
            "evidence_kind": issue.evidence_kind,
            "order_item_id": issue.order_item_id,
            "remaining_quantity": remaining.get(
                (issue.evidence_kind, issue.evidence_id)
            ),
            "state_version": int(issue.state_version or 0),
        })

    return sorted(
        theo_don.values(),
        # Mới nhất trước như cũ; `order_id` giữ thứ tự tất định khi hai đơn cùng
        # mốc bán, và khi `sold_offline_at` NULL ở dữ liệu cũ.
        key=lambda muc: (muc["sold_at"] is not None, muc["sold_at"], muc["order_id"]),
        reverse=True,
    )


def _require_shop_owner_or_admin(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    """Chỉ chủ shop và ADMIN. Nhân viên kho KHÔNG được xác nhận thay.

    Xác nhận một vướng mắc là nhận trách nhiệm về một khoản tiền đã phát sinh -
    hẹp hơn hẳn quyền kiểm kê, cùng vòng người với quyền xem giá vốn.
    """
    shop = require_shop_access(db, shop_id, current_user)
    if not has_cost_visibility(shop, current_user):
        raise HTTPException(
            status_code=403,
            detail=tr("Chỉ chủ cửa hàng mới xác nhận được vướng mắc offline"),
        )
    return shop


def xac_nhan_van_de(
    db: Session,
    current_user: models.User,
    shop_id: int,
    issue_id: int,
    payload: OfflineIssueAcknowledge,
) -> Dict[str, Any]:
    """Chủ shop xác nhận đã xem một vướng mắc không có bằng chứng để đóng.

    Nút này KHÔNG sửa được kho, giá vốn hay tiền. Vì vậy nó chỉ áp cho các vướng
    mắc mà không có gì exact để đối chiếu; những cái còn lại phải đi đúng đường
    của chúng:

    - `TON_AM` exact: chỉ một phiếu kiểm kê dương mới chứng minh hàng đã về;
    - `SP_KHONG_CON`: map lại sản phẩm hoặc chấp nhận giá vốn unknown là I09-G,
      biến nút "đã xem" thành đường sửa giá vốn là ghi một con số không có thật.
    """
    _require_shop_owner_or_admin(db, shop_id, current_user)
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(
            status_code=400,
            detail=tr("Lý do xác nhận không được để trống"),
        )

    try:
        issue = (
            db.query(models.OfflineReceiptIssue)
            .join(models.Order, models.Order.id == models.OfflineReceiptIssue.order_id)
            .filter(
                models.OfflineReceiptIssue.id == issue_id,
                models.Order.shop_id == shop_id,
            )
            .first()
        )
        if issue is None:
            raise HTTPException(
                status_code=404, detail=tr("Không tìm thấy vướng mắc offline")
            )

        if issue.evidence_kind in (EVIDENCE_STOCK_DEFICIT, EVIDENCE_BATCH_DEFICIT):
            raise _xung_dot(
                ERROR_ISSUE_EVIDENCE_REQUIRED,
                "Vướng mắc này chỉ đóng được bằng phiếu kiểm kê thực tế",
            )
        if issue.issue_code == ISSUE_SP_KHONG_CON:
            raise _xung_dot(
                ERROR_ISSUE_RECOVERY_REQUIRED,
                "Vướng mắc này cần map lại sản phẩm hoặc xác nhận giá vốn",
            )
        if issue.issue_code not in ACKNOWLEDGEABLE_ISSUE_CODES and (
            issue.evidence_kind != EVIDENCE_LEGACY_AMBIGUOUS
        ):
            raise _xung_dot(
                ERROR_ISSUE_RECOVERY_REQUIRED,
                "Vướng mắc này không xác nhận bằng tay được",
            )

        # Đọc trước khi commit: `commit()` expire mọi ORM object, và response
        # không được phụ thuộc vào một lần refresh sau đó.
        order_id = int(issue.order_id)
        issue_code = str(issue.issue_code)
        old_state = issue.state
        old_version = int(issue.state_version or 0)
        new_version = old_version + 1
        acknowledged_at = canonical_time_text(datetime.utcnow())
        result = db.execute(
            text(
                """UPDATE offline_receipt_issues
                      SET state = 'ACKNOWLEDGED',
                          reason = :reason,
                          resolved_by_user_id = :actor,
                          resolved_at = :acknowledged_at,
                          state_version = state_version + 1
                    WHERE id = :id AND state = 'OPEN'
                      AND state_version = :version"""
            ),
            {
                "reason": reason,
                "actor": int(current_user.id),
                "acknowledged_at": acknowledged_at,
                "id": int(issue_id),
                "version": int(payload.state_version),
            },
        )
        if result.rowcount != 1 or old_state != STATE_OPEN or (
            old_version != int(payload.state_version)
        ):
            # Ai đó vừa xử lý xong, hoặc máy khách đang cầm phiên bản cũ. Ghi đè
            # là xóa mất quyết định vừa rồi mà không ai biết.
            raise _xung_dot(
                ERROR_ISSUE_STATE_CONFLICT,
                "Vướng mắc đã đổi trạng thái; vui lòng tải lại",
            )

        # Transaction-local: không dùng `log_system_action()` vì helper đó tự
        # commit và nuốt lỗi, tức là có thể có một xác nhận không còn dấu vết ai
        # đã bấm. `reason` thô không đi ra response, nhưng audit thì phải có.
        order_service._them_nhat_ky(
            db,
            int(current_user.id),
            "OFFLINE_ISSUE_ACK",
            (
                f"Đơn #{order_id} - vướng {issue_code}: "
                f"{old_state} -> {STATE_ACKNOWLEDGED} (v{new_version}). "
                f"Lý do: {reason}"
            ),
            shop_id=shop_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "id": int(issue_id),
        "order_id": order_id,
        "code": issue_code,
        "state": STATE_ACKNOWLEDGED,
        "state_version": new_version,
    }


# ---------------------------------------------------------------------------
# v1 offline ingest (I09-E+B2)
# ---------------------------------------------------------------------------

ISSUE_DONG_HO_LECH = "DONG_HO_LECH"
ISSUE_FINGERPRINT_LECH = "FINGERPRINT_LECH"  # client ≠ server fingerprint
EVIDENCE_TIME = "TIME"

ERROR_SEQUENCE_CONFLICT = "OFFLINE_SEQUENCE_CONFLICT"
ERROR_TIME_BEFORE_LEASE = "OFFLINE_TIME_BEFORE_LEASE"

# Confidence levels for sold_at_effective
CONFIDENCE_ANCHORED_CLIENT = "ANCHORED_CLIENT"
CONFIDENCE_BOUNDED = "BOUNDED"
CONFIDENCE_ANOMALY = "ANOMALY"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_canonical_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
    except (TypeError, ValueError) as exc:
        raise ValueError("timestamp is not canonical UTC-naive text") from exc
    if canonical_time_text(parsed) != value:
        raise ValueError("timestamp is not fixed-width canonical text")
    return parsed


def _raise_time_boundary(
    value: datetime,
    *,
    issued_at: datetime,
    expires_at: datetime,
    request_received_at: datetime,
) -> None:
    """Apply the locked boundary order to a derived/effective timestamp."""
    if value < issued_at:
        raise _xung_dot(
            ERROR_TIME_BEFORE_LEASE,
            "Giờ bán trước khi lease được phát hành",
        )
    if value > expires_at:
        raise _xung_dot(
            "OFFLINE_LEASE_EXPIRED",
            "Giờ bán nằm sau thời điểm lease hết hạn",
        )
    if value > request_received_at + timedelta(minutes=2):
        raise _bad_request(
            "OFFLINE_TIME_FUTURE",
            "Giờ bán chạy nhanh hơn 2 phút so với server",
        )


def _compute_sold_at_effective(
    anchor_server_time_utc: datetime,
    issued_at: datetime,
    expires_at: datetime,
    sold_at_client_utc: str,
    client_monotonic_ms: int,
    monotonic_valid: bool,
    request_received_at: datetime,
) -> Tuple[str, str, Optional[str], str]:
    """Compute sold_at_effective and bounds from monotonic clock anchor.

    Returns effective, confidence, optional upper bound and canonical client wall.
    """
    canonical_client = canonical_time_text_v1(sold_at_client_utc)
    client_dt = _parse_canonical_time(canonical_client)
    lower = anchor_server_time_utc + timedelta(milliseconds=client_monotonic_ms)

    if monotonic_valid:
        effective = lower
        upper = None
        confidence = CONFIDENCE_ANCHORED_CLIENT
    else:
        upper = min(
            lower + timedelta(minutes=5),
            expires_at,
            request_received_at + timedelta(minutes=2),
        )
        if upper < lower:
            # Do not swap a contradictory interval.  Classify the lower bound
            # with the same before/expiry/future precedence as normal input.
            _raise_time_boundary(
                lower,
                issued_at=issued_at,
                expires_at=expires_at,
                request_received_at=request_received_at,
            )
            raise _xung_dot("OFFLINE_LEASE_EXPIRED", "Cửa sổ thời gian lease rỗng")
        effective = max(lower, min(client_dt, upper))
        confidence = CONFIDENCE_BOUNDED

    _raise_time_boundary(
        effective,
        issued_at=issued_at,
        expires_at=expires_at,
        request_received_at=request_received_at,
    )
    if abs(client_dt - effective) > timedelta(minutes=10):
        confidence = CONFIDENCE_ANOMALY
    return (
        canonical_time_text(effective),
        confidence,
        canonical_time_text(upper) if upper is not None else None,
        canonical_client,
    )


def _check_sequence_conflict(
    db: Session,
    lease_id: str,
    device_id: str,
    offline_session_id: str,
    sequence: int,
    offline_uuid: str,
) -> None:
    """Check for SEQUENCE_CONFLICT: same lease+sequence but different UUID."""
    existing = (
        db.query(models.OfflineReceipt)
        .join(models.Order, models.Order.id == models.OfflineReceipt.order_id)
        .filter(
            models.OfflineReceipt.lease_id == lease_id,
            models.OfflineReceipt.device_id == device_id,
            models.OfflineReceipt.offline_session_id == offline_session_id,
            models.OfflineReceipt.sequence == sequence,
            models.OfflineReceipt.offline_uuid != offline_uuid,
        )
        .first()
    )
    if existing is not None:
        raise _xung_dot(
            ERROR_SEQUENCE_CONFLICT,
            f"Sequence {sequence} đã được dùng với một phiếu khác trong session này",
        )


def _sequence_is_non_monotonic(
    db: Session,
    *,
    lease_id: str,
    sequence: int,
    client_monotonic_ms: int,
) -> bool:
    predecessor = (
        db.query(models.OfflineReceipt)
        .filter(
            models.OfflineReceipt.lease_id == lease_id,
            models.OfflineReceipt.sequence < sequence,
        )
        .order_by(models.OfflineReceipt.sequence.desc())
        .first()
    )
    successor = (
        db.query(models.OfflineReceipt)
        .filter(
            models.OfflineReceipt.lease_id == lease_id,
            models.OfflineReceipt.sequence > sequence,
        )
        .order_by(models.OfflineReceipt.sequence.asc())
        .first()
    )
    return bool(
        predecessor is not None
        and predecessor.client_monotonic_ms is not None
        and int(predecessor.client_monotonic_ms) > client_monotonic_ms
        or successor is not None
        and successor.client_monotonic_ms is not None
        and int(successor.client_monotonic_ms) < client_monotonic_ms
    )


def _receipt_v1_consistent(
    db: Session,
    order: models.Order,
    registry: models.OfflineReceiptRegistry,
    receipt: models.OfflineReceipt,
) -> bool:
    """Reconstruct fsofr1 from durable lease/order/item/cash evidence."""
    lease = db.get(models.OfflineLease, receipt.lease_id)
    if lease is None:
        return False
    order_items = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == order.id)
        .all()
    )
    snapshots = (
        db.query(models.OfflineReceiptItem)
        .filter(models.OfflineReceiptItem.receipt_id == receipt.id)
        .order_by(models.OfflineReceiptItem.item_ordinal.asc())
        .all()
    )
    payments = (
        db.query(models.OrderPayment)
        .filter(models.OrderPayment.idempotency_key == f"offline:{order.offline_uuid}")
        .all()
    )
    if (
        not 1 <= len(order_items) <= 200
        or len(snapshots) != len(order_items)
        or len(payments) != 1
    ):
        return False
    payment = payments[0]
    try:
        item_by_id = {int(item.id): item for item in order_items}
        if len(item_by_id) != len(order_items):
            return False
        reconstructed_items = []
        seen_item_ids = set()
        for ordinal, snapshot in enumerate(snapshots, start=1):
            if int(snapshot.item_ordinal) != ordinal:
                return False
            order_item = item_by_id.get(int(snapshot.order_item_id))
            if order_item is None or int(order_item.id) in seen_item_ids:
                return False
            seen_item_ids.add(int(order_item.id))
            if (
                snapshot.product_name != order_item.product_name
                or _tien(snapshot.unit_price_vnd) != _tien(order_item.price)
                or int(snapshot.quantity) != int(order_item.quantity)
            ):
                return False
            if order_item.product_id is not None:
                product = db.get(models.Product, int(order_item.product_id))
                if (
                    int(order_item.product_id) != int(snapshot.claimed_product_id)
                    or product is None
                    or int(product.shop_id) != int(order.shop_id)
                ):
                    return False
            elif (
                db.query(models.Product.id)
                .filter(
                    models.Product.id == int(snapshot.claimed_product_id),
                    models.Product.shop_id == int(order.shop_id),
                )
                .first()
                is not None
            ):
                return False
            reconstructed_items.append(
                {
                    "product_id": int(snapshot.claimed_product_id),
                    "product_name": snapshot.product_name,
                    "unit_price_vnd": _tien(snapshot.unit_price_vnd),
                    "quantity": int(snapshot.quantity),
                }
            )
        if seen_item_ids != set(item_by_id):
            return False
        effective = _parse_canonical_time(receipt.sold_at_effective)
        client_wall = _parse_canonical_time(receipt.sold_at_client_utc)
        ingested = _parse_canonical_time(receipt.ingested_at)
        upper = (
            _parse_canonical_time(receipt.sold_at_upper_bound)
            if receipt.sold_at_upper_bound is not None
            else None
        )
        reconstructed = fingerprint_offline_receipt_v1(
            shop_id=int(order.shop_id),
            sold_at_client_utc=canonical_time_text(client_wall),
            client_monotonic_ms=int(receipt.client_monotonic_ms),
            monotonic_valid=upper is None,
            server_anchor_id=receipt.server_anchor_id,
            lease_id=receipt.lease_id,
            device_id=receipt.device_id,
            offline_session_id=receipt.offline_session_id,
            sequence=int(receipt.sequence),
            offline_uuid=receipt.offline_uuid,
            catalog_version=int(lease.catalog_version),
            catalog_snapshot_digest=lease.catalog_snapshot_digest,
            items=reconstructed_items,
            cash_tendered_vnd=_tien(order.cash_tendered_amount),
        )
        if [
            (
                int(item.product_id),
                item.product_name,
                int(item.unit_price_vnd),
                int(item.quantity),
            )
            for item in reconstructed.items
        ] != [
            (
                int(snapshot.claimed_product_id),
                snapshot.product_name,
                _tien(snapshot.unit_price_vnd),
                int(snapshot.quantity),
            )
            for snapshot in snapshots
        ]:
            return False
    except (AttributeError, TypeError, ValueError):
        return False

    # OWNER_RECOVERY creates a new server artifact and therefore has no client
    # fingerprint assertion.  NULL + mismatch=0 means "not supplied"; normal
    # LEASE_CLAIM receipts retain the exact client-vs-server comparison.
    mismatch = (
        False
        if receipt.attribution_kind == "OWNER_RECOVERY"
        and receipt.client_fingerprint is None
        else receipt.client_fingerprint != receipt.server_fingerprint
    )
    return bool(
        registry.state == "INGESTED"
        and registry.order_id == order.id == receipt.order_id
        and registry.offline_uuid == order.offline_uuid == receipt.offline_uuid
        and registry.shop_id == order.shop_id == lease.shop_id
        and registry.contract_version == receipt.contract_version == 1
        and registry.server_fingerprint == receipt.server_fingerprint
        and registry.superseded_by_offline_uuid is None
        and reconstructed.digest == receipt.server_fingerprint
        and reconstructed.total_vnd == _tien(order.total_amount)
        and receipt.client_fingerprint_mismatch == (1 if mismatch else 0)
        and receipt.offline_session_id == receipt.lease_id == lease.lease_id
        and receipt.device_id == lease.device_id == order.offline_device
        and receipt.server_anchor_id == lease.server_anchor_id
        and receipt.sold_by_claimed_user_id == order.created_by_user_id == lease.user_id
        and (
            receipt.attribution_kind == "LEASE_CLAIM"
            and receipt.time_confidence
            in (CONFIDENCE_ANCHORED_CLIENT, CONFIDENCE_BOUNDED, CONFIDENCE_ANOMALY)
            or receipt.attribution_kind == "OWNER_RECOVERY"
            and receipt.time_confidence == "RECOVERED"
        )
        and (receipt.time_confidence != CONFIDENCE_ANCHORED_CLIENT or upper is None)
        and (upper is None or upper >= effective)
        and _canonical_order_time(order.created_at) == receipt.sold_at_effective
        and _canonical_order_time(order.sold_offline_at) == receipt.sold_at_effective
        and canonical_time_text(ingested) == receipt.ingested_at
        and payment.order_id == order.id
        and payment.entry_type == ENTRY_SALE_CASH
        and _tien(payment.amount) == _tien(order.total_amount)
        and payment.created_by_user_id == receipt.sold_by_claimed_user_id
        and payment.shift_id == order.shift_id
        and _canonical_order_time(payment.created_at) == receipt.sold_at_effective
    )


def _tim_theo_uuid_v1(
    db: Session,
    shop_id: int,
    canonical: OfflineFingerprintV1,
) -> Optional[Tuple[models.Order, models.OfflineReceipt]]:
    order = (
        db.query(models.Order)
        .filter(models.Order.offline_uuid == canonical.offline_uuid)
        .first()
    )
    registry = db.get(models.OfflineReceiptRegistry, canonical.offline_uuid)
    receipt = (
        db.query(models.OfflineReceipt)
        .filter(models.OfflineReceipt.offline_uuid == canonical.offline_uuid)
        .first()
    )
    if (
        order is not None
        and int(order.shop_id) != int(shop_id)
        or registry is not None
        and int(registry.shop_id) != int(shop_id)
    ):
        raise _xung_dot(
            ERROR_UUID_OTHER_SHOP,
            "Mã phiếu offline đã được dùng cho một cửa hàng khác",
        )
    if order is None and registry is None and receipt is None:
        return None
    if registry is not None and int(registry.contract_version) != 1:
        raise _xung_dot(
            ERROR_FINGERPRINT_CONFLICT,
            "Mã phiếu offline đã được dùng với contract khác",
        )
    if (
        order is None
        or registry is None
        or receipt is None
        or not _receipt_v1_consistent(db, order, registry, receipt)
    ):
        raise _xung_dot(
            ERROR_REGISTRY_INCONSISTENT,
            "Dữ liệu bằng chứng phiếu offline không nhất quán",
        )
    if registry.server_fingerprint != canonical.digest:
        raise _xung_dot(
            ERROR_FINGERPRINT_CONFLICT,
            "Mã phiếu offline đã được dùng với nội dung khác",
        )
    return order, receipt


def _phan_hoi_v1(
    order: models.Order,
    receipt: models.OfflineReceipt,
    server_time_utc: str,
    moi: bool,
) -> Dict[str, Any]:
    return {
        "contract_version": 1,
        "order_id": order.id,
        "offline_uuid": order.offline_uuid,
        "total": _tien(order.total_amount),
        "shift_id": order.shift_id,
        "sold_by_user_id": receipt.sold_by_claimed_user_id,
        "synced_by_user_id": receipt.synced_by_user_id,
        "sold_at_effective": receipt.sold_at_effective,
        "time_confidence": receipt.time_confidence,
        "server_time_utc": server_time_utc,
        "issues": [x for x in (order.offline_issue or "").split(",") if x],
        "created": moi,
    }


def dong_bo_phieu_v1(
    db: Session,
    current_user: models.User,
    shop_id: int,
    phieu: OfflineOrderCreateV1,
    *,
    lease_token: str = "",
) -> Dict[str, Any]:
    """Ghi một phiếu offline contract v1 (I09-E+B2).

    Time: sold_at_effective = ANCHORED_CLIENT / BOUNDED / ANOMALY.
    Authorization: authorize_normal_v1_capability() → OfflineAttributionContext.
    Attribution: sold_by_claimed = payment_actor = shift_owner = lease user.
    CA: chọn theo sold_at_effective + sold_by_claimed.
    Fingerprint: server recomputes fsofr1:, client_fp for comparison only.
    Token: chỉ từ X-Offline-Lease-Token header.
    """
    from . import offline_lease_service

    canonical: Optional[OfflineFingerprintV1] = None
    request_received_at: Optional[datetime] = None
    # Authentication has already happened at the HTTP boundary.  Close its read
    # snapshot, take the shop write lock, and perform the single I09-D normal-v1
    # authorization seam inside the financial transaction.
    db.rollback()
    try:
        order_service._lock_shop_for_order(db, shop_id)
        request_received_at = _utcnow()
        ctx = offline_lease_service.authorize_normal_v1_capability(
            db,
            current_user=current_user,
            shop_id=shop_id,
            lease_id=phieu.lease_id,
            lease_token=lease_token,
            device_id=phieu.device_id,
            offline_session_id=phieu.offline_session_id,
            request_received_at=request_received_at,
        )
        if (
            ctx.contract_version != 1
            or phieu.catalog_version != ctx.catalog_version
            or phieu.catalog_snapshot_digest != ctx.catalog_snapshot_digest
            or phieu.server_anchor_id != ctx.server_anchor_id
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": offline_lease_service.ERROR_BINDING_MISMATCH,
                    "message": tr("Binding credential offline không khớp"),
                },
            )
        sold_by_user_id = int(ctx.sold_by_claimed_user_id)

        try:
            (
                sold_at_effective,
                time_confidence,
                sold_at_upper_bound,
                sold_at_client_canonical,
            ) = _compute_sold_at_effective(
                anchor_server_time_utc=ctx.anchor_server_time_utc,
                issued_at=ctx.issued_at,
                expires_at=ctx.expires_at,
                sold_at_client_utc=phieu.sold_at_client_utc,
                client_monotonic_ms=phieu.client_monotonic_ms,
                monotonic_valid=phieu.monotonic_valid,
                request_received_at=request_received_at,
            )
            canonical = fingerprint_offline_receipt_v1(
                shop_id=shop_id,
                sold_at_client_utc=sold_at_client_canonical,
                client_monotonic_ms=phieu.client_monotonic_ms,
                monotonic_valid=phieu.monotonic_valid,
                server_anchor_id=phieu.server_anchor_id,
                lease_id=phieu.lease_id,
                device_id=phieu.device_id,
                offline_session_id=phieu.offline_session_id,
                sequence=phieu.sequence,
                offline_uuid=phieu.offline_uuid,
                catalog_version=phieu.catalog_version,
                catalog_snapshot_digest=phieu.catalog_snapshot_digest,
                items=[
                    {
                        "product_id": item.product_id,
                        "product_name": item.product_name,
                        "unit_price_vnd": item.unit_price_vnd,
                        "quantity": item.quantity,
                    }
                    for item in phieu.items
                ],
                cash_tendered_vnd=phieu.cash_tendered,
            )
        except OfflineTotalOverflowError:
            raise _bad_request(
                "OFFLINE_TOTAL_OVERFLOW",
                "Tổng tiền phiếu vượt giới hạn",
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "OFFLINE_RECEIPT_MALFORMED",
                    "message": tr("Phiếu offline không thể chuẩn hóa an toàn"),
                },
            ) from exc

        uuid = canonical.offline_uuid
        da_co = _tim_theo_uuid_v1(db, shop_id, canonical)
        if da_co is not None:
            durable_order, durable_receipt = da_co
            response = _phan_hoi_v1(
                durable_order,
                durable_receipt,
                canonical_time_text(request_received_at),
                moi=False,
            )
            db.rollback()
            return response

        _check_sequence_conflict(
            db,
            lease_id=phieu.lease_id,
            device_id=phieu.device_id,
            offline_session_id=phieu.offline_session_id,
            sequence=phieu.sequence,
            offline_uuid=uuid,
        )
        if _sequence_is_non_monotonic(
            db,
            lease_id=phieu.lease_id,
            sequence=phieu.sequence,
            client_monotonic_ms=phieu.client_monotonic_ms,
        ):
            time_confidence = CONFIDENCE_ANOMALY

        effective_dt = _parse_canonical_time(sold_at_effective)

        van_de: List[str] = []

        # Client fingerprint mismatch → INFO issue (only on first ingest)
        fingerprint_lech = phieu.client_fingerprint != canonical.digest
        if fingerprint_lech:
            van_de.append(ISSUE_FINGERPRINT_LECH)
        if time_confidence == CONFIDENCE_ANOMALY:
            van_de.append(ISSUE_DONG_HO_LECH)

        # ---- Build order items (server-computed total from fingerprint) ----
        tong, dong_hang, line_issues = _prepare_offline_sale_lines(
            db,
            shop_id=shop_id,
            canonical_items=canonical.items,
        )
        if tong != canonical.total_vnd:
            raise _xung_dot(
                ERROR_REGISTRY_INCONSISTENT,
                "Tổng canonical không khớp financial core",
            )
        for code in line_issues:
            if code not in van_de:
                van_de.append(code)
        tendered = _tien(phieu.cash_tendered)
        if tendered < tong:
            raise _bad_request(
                "OFFLINE_TENDER_TOO_LOW",
                tr(
                    "Tiền khách đưa ({tendered}) nhỏ hơn tổng đơn ({total})",
                    tendered=f"{tendered:,.0f}đ",
                    total=f"{tong:,.0f}đ",
                ),
            )

        # ---- CA by effective time + sold_by_claimed ----
        ca = _ca_phu_gio_ban(
            db,
            shop_id,
            ctx.shift_owner_user_id,
            effective_dt,
        )
        if ca is None:
            van_de.append(ISSUE_KHONG_CO_CA)
        elif ca.status != "OPEN":
            van_de.append(ISSUE_CA_DA_CHOT)

        # ---- Atomic: Order + items + payment + inventory + cost + registry + receipt + audit ----
        ingested_at = request_received_at
        now_text = canonical_time_text(ingested_at)

        don = models.Order(
            shop_id=shop_id,
            created_by_user_id=ctx.created_by_user_id,
            shift_id=ca.id if ca else None,
            total_amount=tong,
            discount_amount=0,
            payment_method=order_service.PAYMENT_METHOD_CASH,
            status=order_service.STATUS_PAID,
            cash_paid_amount=tong,
            cash_tendered_amount=tendered,
            cash_change_amount=max(tendered - tong, 0),
            created_at=effective_dt,
            sold_offline_at=effective_dt,
            offline_uuid=uuid,
            offline_device=phieu.device_id,
        )
        db.add(don)
        db.flush()

        # Registry
        registry = models.OfflineReceiptRegistry(
            offline_uuid=uuid,
            shop_id=shop_id,
            order_id=don.id,
            server_fingerprint=canonical.digest,
            contract_version=1,
            state="INGESTED",
            superseded_by_offline_uuid=None,
            created_at=now_text,
            updated_at=now_text,
            state_version=0,
        )
        db.add(registry)
        db.flush()

        # Receipt
        receipt = models.OfflineReceipt(
            order_id=don.id,
            offline_uuid=uuid,
            contract_version=1,
            lease_id=phieu.lease_id,
            device_id=phieu.device_id,
            offline_session_id=phieu.offline_session_id,
            sequence=phieu.sequence,
            server_fingerprint=canonical.digest,
            client_fingerprint=phieu.client_fingerprint,
            client_fingerprint_mismatch=1 if fingerprint_lech else 0,
            sold_by_claimed_user_id=ctx.sold_by_claimed_user_id,
            synced_by_user_id=ctx.synced_by_user_id,
            attribution_kind=ctx.attribution_kind,
            sold_at_effective=sold_at_effective,
            sold_at_client_utc=sold_at_client_canonical,
            sold_at_upper_bound=sold_at_upper_bound,
            time_confidence=time_confidence,
            client_monotonic_ms=phieu.client_monotonic_ms,
            server_anchor_id=phieu.server_anchor_id,
            ingested_at=now_text,
        )
        db.add(receipt)
        db.flush()

        # Order items + inventory
        for item_ordinal, cap in enumerate(dong_hang, start=1):
            prod: Optional[models.Product] = cap["prod"]
            mh = cap["mh"]

            da_lay: List[inventory_service.CostAllocation] = []
            thieu = mh.quantity if prod is None else 0
            if prod is not None:
                da_lay, thieu = _tru_ton_chiu_thieu(db, prod, mh.quantity)
                if thieu > 0 and ISSUE_TON_AM not in van_de:
                    van_de.append(ISSUE_TON_AM)

            known_qty, allocated_unknown_qty, cost_basis = (
                inventory_service.allocation_totals(da_lay)
            )
            allocated_qty = sum(a.quantity for a in da_lay)
            unallocated_qty = max(int(mh.quantity) - allocated_qty, 0)
            unknown_qty = allocated_unknown_qty + unallocated_qty
            line_total = checked_multiply(mh.quantity, mh.unit_price_vnd)

            dong = models.OrderItem(
                order_id=don.id,
                # Only verified same-shop catalog identity enters the business
                # FK.  The exact client claim is durable evidence below.
                product_id=prod.id if prod is not None else None,
                product_name=mh.product_name,
                price=mh.unit_price_vnd,
                quantity=mh.quantity,
                discount_vnd=0,
                loyalty_discount_vnd=0,
                net_amount_vnd=line_total,
                cost_known_qty=known_qty,
                cost_unknown_qty=unknown_qty,
                cost_basis_vnd=cost_basis,
            )
            db.add(dong)
            db.flush()

            db.add(
                models.OfflineReceiptItem(
                    receipt_id=receipt.id,
                    order_item_id=dong.id,
                    item_ordinal=item_ordinal,
                    claimed_product_id=mh.product_id,
                    product_name=mh.product_name,
                    unit_price_vnd=mh.unit_price_vnd,
                    quantity=mh.quantity,
                )
            )

            if cap["thieu_sp"]:
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_SP_KHONG_CON,
                        evidence_kind=EVIDENCE_CATALOG,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                    )
                )
            elif cap["gia_doi"]:
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_GIA_DOI,
                        evidence_kind=EVIDENCE_CATALOG,
                        severity=SEVERITY_INFO,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id if prod else None,
                        resolution_kind=RESOLUTION_INFORMATIONAL,
                        resolved_by_user_id=sold_by_user_id,
                    )
                )

            if prod is not None and prod.track_batches and unallocated_qty > 0:
                bang_chung_lo = models.OfflineBatchStockDeficit(
                    order_item_id=dong.id,
                    product_id=prod.id,
                    deficit_quantity=unallocated_qty,
                    remaining_quantity=unallocated_qty,
                    state_version=0,
                )
                db.add(bang_chung_lo)
                db.flush()
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_TON_AM,
                        evidence_kind=EVIDENCE_BATCH_DEFICIT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id,
                        evidence_id=bang_chung_lo.id,
                    )
                )
            elif prod is not None and not prod.track_batches and thieu > 0:
                bang_chung = models.OfflineStockDeficit(
                    order_item_id=dong.id,
                    product_id=prod.id,
                    deficit_quantity=thieu,
                    remaining_quantity=thieu,
                    state_version=0,
                )
                db.add(bang_chung)
                db.flush()
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ISSUE_TON_AM,
                        evidence_kind=EVIDENCE_STOCK_DEFICIT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                        order_item_id=dong.id,
                        product_id=prod.id,
                        evidence_id=bang_chung.id,
                    )
                )

            if prod is not None and prod.track_batches:
                for allocation in da_lay:
                    lo = allocation.batch
                    if lo is None:
                        raise HTTPException(
                            status_code=409,
                            detail=tr("Thiếu provenance lô offline"),
                        )
                    db.add(
                        models.OrderItemBatch(
                            order_item_id=dong.id,
                            batch_id=lo.id,
                            quantity=allocation.quantity,
                            cost_known_qty=allocation.known_qty,
                            cost_unknown_qty=allocation.unknown_qty,
                            cost_basis_vnd=allocation.cost_basis_vnd,
                        )
                    )

        # Issues about shift
        for ma_ca in (ISSUE_CA_DA_CHOT, ISSUE_KHONG_CO_CA):
            if ma_ca in van_de:
                db.add(
                    _issue_moi(
                        order_id=don.id,
                        issue_code=ma_ca,
                        evidence_kind=EVIDENCE_SHIFT,
                        severity=SEVERITY_ACTION,
                        opened_at=now_text,
                    )
                )

        # FINGERPRINT_LECH issue
        if fingerprint_lech:
            db.add(
                _issue_moi(
                    order_id=don.id,
                    issue_code=ISSUE_FINGERPRINT_LECH,
                    evidence_kind=EVIDENCE_CATALOG,
                    severity=SEVERITY_INFO,
                    opened_at=now_text,
                    resolution_kind=RESOLUTION_INFORMATIONAL,
                    resolved_by_user_id=sold_by_user_id,
                )
            )

        if ISSUE_DONG_HO_LECH in van_de:
            db.add(
                _issue_moi(
                    order_id=don.id,
                    issue_code=ISSUE_DONG_HO_LECH,
                    evidence_kind=EVIDENCE_TIME,
                    severity=SEVERITY_ACTION,
                    opened_at=now_text,
                )
            )

        # Compatible issue string
        if van_de:
            don.offline_issue = ",".join(van_de)

        # Cash payment entry
        _add_offline_cash_payment(
            db,
            order_id=don.id,
            amount=tong,
            offline_uuid=uuid,
            actor_user_id=ctx.payment_actor_user_id,
            shift_id=ca.id if ca else None,
            sold_at=effective_dt,
            note="Bán tiền mặt khi mất mạng (contract v1)",
        )

        # Audit
        order_service._them_nhat_ky(
            db,
            ctx.synced_by_user_id,
            "OFFLINE_SALE_V1",
            (
                f"Đơn #{don.id} bán offline v1 lúc {sold_at_effective[:19]} "
                f"- {tong:,.0f}đ"
                + (f" - vướng: {don.offline_issue}" if don.offline_issue else "")
            ),
            shop_id=shop_id,
        )

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if canonical is not None and _is_uuid_uniqueness_error(exc):
            fresh = Session(bind=db.get_bind())
            try:
                durable = _tim_theo_uuid_v1(fresh, shop_id, canonical)
                if durable is not None:
                    order, durable_receipt = durable
                    return _phan_hoi_v1(
                        order,
                        durable_receipt,
                        canonical_time_text(request_received_at or _utcnow()),
                        moi=False,
                    )
            finally:
                fresh.close()
        if canonical is not None and (
            "offline_receipts.lease_id, offline_receipts.sequence" in message
            or "ux_offline_receipts_lease_sequence" in message
        ):
            fresh = Session(bind=db.get_bind())
            try:
                existing = (
                    fresh.query(models.OfflineReceipt)
                    .filter(
                        models.OfflineReceipt.lease_id == phieu.lease_id,
                        models.OfflineReceipt.sequence == phieu.sequence,
                    )
                    .first()
                )
                if existing is not None and existing.offline_uuid != canonical.offline_uuid:
                    raise _xung_dot(
                        ERROR_SEQUENCE_CONFLICT,
                        "Sequence đã được dùng với một phiếu khác",
                    )
            finally:
                fresh.close()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(don)
    db.refresh(receipt)
    return _phan_hoi_v1(
        don,
        receipt,
        canonical_time_text(request_received_at or ingested_at),
        moi=True,
    )
