"""Phiếu nhập và công nợ nhà cung cấp.

Đây là một sổ tiền đi cùng một lần tăng kho. Bốn bất biến quan trọng nhất:

* DRAFT không được đụng tồn, giá vốn, lô, công nợ hay két.
* Confirm phải nguyên tử: hoặc tất cả dòng kho + công nợ + tiền trả cùng ghi,
  hoặc không có gì ghi.
* Mọi retry dùng cùng ``operation_id`` không được nhân đôi kho/tiền; dùng lại
  mã cho payload khác phải trả 409.
* Tiền mặt trả NCC chỉ đi qua đúng một ``CashMovement PAY_OUT`` của ca OPEN;
  chuyển khoản/tiền ngoài két không được đụng ca.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from conftest import (
    _unique,
    admin_token,
    auth,
    create_product,
    new_staff,
    seller_with_shop,
)
from fselling import models
from fselling.core import bootstrap
from fselling.core.database import SessionLocal
from fselling.core.numeric_limits import MAX_SAFE_QUANTITY, MAX_SAFE_VND
from fselling.services import catalog_service, supplier_service


def _op(prefix: str = "op") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _ngay(delta: int = 0) -> str:
    return (datetime.utcnow() + timedelta(days=delta)).strftime("%Y-%m-%d")


def _unwrap(body, *names):
    """Cho phép response trả thẳng object hoặc bọc theo tên thực thể."""
    if not isinstance(body, dict):
        return body
    for name in names:
        nested = body.get(name)
        if isinstance(nested, dict):
            return nested
    return body


def _entity_id(body, *names) -> int:
    entity = _unwrap(body, *names)
    value = entity.get("id")
    if value is None:
        for key in ("supplier_id", "receipt_id", "payment_id"):
            if entity.get(key) is not None:
                value = entity[key]
                break
    assert value is not None, body
    return int(value)


def _supplier_payload(**changes):
    payload = {
        "name": _unique("NCC"),
        "phone": "090" + uuid.uuid4().hex[:7],
        "tax_code": uuid.uuid4().hex[:10],
        "address": "123 Đường nhập hàng",
        "note": "Nhà cung cấp kiểm thử",
        "opening_balance": 0,
        "operation_id": _op("supplier"),
    }
    payload.update(changes)
    return payload


def _create_supplier(client, ctx, *, token=None, expected=200, **changes):
    payload = _supplier_payload(**changes)
    response = client.post(
        f"/api/suppliers/{ctx['shop_id']}",
        json=payload,
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == expected, response.text
    if expected != 200:
        return response
    return _unwrap(response.json(), "supplier")


def _receipt_payload(ctx, supplier_id: int, items=None, **changes):
    payload = {
        "supplier_id": supplier_id,
        "supplier_invoice_number": _unique("HDN"),
        "received_date": _ngay(),
        "due_date": _ngay(30),
        "note": "Phiếu nhập kiểm thử",
        "operation_id": _op("receipt"),
        "items": items
        or [
            {
                "product_id": ctx["product"]["id"],
                "quantity": 2,
                "unit_cost": 40_000,
            }
        ],
    }
    payload.update(changes)
    return payload


def _create_receipt(
    client,
    ctx,
    supplier_id: int,
    *,
    token=None,
    expected=200,
    items=None,
    **changes,
):
    payload = _receipt_payload(ctx, supplier_id, items=items, **changes)
    response = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == expected, response.text
    if expected != 200:
        return response
    return _unwrap(response.json(), "receipt", "purchase_receipt")


def _confirm(
    client,
    ctx,
    receipt_id: int,
    *,
    paid_amount: int = 0,
    method: str = "OUTSIDE",
    operation_id: str | None = None,
    draft_fingerprint: str | None = None,
    token=None,
):
    request_token = token or ctx["token"]
    if draft_fingerprint is None:
        detail = client.get(
            f"/api/purchase-receipts/receipt/{receipt_id}",
            headers=auth(request_token),
        )
        assert detail.status_code == 200, detail.text
        draft_fingerprint = detail.json()["draft_fingerprint"]
    return client.post(
        f"/api/purchase-receipts/receipt/{receipt_id}/confirm",
        json={
            "operation_id": operation_id or _op("confirm"),
            "draft_fingerprint": draft_fingerprint,
            "paid_amount": paid_amount,
            "method": method,
            "reference": "REF-NHAP",
            "note": "Thanh toán khi xác nhận",
        },
        headers=auth(request_token),
    )


def _payment(
    client,
    ctx,
    supplier_id: int,
    amount: int,
    *,
    method: str = "OUTSIDE",
    operation_id: str | None = None,
    token=None,
):
    return client.post(
        f"/api/suppliers/member/{supplier_id}/payments",
        json={
            "amount": amount,
            "method": method,
            "reference": "REF-TRA-NO",
            "note": "Trả công nợ kiểm thử",
            "operation_id": operation_id or _op("payment"),
        },
        headers=auth(token or ctx["token"]),
    )


def _open_shift(client, ctx, amount: int = 500_000, *, token=None):
    response = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": amount, "note": "Tiền đầu ca"},
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _product(product_id: int):
    session = SessionLocal()
    try:
        return session.query(models.Product).filter(models.Product.id == product_id).one()
    finally:
        session.close()


def _receipt(receipt_id: int):
    session = SessionLocal()
    try:
        return (
            session.query(models.PurchaseReceipt)
            .filter(models.PurchaseReceipt.id == receipt_id)
            .one()
        )
    finally:
        session.close()


def _supplier(supplier_id: int):
    session = SessionLocal()
    try:
        return session.query(models.Supplier).filter(models.Supplier.id == supplier_id).one()
    finally:
        session.close()


def _supplier_detail(client, ctx, supplier_id: int, *, token=None) -> dict:
    response = client.get(
        f"/api/suppliers/member/{supplier_id}",
        headers=auth(token or ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _debt(client, ctx, supplier_id: int, *, token=None) -> float:
    body = _unwrap(_supplier_detail(client, ctx, supplier_id, token=token), "supplier")
    assert "payable_balance" in body, body
    return float(body["payable_balance"])


def _overdue(client, ctx, supplier_id: int) -> float:
    body = _unwrap(_supplier_detail(client, ctx, supplier_id), "supplier")
    assert "overdue_amount" in body, body
    return float(body["overdue_amount"])


def _tracked_product(client, ctx):
    response = client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={
            "name": _unique("HangLo"),
            "price": 90_000,
            "stock": 0,
            "category_id": ctx["category_id"],
            "track_batches": "true",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _hold_inventory_lock(monkeypatch):
    """Giữ request đầu tiên ngay sau khi đã lấy khóa kho của shop.

    Dùng để ép một thao tác kho đứng trước phiếu nhập, rồi kiểm tra confirm
    thật sự phải chờ. Nếu một đường nghiệp vụ quên lấy khóa chung, test sẽ
    không bao giờ nhận được ``lock_ready`` và thất bại rõ ràng.
    """
    lock_ready = threading.Event()
    release_lock = threading.Event()
    original = catalog_service.inventory_service.lock_shop_for_inventory

    def held_lock(db, shop_id):
        original(db, shop_id)
        lock_ready.set()
        assert release_lock.wait(5), "Không nhận được tín hiệu nhả khóa kho"

    monkeypatch.setattr(
        catalog_service.inventory_service,
        "lock_shop_for_inventory",
        held_lock,
    )
    return lock_ready, release_lock


# ---------- Nhà cung cấp và số dư đầu kỳ ----------


def test_tao_ncc_va_so_du_dau_ky_chi_ghi_mot_lan(client):
    ctx = seller_with_shop(client)
    operation_id = _op("opening")
    payload = _supplier_payload(
        opening_balance=350_000,
        opening_date=_ngay(-10),
        opening_due_date=_ngay(10),
        opening_note="Nợ mang sang từ sổ cũ",
        operation_id=operation_id,
    )

    first = client.post(
        f"/api/suppliers/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    retry = client.post(
        f"/api/suppliers/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    assert first.status_code == retry.status_code == 200
    supplier_id = _entity_id(first.json(), "supplier")
    assert _entity_id(retry.json(), "supplier") == supplier_id
    assert _debt(client, ctx, supplier_id) == 350_000

    session = SessionLocal()
    try:
        entries = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.supplier_id == supplier_id,
            models.SupplierPayableEntry.entry_type == "OPENING",
        ).all()
        assert len(entries) == 1
        assert float(entries[0].amount) == 350_000
    finally:
        session.close()


def test_ncc_so_du_0_khong_tao_but_toan_ao(client):
    ctx = seller_with_shop(client)
    supplier = _create_supplier(client, ctx, opening_balance=0)
    supplier_id = _entity_id(supplier)
    assert _debt(client, ctx, supplier_id) == 0

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.supplier_id == supplier_id
        ).count() == 0
    finally:
        session.close()


def test_retry_tao_ncc_cung_ma_khac_payload_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    operation_id = _op("supplier")
    payload = _supplier_payload(operation_id=operation_id, opening_balance=100_000)
    assert client.post(
        f"/api/suppliers/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    ).status_code == 200

    payload["opening_balance"] = 200_000
    conflict = client.post(
        f"/api/suppliers/{ctx['shop_id']}", json=payload, headers=auth(ctx["token"])
    )
    assert conflict.status_code == 409


def test_retry_tao_ncc_bo_trong_ngay_qua_nua_dem_van_cung_ket_qua(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    payload = _supplier_payload(opening_balance=123_456)
    payload.pop("opening_date", None)
    monkeypatch.setattr(supplier_service, "_today_vn", lambda: "2026-08-07")
    first = client.post(
        f"/api/suppliers/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    monkeypatch.setattr(supplier_service, "_today_vn", lambda: "2026-08-08")
    retry = client.post(
        f"/api/suppliers/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == retry.status_code == 200
    supplier_id = _entity_id(first.json(), "supplier")
    assert supplier_id == _entity_id(retry.json(), "supplier")

    session = SessionLocal()
    try:
        entry = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.supplier_id == supplier_id,
            models.SupplierPayableEntry.entry_type == "OPENING",
        ).one()
        assert entry.entry_date == "2026-08-07"
    finally:
        session.close()


@pytest.mark.parametrize(
    "opening_balance",
    [-1, 1.5, True, False, "1", "NaN", "Infinity"],
)
def test_so_du_dau_ky_chi_nhan_so_nguyen_khong_am(client, opening_balance):
    ctx = seller_with_shop(client)
    response = _create_supplier(
        client, ctx, opening_balance=opening_balance, expected=422
    )
    assert response.status_code == 422


# ---------- DRAFT không được tác động sổ ----------


def test_draft_khong_doi_ton_gia_von_lo_cong_no_hay_ket(client):
    ctx = seller_with_shop(client)
    supplier = _create_supplier(client, ctx)
    supplier_id = _entity_id(supplier)
    shift = _open_shift(client, ctx, 500_000)
    receipt = _create_receipt(client, ctx, supplier_id)
    receipt_id = _entity_id(receipt)

    assert _receipt(receipt_id).status == "DRAFT"
    product = _product(ctx["product"]["id"])
    assert product.stock == 10
    assert product.cost_price is None
    assert _debt(client, ctx, supplier_id) == 0

    shift_after = client.get(
        f"/api/shifts/{shift['id']}", headers=auth(ctx["token"])
    ).json()
    assert shift_after["expected_cash_amount"] == 500_000

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id
        ).count() == 0
        assert session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).count() == 0
    finally:
        session.close()


def test_draft_duoc_sua_xoa_nhung_posted_bat_bien(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    updated_payload = {
        "supplier_id": supplier_id,
        "supplier_invoice_number": "HD-SUA-DRAFT",
        "received_date": _ngay(-1),
        "due_date": _ngay(20),
        "note": "Đã sửa trước khi chốt",
        "items": [{
            "product_id": ctx["product"]["id"],
            "quantity": 3,
            "unit_cost": 50_000,
        }],
    }
    updated = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json=updated_payload,
        headers=auth(ctx["token"]),
    )
    assert updated.status_code == 200, updated.text
    assert _receipt(receipt_id).total_amount == 150_000
    assert _product(ctx["product"]["id"]).stock == 10

    assert _confirm(client, ctx, receipt_id).status_code == 200
    stock_after = _product(ctx["product"]["id"]).stock
    debt_after = _debt(client, ctx, supplier_id)
    immutable_update = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json={**updated_payload, "items": [{
            "product_id": ctx["product"]["id"],
            "quantity": 99,
            "unit_cost": 1,
        }]},
        headers=auth(ctx["token"]),
    )
    immutable_delete = client.delete(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    )
    assert immutable_update.status_code == 409
    assert immutable_delete.status_code == 409
    assert _receipt(receipt_id).status == "POSTED"
    assert _product(ctx["product"]["id"]).stock == stock_after
    assert _debt(client, ctx, supplier_id) == debt_after


def test_xoa_draft_xoa_ca_dong_nhung_khong_dung_kho(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    deleted = client.delete(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    )
    assert deleted.status_code == 200, deleted.text
    assert _product(ctx["product"]["id"]).stock == 10
    session = SessionLocal()
    try:
        assert session.query(models.PurchaseReceipt).filter(
            models.PurchaseReceipt.id == receipt_id
        ).count() == 0
        assert session.query(models.PurchaseReceiptItem).filter(
            models.PurchaseReceiptItem.receipt_id == receipt_id
        ).count() == 0
    finally:
        session.close()


def test_confirm_tinh_tong_tu_dong_va_tang_kho_nhieu_dong_nguyen_tu(client):
    ctx = seller_with_shop(client)
    second = create_product(
        client,
        ctx["token"],
        ctx["shop_id"],
        _unique("SP2"),
        120_000,
        4,
        ctx["category_id"],
    )
    supplier_id = _entity_id(_create_supplier(client, ctx))
    items = [
        {"product_id": ctx["product"]["id"], "quantity": 2, "unit_cost": 40_000},
        {"product_id": second["id"], "quantity": 3, "unit_cost": 25_000},
    ]
    receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=items,
        # Client có gửi tổng giả thì server vẫn phải bỏ và tự tính lại.
        total_amount=1,
    )
    receipt_id = _entity_id(receipt)

    confirmed = _confirm(client, ctx, receipt_id)
    assert confirmed.status_code == 200, confirmed.text
    posted = _receipt(receipt_id)
    assert posted.status == "POSTED"
    assert float(posted.total_amount) == 155_000
    assert _product(ctx["product"]["id"]).stock == 12
    assert _product(second["id"]).stock == 7
    assert _debt(client, ctx, supplier_id) == 155_000

    session = SessionLocal()
    try:
        entries = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id,
            models.SupplierPayableEntry.entry_type == "PURCHASE",
        ).all()
        assert len(entries) == 1
        assert float(entries[0].amount) == 155_000
    finally:
        session.close()


def test_confirm_that_bai_phai_rollback_ca_hai_dong_kho_va_so_tien(client):
    """Tiền đầu ca không đủ là lỗi xảy ra ngay lúc confirm, sau khi DRAFT hợp lệ."""
    ctx = seller_with_shop(client)
    second = create_product(
        client, ctx["token"], ctx["shop_id"], _unique("SP2"), 1, 8, ctx["category_id"]
    )
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(
        _create_receipt(
            client,
            ctx,
            supplier_id,
            items=[
                {"product_id": ctx["product"]["id"], "quantity": 2, "unit_cost": 40_000},
                {"product_id": second["id"], "quantity": 2, "unit_cost": 30_000},
            ],
        )
    )
    shift = _open_shift(client, ctx, 50_000)

    failed = _confirm(
        client,
        ctx,
        receipt_id,
        paid_amount=140_000,
        method="CASH_SHIFT",
    )
    assert failed.status_code == 409, failed.text
    assert _receipt(receipt_id).status == "DRAFT"
    assert _product(ctx["product"]["id"]).stock == 10
    assert _product(second["id"]).stock == 8
    assert _debt(client, ctx, supplier_id) == 0

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id
        ).count() == 0
        assert session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).count() == 0
        assert session.query(models.CashMovement).filter(
            models.CashMovement.shift_id == shift["id"],
            models.CashMovement.movement_type == "PAY_OUT",
        ).count() == 0
    finally:
        session.close()


# ---------- Giá vốn và lô ----------


def test_nhap_dau_tien_khi_gia_von_null_lay_dung_don_gia(client):
    ctx = seller_with_shop(client)
    assert _product(ctx["product"]["id"]).cost_price is None
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(
        _create_receipt(client, ctx, supplier_id, items=[{
            "product_id": ctx["product"]["id"], "quantity": 5, "unit_cost": 20_000,
        }])
    )
    assert _confirm(client, ctx, receipt_id).status_code == 200
    assert _product(ctx["product"]["id"]).cost_price == 20_000


def test_gia_von_binh_quan_va_hang_tang_0_khac_null(client):
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]
    session = SessionLocal()
    try:
        product = session.query(models.Product).filter(models.Product.id == product_id).one()
        product.cost_price = 40_000
        session.commit()
    finally:
        session.close()

    supplier_id = _entity_id(_create_supplier(client, ctx))
    first_id = _entity_id(_create_receipt(client, ctx, supplier_id, items=[{
        "product_id": product_id, "quantity": 10, "unit_cost": 20_000,
    }]))
    assert _confirm(client, ctx, first_id).status_code == 200
    assert _product(product_id).cost_price == 30_000

    gift_id = _entity_id(_create_receipt(client, ctx, supplier_id, items=[{
        "product_id": product_id, "quantity": 20, "unit_cost": 0,
    }]))
    assert _confirm(client, ctx, gift_id).status_code == 200
    assert _product(product_id).cost_price == 15_000


def test_hang_theo_lo_bat_buoc_han_va_confirm_tao_dung_lo_gia(client):
    ctx = seller_with_shop(client)
    tracked = _tracked_product(client, ctx)
    supplier_id = _entity_id(_create_supplier(client, ctx))

    missing = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{"product_id": tracked["id"], "quantity": 5, "unit_cost": 31_000}],
        expected=400,
    )
    assert missing.status_code == 400

    expiry = _ngay(90)
    receipt_id = _entity_id(_create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": tracked["id"],
            "quantity": 5,
            "unit_cost": 31_000,
            "expiry_date": expiry,
        }],
    ))
    assert _confirm(client, ctx, receipt_id).status_code == 200

    session = SessionLocal()
    try:
        batches = session.query(models.ProductBatch).filter(
            models.ProductBatch.product_id == tracked["id"]
        ).all()
        assert len(batches) == 1
        assert batches[0].quantity == 5
        assert batches[0].expiry_date == expiry
        assert batches[0].cost_price == 31_000
        item = session.query(models.PurchaseReceiptItem).filter(
            models.PurchaseReceiptItem.receipt_id == receipt_id
        ).one()
        assert item.batch_id == batches[0].id
    finally:
        session.close()
    assert _product(tracked["id"]).stock == 5


def test_phieu_toan_hang_tang_tong_0_khong_tao_no_hay_thanh_toan_ao(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 4,
            "unit_cost": 0,
        }],
    ))
    confirmed = _confirm(client, ctx, receipt_id, paid_amount=0)
    assert confirmed.status_code == 200, confirmed.text
    assert _receipt(receipt_id).total_amount == 0
    assert _product(ctx["product"]["id"]).stock == 14
    assert _product(ctx["product"]["id"]).cost_price == 0
    assert _debt(client, ctx, supplier_id) == 0

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id
        ).count() == 0
        assert session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).count() == 0
    finally:
        session.close()


@pytest.mark.parametrize(
    "item",
    [
        {"quantity": 0, "unit_cost": 10_000},
        {"quantity": -1, "unit_cost": 10_000},
        {"quantity": 1.5, "unit_cost": 10_000},
        {"quantity": True, "unit_cost": 10_000},
        {"quantity": "1", "unit_cost": 10_000},
        {"quantity": 1, "unit_cost": -1},
        {"quantity": 1, "unit_cost": 1.5},
        {"quantity": 1, "unit_cost": False},
        {"quantity": 1, "unit_cost": "10000"},
        {"quantity": 1, "unit_cost": "NaN"},
        {"quantity": 1, "unit_cost": "Infinity"},
    ],
)
def test_dong_phieu_chi_nhan_so_nguyen_hop_le(client, item):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    item = {"product_id": ctx["product"]["id"], **item}
    response = _create_receipt(
        client, ctx, supplier_id, items=[item], expected=422
    )
    assert response.status_code == 422
    assert _product(ctx["product"]["id"]).stock == 10


@pytest.mark.parametrize("field", ["supplier_id", "product_id"])
@pytest.mark.parametrize("bad_id", [True, False, "1", 1.5])
def test_id_trong_phieu_nhap_phai_la_so_nguyen_that(client, field, bad_id):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    payload = _receipt_payload(ctx, supplier_id)
    if field == "supplier_id":
        payload["supplier_id"] = bad_id
    else:
        payload["items"][0]["product_id"] = bad_id

    response = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 422, response.text
    assert _product(ctx["product"]["id"]).stock == 10


@pytest.mark.parametrize("paid_amount", [True, False, "0", "10000", 1.5])
def test_tien_tra_khi_confirm_phai_la_so_nguyen_that(client, paid_amount):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt = _create_receipt(client, ctx, supplier_id)
    receipt_id = _entity_id(receipt)

    response = _confirm(
        client,
        ctx,
        receipt_id,
        paid_amount=paid_amount,
        draft_fingerprint=receipt["draft_fingerprint"],
    )
    assert response.status_code == 422, response.text
    assert _receipt(receipt_id).status == "DRAFT"
    assert _product(ctx["product"]["id"]).stock == 10
    assert _debt(client, ctx, supplier_id) == 0


@pytest.mark.parametrize("amount", [True, False, "1", "10000", 1.5])
def test_tien_tra_cong_no_phai_la_so_nguyen_that(client, amount):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(
        _create_supplier(client, ctx, opening_balance=100_000)
    )

    response = _payment(client, ctx, supplier_id, amount)
    assert response.status_code == 422, response.text
    assert _debt(client, ctx, supplier_id) == 100_000


def test_gioi_han_tien_nhan_dung_mep_va_chan_vuot_mot_dong(client):
    ctx = seller_with_shop(client)

    too_large_opening = _create_supplier(
        client,
        ctx,
        opening_balance=MAX_SAFE_VND + 1,
        expected=422,
    )
    assert too_large_opening.status_code == 422

    supplier_id = _entity_id(
        _create_supplier(
            client,
            ctx,
            opening_balance=MAX_SAFE_VND,
            opening_date=_ngay(),
        )
    )
    assert _debt(client, ctx, supplier_id) == MAX_SAFE_VND
    too_large_payment = _payment(
        client, ctx, supplier_id, MAX_SAFE_VND + 1
    )
    assert too_large_payment.status_code == 422, too_large_payment.text

    exact_receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 1,
            "unit_cost": MAX_SAFE_VND,
        }],
    )
    assert exact_receipt["total_amount"] == MAX_SAFE_VND
    exact_receipt_id = _entity_id(exact_receipt)

    too_large_confirm = _confirm(
        client,
        ctx,
        exact_receipt_id,
        paid_amount=MAX_SAFE_VND + 1,
        draft_fingerprint=exact_receipt["draft_fingerprint"],
    )
    assert too_large_confirm.status_code == 422, too_large_confirm.text

    exact_confirm = _confirm(
        client,
        ctx,
        exact_receipt_id,
        paid_amount=MAX_SAFE_VND,
        draft_fingerprint=exact_receipt["draft_fingerprint"],
    )
    assert exact_confirm.status_code == 200, exact_confirm.text
    assert _debt(client, ctx, supplier_id) == MAX_SAFE_VND

    exact_payment = _payment(client, ctx, supplier_id, MAX_SAFE_VND)
    assert exact_payment.status_code == 200, exact_payment.text
    assert _debt(client, ctx, supplier_id) == 0

    too_large_cost = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 1,
            "unit_cost": MAX_SAFE_VND + 1,
        }],
        expected=422,
    )
    assert too_large_cost.status_code == 422

    line_overflow = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 2,
            "unit_cost": MAX_SAFE_VND // 2 + 1,
        }],
        expected=400,
    )
    assert line_overflow.status_code == 400


def test_tong_phieu_chan_nhieu_dong_cong_lai_vuot_tran(client):
    ctx = seller_with_shop(client)
    second = create_product(
        client,
        ctx["token"],
        ctx["shop_id"],
        _unique("SP-tran-tien"),
        1,
        0,
        ctx["category_id"],
    )
    supplier_id = _entity_id(_create_supplier(client, ctx))
    response = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[
            {
                "product_id": ctx["product"]["id"],
                "quantity": 1,
                "unit_cost": MAX_SAFE_VND // 2 + 1,
            },
            {
                "product_id": second["id"],
                "quantity": 1,
                "unit_cost": MAX_SAFE_VND // 2 + 1,
            },
        ],
        expected=400,
    )
    assert response.status_code == 400


def test_gioi_han_so_luong_gop_cac_lo_va_ton_hien_tai(client):
    ctx = seller_with_shop(client)
    tracked = _tracked_product(client, ctx)
    supplier_id = _entity_id(_create_supplier(client, ctx))

    exact = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[
            {
                "product_id": tracked["id"],
                "quantity": 600_000_000,
                "unit_cost": 0,
                "expiry_date": _ngay(30),
            },
            {
                "product_id": tracked["id"],
                "quantity": 400_000_000,
                "unit_cost": 0,
                "expiry_date": _ngay(60),
            },
        ],
    )
    assert exact["total_amount"] == 0
    assert _product(tracked["id"]).stock == 0  # nháp chưa tăng kho

    too_many_batches = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[
            {
                "product_id": tracked["id"],
                "quantity": 600_000_000,
                "unit_cost": 0,
                "expiry_date": _ngay(30),
            },
            {
                "product_id": tracked["id"],
                "quantity": 400_000_001,
                "unit_cost": 0,
                "expiry_date": _ngay(60),
            },
        ],
        expected=400,
    )
    assert too_many_batches.status_code == 400

    too_large_item = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": tracked["id"],
            "quantity": MAX_SAFE_QUANTITY + 1,
            "unit_cost": 0,
            "expiry_date": _ngay(30),
        }],
        expected=422,
    )
    assert too_large_item.status_code == 422

    existing_stock_overflow = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": MAX_SAFE_QUANTITY,
            "unit_cost": 0,
        }],
        expected=400,
    )
    assert existing_stock_overflow.status_code == 400


def test_confirm_chan_cong_no_vuot_tran_va_rollback_kho(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(
        _create_supplier(
            client,
            ctx,
            opening_balance=MAX_SAFE_VND - 50,
            opening_date=_ngay(),
        )
    )
    receipt_id = _entity_id(
        _create_receipt(
            client,
            ctx,
            supplier_id,
            items=[{
                "product_id": ctx["product"]["id"],
                "quantity": 1,
                "unit_cost": 100,
            }],
        )
    )

    failed = _confirm(client, ctx, receipt_id, paid_amount=0)
    assert failed.status_code == 409, failed.text
    assert _receipt(receipt_id).status == "DRAFT"
    assert _product(ctx["product"]["id"]).stock == 10
    assert _debt(client, ctx, supplier_id) == MAX_SAFE_VND - 50


def test_confirm_cho_phep_cong_no_cham_dung_tran(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(
        _create_supplier(
            client,
            ctx,
            opening_balance=MAX_SAFE_VND - 100,
            opening_date=_ngay(),
        )
    )
    receipt_id = _entity_id(
        _create_receipt(
            client,
            ctx,
            supplier_id,
            items=[{
                "product_id": ctx["product"]["id"],
                "quantity": 1,
                "unit_cost": 100,
            }],
        )
    )

    confirmed = _confirm(client, ctx, receipt_id, paid_amount=0)
    assert confirmed.status_code == 200, confirmed.text
    assert _debt(client, ctx, supplier_id) == MAX_SAFE_VND
    assert _product(ctx["product"]["id"]).stock == 11


def test_ngay_va_han_su_dung_khong_hop_le_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    tracked = _tracked_product(client, ctx)
    supplier_id = _entity_id(_create_supplier(client, ctx))

    bad_received = _create_receipt(
        client, ctx, supplier_id, received_date="2026-02-30", expected=400
    )
    assert bad_received.status_code == 400
    bad_expiry = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": tracked["id"],
            "quantity": 1,
            "unit_cost": 10_000,
            "expiry_date": "2026-13-01",
        }],
        expected=422,
    )
    assert bad_expiry.status_code == 422


# ---------- Idempotency của phiếu ----------


def test_confirm_bat_buoc_gui_ban_nhap_da_xem_va_so_tien_da_chon(client):
    """Không được mặc định quyết định tiền, cũng không được chốt khi client
    không chứng minh được đang xác nhận đúng bản nháp vừa xem.
    """
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    detail = client.get(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    ).json()
    base = {
        "operation_id": _op("confirm-required"),
        "draft_fingerprint": detail["draft_fingerprint"],
        "paid_amount": 0,
    }

    for missing in ("draft_fingerprint", "paid_amount"):
        payload = dict(base)
        payload.pop(missing)
        response = client.post(
            f"/api/purchase-receipts/receipt/{receipt_id}/confirm",
            json=payload,
            headers=auth(ctx["token"]),
        )
        assert response.status_code == 422, response.text

    assert _receipt(receipt_id).status == "DRAFT"
    assert _product(ctx["product"]["id"]).stock == 10
    assert _debt(client, ctx, supplier_id) == 0


def test_fingerprint_on_dinh_khi_chi_doi_thu_tu_dong(client):
    """Thứ tự vật lý/id dòng không làm một nội dung nghiệp vụ thành bản khác."""
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    items = [
        {
            "product_id": ctx["product"]["id"],
            "quantity": 2,
            "unit_cost": 31_000,
        },
        {
            "product_id": ctx["product"]["id"],
            "quantity": 3,
            "unit_cost": 47_000,
        },
    ]
    receipt = _create_receipt(client, ctx, supplier_id, items=items)
    receipt_id = _entity_id(receipt)
    fingerprint_before = receipt["draft_fingerprint"]
    payload = {
        "supplier_id": supplier_id,
        "supplier_invoice_number": receipt["supplier_invoice_number"],
        "received_date": receipt["received_date"],
        "due_date": receipt["due_date"],
        "note": receipt["note"],
        "items": list(reversed(items)),
    }

    updated = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["draft_fingerprint"] == fingerprint_before


def test_ban_nhap_bi_admin_sua_sau_khi_mo_thi_owner_phai_xem_lai(client):
    """Race thật: owner giữ fingerprint A; ADMIN lưu nội dung B; request chốt
    A phải 409 và không được đổi tồn/công nợ. Chỉ fingerprint B mới được chốt.
    """
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt = _create_receipt(client, ctx, supplier_id)
    receipt_id = _entity_id(receipt)
    fingerprint_owner_saw = receipt["draft_fingerprint"]

    changed_items = [{
        "product_id": ctx["product"]["id"],
        "quantity": 5,
        "unit_cost": 42_000,
    }]
    changed_payload = {
        "supplier_id": supplier_id,
        "supplier_invoice_number": "HD-ADMIN-DA-SUA",
        "received_date": receipt["received_date"],
        "due_date": receipt["due_date"],
        "note": "Nội dung B do ADMIN vừa kiểm tra lại",
        "items": changed_items,
    }
    changed = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json=changed_payload,
        headers=auth(admin_token(client)),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["draft_fingerprint"] != fingerprint_owner_saw

    stale_confirm = _confirm(
        client,
        ctx,
        receipt_id,
        draft_fingerprint=fingerprint_owner_saw,
    )
    assert stale_confirm.status_code == 409, stale_confirm.text
    assert _receipt(receipt_id).status == "DRAFT"
    assert _product(ctx["product"]["id"]).stock == 10
    assert _debt(client, ctx, supplier_id) == 0

    fresh = client.get(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    )
    assert fresh.status_code == 200, fresh.text
    fresh_fingerprint = fresh.json()["draft_fingerprint"]
    assert fresh_fingerprint == changed.json()["draft_fingerprint"]
    confirmed = _confirm(
        client,
        ctx,
        receipt_id,
        draft_fingerprint=fresh_fingerprint,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert _product(ctx["product"]["id"]).stock == 15
    assert _debt(client, ctx, supplier_id) == 210_000


def test_retry_tao_draft_cung_payload_tra_cung_phieu_khac_payload_409(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    payload = _receipt_payload(ctx, supplier_id, operation_id=_op("receipt"))

    first = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    retry = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == retry.status_code == 200
    assert _entity_id(first.json(), "receipt") == _entity_id(retry.json(), "receipt")

    payload["items"][0]["quantity"] = 3
    conflict = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert conflict.status_code == 409


def test_retry_tao_draft_bo_trong_ngay_qua_nua_dem_van_cung_phieu(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    payload = _receipt_payload(ctx, supplier_id)
    payload.pop("received_date")
    monkeypatch.setattr(supplier_service, "_today_vn", lambda: "2026-08-07")
    first = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    monkeypatch.setattr(supplier_service, "_today_vn", lambda: "2026-08-08")
    retry = client.post(
        f"/api/purchase-receipts/{ctx['shop_id']}",
        json=payload,
        headers=auth(ctx["token"]),
    )
    assert first.status_code == retry.status_code == 200
    assert _entity_id(first.json(), "receipt") == _entity_id(retry.json(), "receipt")
    assert first.json()["received_date"] == "2026-08-07"
    assert retry.json()["received_date"] == "2026-08-07"


def test_tao_phieu_dong_thoi_xoa_ncc_khong_de_chung_tu_mo_coi(
    client, monkeypatch
):
    """SQLite không bật FK nên lock ứng dụng phải tự giữ bất biến tham chiếu."""
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    payload = _receipt_payload(ctx, supplier_id)
    prepare_ready = threading.Event()
    release_prepare = threading.Event()
    delete_started = threading.Event()
    delete_done = threading.Event()
    original_prepare = supplier_service._prepare_items

    def gated_prepare(*args, **kwargs):
        prepared = original_prepare(*args, **kwargs)
        prepare_ready.set()
        assert release_prepare.wait(5), "Không nhận được tín hiệu tiếp tục tạo phiếu"
        return prepared

    monkeypatch.setattr(supplier_service, "_prepare_items", gated_prepare)

    def create_once():
        return client.post(
            f"/api/purchase-receipts/{ctx['shop_id']}",
            json=payload,
            headers=auth(ctx["token"]),
        )

    def delete_once():
        delete_started.set()
        try:
            return client.delete(
                f"/api/suppliers/member/{supplier_id}",
                headers=auth(ctx["token"]),
            )
        finally:
            delete_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        create_future = pool.submit(create_once)
        assert prepare_ready.wait(5), "Request tạo phiếu chưa tới điểm đồng bộ"
        delete_future = pool.submit(delete_once)
        assert delete_started.wait(5)
        # Bản lỗi xóa xong ngay tại đây rồi request tạo INSERT phiếu mồ côi.
        # Bản đúng đang giữ write lock shop, nên xóa phải chờ tạo phiếu commit.
        delete_done.wait(0.4)
        release_prepare.set()
        created = create_future.result(timeout=10)
        deleted = delete_future.result(timeout=10)

    assert created.status_code == 200, created.text
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["msg"] == "Deactivated"

    session = SessionLocal()
    try:
        orphan_count = (
            session.query(models.PurchaseReceipt)
            .outerjoin(
                models.Supplier,
                models.Supplier.id == models.PurchaseReceipt.supplier_id,
            )
            .filter(
                models.PurchaseReceipt.supplier_id == supplier_id,
                models.Supplier.id.is_(None),
            )
            .count()
        )
        supplier = session.query(models.Supplier).filter(
            models.Supplier.id == supplier_id
        ).one()
        assert orphan_count == 0
        assert supplier.is_active is False
    finally:
        session.close()


def test_retry_confirm_khong_tang_kho_hay_ghi_cong_no_hai_lan(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    operation_id = _op("confirm")

    first = _confirm(client, ctx, receipt_id, operation_id=operation_id)
    retry = _confirm(client, ctx, receipt_id, operation_id=operation_id)
    assert first.status_code == retry.status_code == 200
    assert _product(ctx["product"]["id"]).stock == 12
    assert _debt(client, ctx, supplier_id) == 80_000

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id,
            models.SupplierPayableEntry.entry_type == "PURCHASE",
        ).count() == 1
    finally:
        session.close()

    conflict = _confirm(
        client,
        ctx,
        receipt_id,
        paid_amount=1,
        method="OUTSIDE",
        operation_id=operation_id,
    )
    assert conflict.status_code == 409


def test_hai_confirm_dong_thoi_khac_ma_chi_post_mot_lan(client):
    """Khóa trạng thái phải bảo vệ cả khi hai nút dùng hai operation_id khác."""
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    barrier = threading.Barrier(2)

    def confirm_once():
        barrier.wait()
        return _confirm(
            client,
            ctx,
            receipt_id,
            operation_id=_op("parallel-confirm"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result() for future in [
            pool.submit(confirm_once), pool.submit(confirm_once)
        ]]

    assert any(row.status_code == 200 for row in responses)
    assert all(row.status_code in (200, 409, 503) for row in responses)
    assert _receipt(receipt_id).status == "POSTED"
    assert _product(ctx["product"]["id"]).stock == 12
    assert _debt(client, ctx, supplier_id) == 80_000
    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id
        ).count() == 1
    finally:
        session.close()


def test_confirm_cho_dieu_chinh_lo_de_khong_lech_tong_lo_va_ton(
    client, monkeypatch
):
    """Điều chỉnh lô đang giữ khóa thì phiếu nhập phải xếp hàng phía sau."""
    ctx = seller_with_shop(client)
    tracked = _tracked_product(client, ctx)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": tracked["id"],
            "quantity": 5,
            "unit_cost": 31_000,
            "expiry_date": _ngay(90),
        }],
    )
    receipt_id = _entity_id(receipt)
    lock_ready, release_lock = _hold_inventory_lock(monkeypatch)
    confirm_started = threading.Event()
    confirm_done = threading.Event()

    def adjust_once():
        return client.post(
            f"/api/products/{tracked['id']}/stock",
            json={
                "delta": 7,
                "unit_cost": 29_000,
                "expiry_date": _ngay(120),
                "reason": "Kiểm thử hai thao tác kho đồng thời",
            },
            headers=auth(ctx["token"]),
        )

    def confirm_once():
        confirm_started.set()
        try:
            return _confirm(
                client,
                ctx,
                receipt_id,
                draft_fingerprint=receipt["draft_fingerprint"],
            )
        finally:
            confirm_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        adjust_future = pool.submit(adjust_once)
        confirm_future = None
        try:
            assert lock_ready.wait(5), "Điều chỉnh lô chưa lấy khóa kho chung"
            confirm_future = pool.submit(confirm_once)
            assert confirm_started.wait(5)
            assert not confirm_done.wait(0.4), "Confirm đã chen qua khóa kho"
        finally:
            release_lock.set()
        adjusted = adjust_future.result(timeout=10)
        confirmed = confirm_future.result(timeout=10)

    assert adjusted.status_code == 200, adjusted.text
    assert confirmed.status_code == 200, confirmed.text
    session = SessionLocal()
    try:
        product = session.query(models.Product).filter(
            models.Product.id == tracked["id"]
        ).one()
        batches = session.query(models.ProductBatch).filter(
            models.ProductBatch.product_id == tracked["id"]
        ).all()
        assert product.stock == 12
        assert sum(batch.quantity for batch in batches) == 12
        assert sorted(batch.quantity for batch in batches) == [5, 7]
    finally:
        session.close()


def test_confirm_cho_kiem_ke_de_khong_nuot_ton_vua_nhap(client, monkeypatch):
    """Kiểm kê gán tồn tuyệt đối trước; confirm sau đó phải cộng trên số mới."""
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{"product_id": product_id, "quantity": 5, "unit_cost": 40_000}],
    )
    receipt_id = _entity_id(receipt)
    lock_ready, release_lock = _hold_inventory_lock(monkeypatch)
    confirm_started = threading.Event()
    confirm_done = threading.Event()

    def stocktake_once():
        return client.post(
            f"/api/products/{ctx['shop_id']}/stocktake",
            json={"items": [{
                "product_id": product_id,
                "counted": 8,
                "stock_snapshot": 10,
            }]},
            headers=auth(ctx["token"]),
        )

    def confirm_once():
        confirm_started.set()
        try:
            return _confirm(
                client,
                ctx,
                receipt_id,
                draft_fingerprint=receipt["draft_fingerprint"],
            )
        finally:
            confirm_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        stocktake_future = pool.submit(stocktake_once)
        confirm_future = None
        try:
            assert lock_ready.wait(5), "Kiểm kê chưa lấy khóa kho chung"
            confirm_future = pool.submit(confirm_once)
            assert confirm_started.wait(5)
            assert not confirm_done.wait(0.4), "Confirm đã chen qua khóa kiểm kê"
        finally:
            release_lock.set()
        stocktake = stocktake_future.result(timeout=10)
        confirmed = confirm_future.result(timeout=10)

    assert stocktake.status_code == 200, stocktake.text
    assert stocktake.json()["bo_qua"] == []
    assert confirmed.status_code == 200, confirmed.text
    # Kiểm kê 10 -> 8 chạy trước, nhập thêm 5 chạy sau: tồn cuối phải là 13.
    assert _product(product_id).stock == 13


def test_confirm_cho_huy_hang_de_khong_nuot_ton_va_chot_sai_gia_von(
    client, monkeypatch
):
    """Hủy hàng phải chốt tồn/giá trước; confirm không được chen vào giữa."""
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]
    assert _product(product_id).cost_price is None
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{"product_id": product_id, "quantity": 5, "unit_cost": 40_000}],
    )
    receipt_id = _entity_id(receipt)
    lock_ready, release_lock = _hold_inventory_lock(monkeypatch)
    confirm_started = threading.Event()
    confirm_done = threading.Event()

    def write_off_once():
        return client.post(
            f"/api/products/{ctx['shop_id']}/write-off",
            json={
                "reason": "LOST",
                "note": "Kiểm thử hai thao tác kho đồng thời",
                "operation_id": _op("parallel-write-off"),
                "items": [{"product_id": product_id, "quantity": 3}],
            },
            headers=auth(ctx["token"]),
        )

    def confirm_once():
        confirm_started.set()
        try:
            return _confirm(
                client,
                ctx,
                receipt_id,
                draft_fingerprint=receipt["draft_fingerprint"],
            )
        finally:
            confirm_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_off_future = pool.submit(write_off_once)
        confirm_future = None
        try:
            assert lock_ready.wait(5), "Hủy hàng chưa lấy khóa kho chung"
            confirm_future = pool.submit(confirm_once)
            assert confirm_started.wait(5)
            assert not confirm_done.wait(0.4), "Confirm đã chen qua khóa hủy hàng"
        finally:
            release_lock.set()
        write_off = write_off_future.result(timeout=10)
        confirmed = confirm_future.result(timeout=10)

    assert write_off.status_code == 200, write_off.text
    assert confirmed.status_code == 200, confirmed.text
    assert _product(product_id).stock == 12
    session = SessionLocal()
    try:
        item = session.query(models.StockWriteOffItem).filter(
            models.StockWriteOffItem.write_off_id
            == write_off.json()["write_off_id"]
        ).one()
        # Hủy chạy trước lúc lô 40.000đ được nhập, nên giá vốn chốt đúng là
        # chưa khai (NULL), không được nhìn xuyên sang giao dịch chạy sau.
        assert item.cost_price is None
    finally:
        session.close()


# ---------- Thanh toán, FIFO và két ca ----------


def test_xac_nhan_tra_mot_phan_va_tra_no_tiep_den_het(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))  # 80k

    confirmed = _confirm(
        client, ctx, receipt_id, paid_amount=30_000, method="OUTSIDE"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert _debt(client, ctx, supplier_id) == 50_000

    paid = _payment(client, ctx, supplier_id, 50_000, method="TRANSFER")
    assert paid.status_code == 200, paid.text
    assert _debt(client, ctx, supplier_id) == 0


def test_tien_tra_ngay_khi_confirm_chi_phan_bo_vao_phieu_moi(client):
    """Không dùng FIFO cho tiền trao đúng lúc nhận phiếu: nợ đầu kỳ vẫn nguyên."""
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(
        client,
        ctx,
        opening_balance=100_000,
        opening_date=_ngay(-30),
        opening_due_date=_ngay(-1),
        opening_note="Nợ đầu kỳ",
    ))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))  # 80k
    confirmed = _confirm(
        client, ctx, receipt_id, paid_amount=30_000, method="OUTSIDE"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert _debt(client, ctx, supplier_id) == 150_000

    session = SessionLocal()
    try:
        opening = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.supplier_id == supplier_id,
            models.SupplierPayableEntry.entry_type == "OPENING",
        ).one()
        purchase = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.receipt_id == receipt_id,
            models.SupplierPayableEntry.entry_type == "PURCHASE",
        ).one()
        payment = session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).one()
        allocations = session.query(models.SupplierPaymentAllocation).filter(
            models.SupplierPaymentAllocation.payment_id == payment.id
        ).all()
        assert [(row.payable_entry_id, row.amount) for row in allocations] == [
            (purchase.id, 30_000)
        ]
        assert all(row.payable_entry_id != opening.id for row in allocations)
    finally:
        session.close()


def test_tra_no_tu_dong_can_fifo_va_khong_lan_ncc_khac(client):
    ctx = seller_with_shop(client)
    supplier_a = _create_supplier(
        client,
        ctx,
        opening_balance=100_000,
        opening_date=_ngay(-30),
        opening_due_date=_ngay(-1),
        opening_note="Nợ đầu kỳ",
    )
    supplier_a_id = _entity_id(supplier_a)
    supplier_b_id = _entity_id(_create_supplier(client, ctx, opening_balance=70_000))

    first_receipt = _create_receipt(
        client,
        ctx,
        supplier_a_id,
        received_date=_ngay(-10),
        due_date=_ngay(5),
        items=[{
            "product_id": ctx["product"]["id"], "quantity": 2, "unit_cost": 100_000,
        }],
    )
    second_receipt = _create_receipt(
        client,
        ctx,
        supplier_a_id,
        received_date=_ngay(-5),
        due_date=_ngay(10),
        items=[{
            "product_id": ctx["product"]["id"], "quantity": 3, "unit_cost": 100_000,
        }],
    )
    assert _confirm(client, ctx, _entity_id(first_receipt)).status_code == 200
    assert _confirm(client, ctx, _entity_id(second_receipt)).status_code == 200

    payment = _payment(client, ctx, supplier_a_id, 250_000)
    assert payment.status_code == 200, payment.text
    payment_id = _entity_id(payment.json(), "payment")

    session = SessionLocal()
    try:
        entries = session.query(models.SupplierPayableEntry).filter(
            models.SupplierPayableEntry.supplier_id == supplier_a_id
        ).order_by(
            models.SupplierPayableEntry.entry_date,
            models.SupplierPayableEntry.id,
        ).all()
        allocations = session.query(models.SupplierPaymentAllocation).filter(
            models.SupplierPaymentAllocation.payment_id == payment_id
        ).order_by(models.SupplierPaymentAllocation.id).all()
        by_entry = {row.payable_entry_id: float(row.amount) for row in allocations}
        assert by_entry[entries[0].id] == 100_000
        assert by_entry[entries[1].id] == 150_000
        assert entries[2].id not in by_entry
    finally:
        session.close()

    assert _debt(client, ctx, supplier_a_id) == 350_000
    assert _debt(client, ctx, supplier_b_id) == 70_000


def test_khong_tra_qua_tong_no_va_loi_khong_ghi_giao_dich(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))
    response = _payment(client, ctx, supplier_id, 100_001)
    assert response.status_code == 409
    assert _debt(client, ctx, supplier_id) == 100_000

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).count() == 0
    finally:
        session.close()


def test_outside_bat_buoc_ghi_chu_va_method_reference_duoc_validate(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))

    missing_note = client.post(
        f"/api/suppliers/member/{supplier_id}/payments",
        json={
            "amount": 10_000,
            "method": "OUTSIDE",
            "note": "   ",
            "reference": "REF",
            "operation_id": _op("outside"),
        },
        headers=auth(ctx["token"]),
    )
    invalid_method = client.post(
        f"/api/suppliers/member/{supplier_id}/payments",
        json={
            "amount": 10_000,
            "method": "VI_DIEN_TU",
            "note": "Có ghi chú",
            "operation_id": _op("method"),
        },
        headers=auth(ctx["token"]),
    )
    long_reference = client.post(
        f"/api/suppliers/member/{supplier_id}/payments",
        json={
            "amount": 10_000,
            "method": "TRANSFER",
            "reference": "x" * 129,
            "operation_id": _op("reference"),
        },
        headers=auth(ctx["token"]),
    )
    assert missing_note.status_code == 400
    assert invalid_method.status_code == 422
    assert long_reference.status_code == 422
    assert _debt(client, ctx, supplier_id) == 100_000

    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    receipt_detail = client.get(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        headers=auth(ctx["token"]),
    ).json()
    bad_confirm = client.post(
        f"/api/purchase-receipts/receipt/{receipt_id}/confirm",
        json={
            "operation_id": _op("confirm-outside"),
            "draft_fingerprint": receipt_detail["draft_fingerprint"],
            "paid_amount": 10_000,
            "method": "OUTSIDE",
            "note": "  ",
            "reference": "REF",
        },
        headers=auth(ctx["token"]),
    )
    assert bad_confirm.status_code == 400
    assert _receipt(receipt_id).status == "DRAFT"


def test_retry_tra_no_cung_payload_khong_tru_hai_lan_khac_payload_409(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=200_000))
    operation_id = _op("payment")

    first = _payment(
        client, ctx, supplier_id, 50_000, operation_id=operation_id
    )
    retry = _payment(
        client, ctx, supplier_id, 50_000, operation_id=operation_id
    )
    assert first.status_code == retry.status_code == 200
    assert _debt(client, ctx, supplier_id) == 150_000

    conflict = _payment(
        client, ctx, supplier_id, 60_000, operation_id=operation_id
    )
    assert conflict.status_code == 409

    session = SessionLocal()
    try:
        assert session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).count() == 1
    finally:
        session.close()


def test_hai_payment_dong_thoi_khong_duoc_tra_qua_du_no(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))
    barrier = threading.Barrier(2)

    def pay_once():
        barrier.wait()
        return _payment(
            client,
            ctx,
            supplier_id,
            70_000,
            method="TRANSFER",
            operation_id=_op("parallel-payment"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result() for future in [
            pool.submit(pay_once), pool.submit(pay_once)
        ]]

    assert any(row.status_code == 200 for row in responses)
    assert all(row.status_code in (200, 409, 503) for row in responses)
    assert _debt(client, ctx, supplier_id) == 30_000
    session = SessionLocal()
    try:
        payments = session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).all()
        allocations = (
            session.query(models.SupplierPaymentAllocation)
            .join(
                models.SupplierPayment,
                models.SupplierPayment.id
                == models.SupplierPaymentAllocation.payment_id,
            )
            .filter(models.SupplierPayment.supplier_id == supplier_id)
            .all()
        )
        assert sum(row.amount for row in payments) == 70_000
        assert sum(row.amount for row in allocations) == 70_000
    finally:
        session.close()


def test_tien_mat_bat_buoc_ca_cua_chinh_nguoi_tra_va_du_tien(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))
    _, cashier = new_staff(client, ctx, "CASHIER")
    _open_shift(client, ctx, 500_000, token=cashier)

    # Shop có ca của người khác vẫn chưa đủ; tiền phải ra đúng két của người bấm.
    no_shift = _payment(client, ctx, supplier_id, 10_000, method="CASH_SHIFT")
    assert no_shift.status_code == 409
    assert _debt(client, ctx, supplier_id) == 100_000

    shift = _open_shift(client, ctx, 50_000)
    too_much = _payment(client, ctx, supplier_id, 60_000, method="CASH_SHIFT")
    assert too_much.status_code == 409
    assert _debt(client, ctx, supplier_id) == 100_000
    detail = client.get(
        f"/api/shifts/{shift['id']}", headers=auth(ctx["token"])
    ).json()
    assert detail["expected_cash_amount"] == 50_000


def test_tien_mat_tru_ket_dung_mot_lan_ke_ca_khi_retry(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=200_000))
    shift = _open_shift(client, ctx, 500_000)
    operation_id = _op("cash-payment")

    first = _payment(
        client,
        ctx,
        supplier_id,
        80_000,
        method="CASH_SHIFT",
        operation_id=operation_id,
    )
    retry = _payment(
        client,
        ctx,
        supplier_id,
        80_000,
        method="CASH_SHIFT",
        operation_id=operation_id,
    )
    assert first.status_code == retry.status_code == 200
    detail = client.get(
        f"/api/shifts/{shift['id']}", headers=auth(ctx["token"])
    ).json()
    assert detail["expected_cash_amount"] == 420_000
    assert _debt(client, ctx, supplier_id) == 120_000

    session = SessionLocal()
    try:
        movements = session.query(models.CashMovement).filter(
            models.CashMovement.shift_id == shift["id"],
            models.CashMovement.movement_type == "PAY_OUT",
        ).all()
        assert len(movements) == 1
        assert movements[0].amount == 80_000
        payments = session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).all()
        assert len(payments) == 1
        assert payments[0].shift_id == shift["id"]
    finally:
        session.close()


def test_staff_xem_chi_tiet_ca_chi_thay_so_ket_khong_thay_chi_tiet_ncc(client):
    """MANAGER cần thấy khoản PAY_OUT để đối chiếu két, nhưng ghi chú của
    CashMovement không được trở thành đường vòng đọc NCC/phiếu/công nợ.
    """
    ctx = seller_with_shop(client)
    supplier_name = _unique("NCC_BI_MAT")
    supplier_id = _entity_id(
        _create_supplier(client, ctx, name=supplier_name)
    )
    receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 3,
            "unit_cost": 82_271,
        }],
    )
    receipt_id = _entity_id(receipt)
    shift = _open_shift(client, ctx, 500_000)
    paid_amount = 74_293
    private_note = (
        f"PHIEU_NHAP_BI_MAT_{receipt_id}; {supplier_name}; "
        f"CASH_SHIFT; {paid_amount:,}đ"
    )
    confirmed = client.post(
        f"/api/purchase-receipts/receipt/{receipt_id}/confirm",
        json={
            "operation_id": _op("confirm-private-cash"),
            "draft_fingerprint": receipt["draft_fingerprint"],
            "paid_amount": paid_amount,
            "method": "CASH_SHIFT",
            "reference": "THAM_CHIEU_CONG_NO_BI_MAT",
            "note": private_note,
        },
        headers=auth(ctx["token"]),
    )
    assert confirmed.status_code == 200, confirmed.text

    _, manager_token = new_staff(client, ctx, "MANAGER")
    response = client.get(
        f"/api/shifts/{shift['id']}", headers=auth(manager_token)
    )
    assert response.status_code == 200, response.text
    pay_outs = [
        movement for movement in response.json()["movements"]
        if movement["movement_type"] == "PAY_OUT"
    ]
    assert len(pay_outs) == 1
    movement = pay_outs[0]
    assert movement["direction"] == "OUT"
    assert movement["amount"] == paid_amount
    assert "supplier" not in movement["operation_id"].lower()
    assert "ncc" not in movement["operation_id"].lower()

    note = movement["note"] or ""
    assert note == "Khoản chi"
    for private_detail in (
        supplier_name,
        private_note,
        f"PHIEU_NHAP_BI_MAT_{receipt_id}",
        "CASH_SHIFT",
        f"{paid_amount:,}",
        str(paid_amount),
        "THAM_CHIEU_CONG_NO_BI_MAT",
    ):
        assert private_detail not in note


@pytest.mark.parametrize("method", ["TRANSFER", "OUTSIDE"])
def test_chuyen_khoan_va_tien_ngoai_ket_khong_can_ca_khong_dung_ket(client, method):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))
    response = _payment(client, ctx, supplier_id, 40_000, method=method)
    assert response.status_code == 200, response.text
    assert _debt(client, ctx, supplier_id) == 60_000

    session = SessionLocal()
    try:
        payment = session.query(models.SupplierPayment).filter(
            models.SupplierPayment.supplier_id == supplier_id
        ).one()
        assert payment.shift_id is None
        assert payment.cash_movement_id is None
        assert session.query(models.CashMovement).filter(
            models.CashMovement.created_by_user_id == payment.created_by_user_id
        ).count() == 0
    finally:
        session.close()


# ---------- Cách ly shop, phân quyền và vòng đời ----------


def test_san_pham_trong_phieu_nhap_khong_duoc_xoa_cung_de_tranh_tai_dung_id(client):
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))

    deleted = client.delete(
        f"/api/products/{product_id}", headers=auth(ctx["token"])
    )
    assert deleted.status_code == 409, deleted.text
    assert "bấm Ẩn" in deleted.json()["detail"]

    confirmed = _confirm(client, ctx, receipt_id)
    assert confirmed.status_code == 200, confirmed.text
    assert _product(product_id).stock == 12


def test_khong_duoc_dung_ncc_hoac_san_pham_cua_shop_khac(client):
    a = seller_with_shop(client)
    b = seller_with_shop(client)
    supplier_a_id = _entity_id(_create_supplier(client, a))
    supplier_b_id = _entity_id(_create_supplier(client, b))

    wrong_supplier = _create_receipt(
        client, a, supplier_b_id, expected=404
    )
    assert wrong_supplier.status_code in (403, 404)
    wrong_product = _create_receipt(
        client,
        a,
        supplier_a_id,
        items=[{
            "product_id": b["product"]["id"], "quantity": 1, "unit_cost": 10_000,
        }],
        expected=404,
    )
    assert wrong_product.status_code in (403, 404)
    assert _product(b["product"]["id"]).stock == 10


def test_chu_shop_va_admin_duoc_dung_nhung_moi_staff_deu_bi_chan(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    admin = admin_token(client)

    assert client.get(
        f"/api/suppliers/{ctx['shop_id']}", headers=auth(ctx["token"])
    ).status_code == 200
    assert client.get(
        f"/api/suppliers/{ctx['shop_id']}", headers=auth(admin)
    ).status_code == 200
    admin_receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    assert _confirm(
        client, ctx, admin_receipt_id, token=admin
    ).status_code == 200
    assert _payment(
        client, ctx, supplier_id, 10_000, token=admin
    ).status_code == 200

    for role in ("CASHIER", "WAREHOUSE", "MANAGER"):
        _, staff_token = new_staff(client, ctx, role)
        assert client.get(
            f"/api/suppliers/{ctx['shop_id']}", headers=auth(staff_token)
        ).status_code == 403
        denied = _create_receipt(
            client, ctx, supplier_id, token=staff_token, expected=403
        )
        assert denied.status_code == 403
        assert _payment(
            client, ctx, supplier_id, 1, token=staff_token
        ).status_code == 403


def test_chua_dang_nhap_bi_chan(client):
    ctx = seller_with_shop(client)
    assert client.get(f"/api/suppliers/{ctx['shop_id']}").status_code == 401


def test_ncc_co_lich_su_chi_ngung_su_dung_van_tra_duoc_no_cu(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx, opening_balance=100_000))

    deleted = client.delete(
        f"/api/suppliers/member/{supplier_id}", headers=auth(ctx["token"])
    )
    assert deleted.status_code == 200, deleted.text
    assert _supplier(supplier_id).is_active is False

    # Ngừng sử dụng chặn chứng từ mới nhưng không được chặn việc trả nợ cũ.
    rejected = _create_receipt(
        client, ctx, supplier_id, expected=404
    )
    assert rejected.status_code == 404
    paid = _payment(client, ctx, supplier_id, 100_000)
    assert paid.status_code == 200, paid.text
    assert _debt(client, ctx, supplier_id) == 0

    enabled = client.put(
        f"/api/suppliers/member/{supplier_id}/status",
        json={"is_active": True},
        headers=auth(ctx["token"]),
    )
    assert enabled.status_code == 200, enabled.text
    assert _supplier(supplier_id).is_active is True


def test_ncc_chua_co_lich_su_duoc_xoa_that(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    deleted = client.delete(
        f"/api/suppliers/member/{supplier_id}", headers=auth(ctx["token"])
    )
    assert deleted.status_code == 200, deleted.text
    session = SessionLocal()
    try:
        assert session.query(models.Supplier).filter(
            models.Supplier.id == supplier_id
        ).count() == 0
    finally:
        session.close()


def test_qua_han_tinh_tu_han_no_dau_ky_va_han_phieu(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(
        client,
        ctx,
        opening_balance=100_000,
        opening_date=_ngay(-30),
        opening_due_date=_ngay(-1),
        opening_note="Nợ đầu kỳ quá hạn",
    ))
    overdue_receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        due_date=_ngay(-1),
        items=[{
            "product_id": ctx["product"]["id"], "quantity": 2, "unit_cost": 40_000,
        }],
    )
    future_receipt = _create_receipt(
        client,
        ctx,
        supplier_id,
        due_date=_ngay(10),
        items=[{
            "product_id": ctx["product"]["id"], "quantity": 1, "unit_cost": 40_000,
        }],
    )
    assert _confirm(client, ctx, _entity_id(overdue_receipt)).status_code == 200
    assert _confirm(client, ctx, _entity_id(future_receipt)).status_code == 200
    assert _debt(client, ctx, supplier_id) == 220_000
    assert _overdue(client, ctx, supplier_id) == 180_000
    listed = client.get(
        f"/api/suppliers/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert listed.status_code == 200, listed.text
    row = next(
        item for item in listed.json()["suppliers"] if item["id"] == supplier_id
    )
    assert row["payable_balance"] == 220_000
    assert row["overdue_amount"] == 180_000

    # Trả theo FIFO: hết 100k đầu kỳ rồi 20k của phiếu quá hạn.
    assert _payment(client, ctx, supplier_id, 120_000).status_code == 200
    assert _debt(client, ctx, supplier_id) == 100_000
    assert _overdue(client, ctx, supplier_id) == 60_000


def test_shop_co_so_ncc_khong_duoc_xoa_cung(client):
    ctx = seller_with_shop(client)
    _create_supplier(client, ctx, opening_balance=10_000)
    response = client.delete(
        f"/api/shops/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert response.status_code == 409


# ---------- Audit, schema và index fail-closed ----------


def test_confirm_va_tra_no_hien_o_nhat_ky_cung_dung_nguoi(client):
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(_create_supplier(client, ctx))
    receipt_id = _entity_id(_create_receipt(client, ctx, supplier_id))
    assert _confirm(client, ctx, receipt_id).status_code == 200
    assert _payment(client, ctx, supplier_id, 10_000).status_code == 200

    response = client.get(
        f"/api/logs/shop/{ctx['shop_id']}", headers=auth(ctx["token"])
    )
    assert response.status_code == 200
    logs = response.json()["logs"]
    actions = {row["action"] for row in logs}
    assert "CONFIRM_PURCHASE_RECEIPT" in actions
    assert "SUPPLIER_PAYMENT" in actions
    assert all(
        row["username"] == ctx["username"]
        for row in logs
        if row["action"] in {"CONFIRM_PURCHASE_RECEIPT", "SUPPLIER_PAYMENT"}
    )


def test_staff_xem_nhat_ky_nhung_khong_thay_so_tien_ncc(client):
    """Màn Ai Làm Gì vẫn mở cho STAFF, nhưng không được thành đường vòng đọc
    nợ đầu kỳ, giá nhập, tổng phiếu hay số tiền chủ shop đã trả nhà cung cấp.
    """
    ctx = seller_with_shop(client)
    supplier_id = _entity_id(
        _create_supplier(client, ctx, opening_balance=731_947)
    )
    receipt_id = _entity_id(
        _create_receipt(
            client,
            ctx,
            supplier_id,
            items=[{
                "product_id": ctx["product"]["id"],
                "quantity": 3,
                "unit_cost": 83_429,
            }],
        )
    )
    updated = _receipt_payload(
        ctx,
        supplier_id,
        items=[{
            "product_id": ctx["product"]["id"],
            "quantity": 4,
            "unit_cost": 83_429,
        }],
    )
    updated.pop("operation_id")
    response = client.put(
        f"/api/purchase-receipts/receipt/{receipt_id}",
        json=updated,
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert _confirm(
        client, ctx, receipt_id, paid_amount=47_381
    ).status_code == 200
    assert _payment(client, ctx, supplier_id, 51_719).status_code == 200

    _, staff_token = new_staff(client, ctx, "MANAGER")
    response = client.get(
        f"/api/logs/shop/{ctx['shop_id']}", headers=auth(staff_token)
    )
    assert response.status_code == 200, response.text
    supplier_logs = [
        row for row in response.json()["logs"]
        if row["action"] in {
            "CREATE_SUPPLIER",
            "CREATE_PURCHASE_RECEIPT_DRAFT",
            "UPDATE_PURCHASE_RECEIPT_DRAFT",
            "CONFIRM_PURCHASE_RECEIPT",
            "SUPPLIER_PAYMENT",
        }
    ]
    assert {row["action"] for row in supplier_logs} == {
        "CREATE_SUPPLIER",
        "CREATE_PURCHASE_RECEIPT_DRAFT",
        "UPDATE_PURCHASE_RECEIPT_DRAFT",
        "CONFIRM_PURCHASE_RECEIPT",
        "SUPPLIER_PAYMENT",
    }
    details = "\n".join(row["details"] or "" for row in supplier_logs)
    for sensitive_amount in (
        731_947,  # nợ đầu kỳ
        83_429,   # đơn giá nhập
        250_287,  # tổng nháp lúc tạo
        333_716,  # tổng sau sửa và lúc xác nhận
        47_381,   # trả ngay khi xác nhận
        51_719,   # lần trả công nợ sau đó
    ):
        assert f"{sensitive_amount:,}" not in details
        assert str(sensitive_amount) not in details


def test_nang_db_legacy_tao_bang_moi_nhung_khong_bia_phieu_tu_ton_cu(client, db):
    """ADJUST_STOCK cũ không đủ thông tin để đoán NCC, hóa đơn hay đã trả tiền."""
    ctx = seller_with_shop(client)
    product_id = ctx["product"]["id"]
    before = db.query(models.Product).filter(models.Product.id == product_id).one()
    stock_before = before.stock
    cost_before = before.cost_price

    for table in (
        "supplier_payment_allocations",
        "supplier_payments",
        "supplier_payable_entries",
        "purchase_receipt_items",
        "purchase_receipts",
        "suppliers",
    ):
        db.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
    db.commit()

    bootstrap.initialize()
    db.expire_all()
    after = db.query(models.Product).filter(models.Product.id == product_id).one()
    assert after.stock == stock_before
    assert after.cost_price == cost_before
    assert db.query(models.Supplier).filter(
        models.Supplier.shop_id == ctx["shop_id"]
    ).count() == 0
    assert db.query(models.PurchaseReceipt).filter(
        models.PurchaseReceipt.shop_id == ctx["shop_id"]
    ).count() == 0


def test_cac_bang_moi_ton_tai_va_migration_chay_lap(client, db):
    expected = {
        "suppliers",
        "purchase_receipts",
        "purchase_receipt_items",
        "supplier_payable_entries",
        "supplier_payments",
        "supplier_payment_allocations",
    }
    actual = {
        row[0]
        for row in db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
    }
    assert expected <= actual
    bootstrap.run_migrations(db)
    bootstrap.run_migrations(db)
    protected = {
        "ux_suppliers_create_operation_id",
        "ux_purchase_receipts_create_operation_id",
        "ux_purchase_receipts_confirm_operation_id",
        "ux_supplier_payable_entries_idempotency_key",
        "ux_supplier_payable_entries_receipt_id",
        "ux_supplier_payments_idempotency_key",
        "ux_supplier_payment_allocations_pair",
    }
    assert not protected.intersection(bootstrap.verify_required_indexes(db))


def test_unique_index_bao_ve_phieu_but_toan_va_thanh_toan(client, db):
    protected = {
        "ux_suppliers_create_operation_id": "suppliers",
        "ux_purchase_receipts_create_operation_id": "purchase_receipts",
        "ux_purchase_receipts_confirm_operation_id": "purchase_receipts",
        "ux_supplier_payable_entries_idempotency_key": "supplier_payable_entries",
        "ux_supplier_payable_entries_receipt_id": "supplier_payable_entries",
        "ux_supplier_payments_idempotency_key": "supplier_payments",
        "ux_supplier_payment_allocations_pair": "supplier_payment_allocations",
    }
    for name, table in protected.items():
        indexes = {
            row[1]: row[2]
            for row in db.execute(text(f'PRAGMA index_list("{table}")'))
        }
        assert indexes.get(name) == 1, f"{name} phải là UNIQUE"
        assert name in bootstrap._REQUIRED_INDEXES
        assert name in bootstrap._FINANCIAL_INDEXES
        assert name not in bootstrap.verify_required_indexes(db)


def test_verify_khong_tin_index_tai_chinh_chi_vi_trung_ten(client, db):
    name = "ux_supplier_payments_idempotency_key"
    db.execute(text(f'DROP INDEX "{name}"'))
    db.execute(text(
        f'CREATE INDEX "{name}" ON supplier_payments(method)'
    ))
    db.commit()
    try:
        assert name in bootstrap.verify_required_indexes(db)
    finally:
        db.execute(text(f'DROP INDEX "{name}"'))
        db.execute(text(
            f'CREATE UNIQUE INDEX "{name}" '
            "ON supplier_payments(idempotency_key)"
        ))
        db.commit()
