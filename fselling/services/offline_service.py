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

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..core.money import checked_add, checked_multiply, exact_vnd
from ..dependencies import (
    PERMISSION_SALE,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.order import OfflineOrderCreate
from . import inventory_service, order_service
from .offline_fingerprint import (
    OfflineFingerprintV0,
    canonical_time_text,
    fingerprint_offline_receipt_v0,
)

# Vướng mắc lúc ghi phiếu. Nối bằng dấu phẩy vào `orders.offline_issue` để nổi
# lên màn Đối Soát. Đơn KHÔNG bị chặn vì lý do nào trong số này.
ISSUE_TON_AM = "TON_AM"              # kho không đủ hàng lúc sync
ISSUE_CA_DA_CHOT = "CA_DA_CHOT"      # ca lúc bán nay đã kết ca
ISSUE_KHONG_CO_CA = "KHONG_CO_CA"    # không ca nào phủ giờ bán
ISSUE_SP_KHONG_CON = "SP_KHONG_CON"  # sản phẩm đã bị xóa giữa bán và sync
ISSUE_GIA_DOI = "GIA_DOI"            # giá trên phiếu khác giá hiện tại

# Đã nằm trong `CASH_PAYMENT_IN_TYPES` của shift_service nên tự được tính vào
# két của ca. ĐỪNG thêm `CashMovement` kèm theo — sẽ cộng két hai lần.
ENTRY_SALE_CASH = "SALE_CASH"

ERROR_FINGERPRINT_CONFLICT = "OFFLINE_RECEIPT_FINGERPRINT_CONFLICT"
ERROR_UUID_OTHER_SHOP = "OFFLINE_RECEIPT_UUID_OTHER_SHOP"
ERROR_REGISTRY_INCONSISTENT = "OFFLINE_RECEIPT_REGISTRY_INCONSISTENT"
ERROR_UUID_UNAVAILABLE = "OFFLINE_RECEIPT_UUID_UNAVAILABLE"

MONEY_EPSILON = 0


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
        raise HTTPException(status_code=400, detail=tr("Thiếu mã phiếu offline"))

    # Fingerprint is already known before the first duplicate decision.  A
    # matching durable registry is a retry; a different document is a conflict.
    da_co = _tim_theo_uuid(db, shop_id, uuid, canonical.fingerprint)
    if da_co is not None:
        return _phan_hoi(da_co, moi=False)

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

        luc_ban = canonical.sold_at_utc
        ingested_at = datetime.utcnow()
        if luc_ban > ingested_at:
            # Đồng hồ máy bán chạy nhanh. Nhận giờ tương lai thì đơn rơi ra ngoài mọi
            # báo cáo theo ngày và không ca nào phủ được nó.
            raise HTTPException(
                status_code=400,
                detail=tr("Giờ bán nằm ở tương lai; kiểm lại đồng hồ máy bán"),
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
        tong = 0
        dong_hang: List[Dict[str, Any]] = []
        for mh in canonical.items:
            # Lọc kèm shop_id: thiếu điều kiện đó thì đoán product_id là bán được
            # hàng của shop khác (bẫy 22).
            prod = (
                db.query(models.Product)
                .filter(
                    models.Product.id == mh.product_id,
                    models.Product.shop_id == shop_id,
                )
                .first()
            )
            try:
                tien_dong = checked_multiply(mh.quantity, mh.unit_price_vnd)
                tong = checked_add(tong, tien_dong)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=tr("Tổng tiền phiếu vượt giới hạn"),
                )
            dong_hang.append({"prod": prod, "mh": mh})

            if prod is None:
                # Sản phẩm bị xóa giữa lúc bán và lúc sync. Vẫn ghi dòng tiền bằng
                # tên đã chụp, để khoản tiền trong két còn tra được về đâu.
                if ISSUE_SP_KHONG_CON not in van_de:
                    van_de.append(ISSUE_SP_KHONG_CON)
            elif _tien(prod.price) != mh.unit_price_vnd:
                if ISSUE_GIA_DOI not in van_de:
                    van_de.append(ISSUE_GIA_DOI)

        tendered = _tien(phieu.cash_tendered)
        if tendered < tong:
            # Tiền khách đưa ít hơn tổng đơn là phiếu sai, không phải xung đột dữ
            # liệu. Nhận vào là ghi một khoản thu không có thật.
            raise HTTPException(
                status_code=400,
                detail=tr(
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

            if prod is not None and prod.track_batches and unallocated_qty > 0:
                # Do not invent a batch for goods that had already left the shop.
                # This row is the durable, per-product/exact-quantity evidence that
                # makes the deliberate Product.stock < SUM(batch.quantity) gap
                # restart-verifiable until a batch stocktake reconciles it.
                db.add(
                    models.OfflineBatchStockDeficit(
                        order_item_id=dong.id,
                        product_id=prod.id,
                        deficit_quantity=unallocated_qty,
                        remaining_quantity=unallocated_qty,
                        resolution_kind=None,
                        state_version=0,
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

        if van_de:
            don.offline_issue = ",".join(van_de)

        # ---- Bút toán tiền mặt vào két của ca ----
        # `idempotency_key` là lớp chặn thứ hai sau registry/order UUID.
        db.add(
            models.OrderPayment(
                order_id=don.id,
                entry_type=ENTRY_SALE_CASH,
                amount=tong,
                idempotency_key=f"offline:{uuid}",
                created_by_user_id=user_id,
                shift_id=ca.id if ca else None,
                note="Bán tiền mặt khi mất mạng",
                created_at=luc_ban,
            )
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


def danh_sach_can_xu_ly(db: Session, shop_id: int) -> List[Dict[str, Any]]:
    """Đơn offline có vướng mắc, để chủ shop xử lý. Mới nhất trước."""
    don = (
        db.query(models.Order)
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.offline_issue.isnot(None),
        )
        .order_by(models.Order.sold_offline_at.desc())
        .all()
    )
    return [
        {
            "order_id": o.id,
            "sold_at": o.sold_offline_at,
            "total": _tien(o.total_amount),
            "device": o.offline_device,
            "shift_id": o.shift_id,
            "issues": [x for x in (o.offline_issue or "").split(",") if x],
        }
        for o in don
    ]
