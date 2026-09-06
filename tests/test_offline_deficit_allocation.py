"""I09-C: FIFO + CAS allocation of a positive stocktake onto exact evidence.

The number that must never be guessed is "how much of the missing stock came
back". Before this slice the only trace of a non-batch offline shortfall was
`products.cost_deficit_qty` - an aggregate that cannot say WHICH sale was short,
so nothing could decide which problem a stocktake just fixed.

Every test here is one way that decision can go wrong: closing too much, closing
the wrong row, closing on a count that proves nothing, or closing against a
snapshot that has moved underneath the sheet.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from conftest import (
    _TEST_MIGRATIONS,
    _unique,
    auth,
    create_product,
    new_staff,
    seller_with_shop,
)

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import catalog_service, inventory_service


def _uid() -> str:
    return "off-" + _uuid.uuid4().hex


def _mo_ca(client, ctx):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": 0},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _ban_offline(client, ctx, product, so_luong):
    """Bán offline nhiều hơn tồn -> sinh đúng một evidence exact cho dòng đó."""
    tong = product["price"] * so_luong
    res = client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        json={
            "offline_uuid": _uid(),
            "sold_at": datetime.utcnow().isoformat(),
            "items": [{
                "product_id": product["id"],
                "product_name": product["name"],
                "unit_price": product["price"],
                "quantity": so_luong,
            }],
            "cash_tendered": tong,
            "device_label": "POS-01",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _nhap_kho(client, ctx, product_id, delta):
    res = client.post(
        f"/api/products/{product_id}/stock",
        json={"delta": delta, "reason": "nhap bu"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _kiem_ke(client, ctx, items, token=None):
    return client.post(
        f"/api/products/{ctx['shop_id']}/stocktake",
        json={"items": items},
        headers=auth(token or ctx["token"]),
    )


def _rows(sql, **params):
    session = SessionLocal()
    try:
        return [dict(r._mapping) for r in session.execute(text(sql), params)]
    finally:
        session.close()


def _deficits(product_id):
    return _rows(
        """SELECT id, deficit_quantity, remaining_quantity, resolution_kind,
                  resolved_by_user_id, resolved_at, state_version
           FROM offline_stock_deficits WHERE product_id = :p ORDER BY id""",
        p=product_id,
    )


def _issue_states(product_id):
    return _rows(
        """SELECT s.evidence_id, s.state, s.resolution_kind, s.state_version
           FROM offline_receipt_issues s
           WHERE s.evidence_kind = 'OFFLINE_STOCK_DEFICIT'
             AND s.product_id = :p
           ORDER BY s.evidence_id""",
        p=product_id,
    )


def _ton(product_id):
    return _rows("SELECT stock, cost_deficit_qty FROM products WHERE id = :p",
                 p=product_id)[0]


def _snapshot(product_id):
    session = SessionLocal()
    try:
        return inventory_service.offline_stock_deficit_state(session, product_id)
    finally:
        session.close()


def _hai_thieu_5_va_3(client):
    """Dựng đúng hai evidence 5 và 3 trên cùng một sản phẩm, tồn về 0."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = ctx["product"]                       # tồn 10
    _ban_offline(client, ctx, sp, 15)         # thiếu 5, tồn -5
    _ban_offline(client, ctx, sp, 3)          # thiếu 3, tồn -8
    _nhap_kho(client, ctx, sp["id"], 8)       # hàng về, tồn 0
    assert [d["deficit_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert _ton(sp["id"])["stock"] == 0
    return ctx, sp


# ---------- Phân bổ FIFO ----------


def test_reconcile_6_dong_dong_dau_va_de_lai_2_o_dong_sau(client):
    """5 và 3, đếm dư 6: dòng cũ đóng, dòng sau còn 2. Tổng giảm đúng 6."""
    ctx, sp = _hai_thieu_5_va_3(client)
    snapshot = _snapshot(sp["id"])
    assert snapshot["open_quantity"] == 8

    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"],
        "counted": 6,
        "stock_snapshot": 0,
        "offline_deficit_snapshot": snapshot["snapshot"],
    }])
    assert res.status_code == 200, res.text
    assert res.json()["da_dieu_chinh"][0]["offline_deficit_reconciled"] == 6

    dau, sau = _deficits(sp["id"])
    assert (dau["remaining_quantity"], dau["resolution_kind"]) == (0, "STOCKTAKE")
    assert dau["resolved_by_user_id"] is not None
    assert len(dau["resolved_at"]) == 26
    assert dau["state_version"] == 1
    # Dòng sau chỉ giảm bớt: hàng vẫn còn thiếu 2, chưa có gì để giải quyết.
    assert (sau["remaining_quantity"], sau["resolution_kind"]) == (2, None)
    assert (sau["resolved_by_user_id"], sau["resolved_at"]) == (None, None)
    assert sau["state_version"] == 1
    assert _snapshot(sp["id"])["open_quantity"] == 2

    trang_thai = {i["evidence_id"]: i["state"] for i in _issue_states(sp["id"])}
    assert trang_thai == {dau["id"]: "RESOLVED", sau["id"]: "OPEN"}
    _TEST_MIGRATIONS.verify()


def test_dem_du_hon_tong_thieu_khong_dong_qua_muc(client):
    ctx, sp = _hai_thieu_5_va_3(client)
    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"],
        "counted": 30,
        "stock_snapshot": 0,
        "offline_deficit_snapshot": _snapshot(sp["id"])["snapshot"],
    }])
    assert res.status_code == 200, res.text
    assert res.json()["da_dieu_chinh"][0]["offline_deficit_reconciled"] == 8

    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [0, 0]
    assert all(i["state"] == "RESOLVED" for i in _issue_states(sp["id"]))
    assert _ton(sp["id"])["stock"] == 30
    _TEST_MIGRATIONS.verify()


@pytest.mark.parametrize("counted", [0, 5])
def test_dem_khong_tang_thi_khong_dong_bang_chung_nao(client, counted):
    """Đếm bằng hoặc thấp hơn tồn đang ghi không chứng minh hàng đã quay về."""
    ctx, sp = _hai_thieu_5_va_3(client)
    _nhap_kho(client, ctx, sp["id"], 5)        # tồn 5
    truoc = _deficits(sp["id"])

    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"],
        "counted": counted,
        "stock_snapshot": 5,
        "offline_deficit_snapshot": _snapshot(sp["id"])["snapshot"],
    }])
    assert res.status_code == 200, res.text
    assert "offline_deficit_reconciled" not in res.json()["da_dieu_chinh"][0] if (
        res.json()["da_dieu_chinh"]
    ) else True

    assert _deficits(sp["id"]) == truoc
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    _TEST_MIGRATIONS.verify()


def test_nhap_kho_va_gia_von_khong_tu_dong_dong_van_de(client):
    """`cost_deficit_qty` là số tổng, không phải bằng chứng của dòng nào."""
    ctx, sp = _hai_thieu_5_va_3(client)
    assert _ton(sp["id"])["cost_deficit_qty"] == 0, "nhập bù đã phủ phần thiếu"

    truoc = _deficits(sp["id"])
    _nhap_kho(client, ctx, sp["id"], 20)
    assert _deficits(sp["id"]) == truoc
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    _TEST_MIGRATIONS.verify()


# ---------- Snapshot token ----------


def test_thieu_token_thi_tu_choi_chu_khong_doan(client):
    ctx, sp = _hai_thieu_5_va_3(client)
    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 6, "stock_snapshot": 0,
    }])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OFFLINE_DEFICIT_SNAPSHOT_REQUIRED"
    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert _ton(sp["id"])["stock"] == 0, "cả phiếu phải rollback"


def test_token_cu_bi_tu_choi(client):
    ctx, sp = _hai_thieu_5_va_3(client)
    cu = _snapshot(sp["id"])["snapshot"]

    dau = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 3, "stock_snapshot": 0,
        "offline_deficit_snapshot": cu,
    }])
    assert dau.status_code == 200, dau.text

    lai = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 9, "stock_snapshot": 3,
        "offline_deficit_snapshot": cu,
    }])
    assert lai.status_code == 409
    assert lai.json()["detail"]["code"] == "OFFLINE_DEFICIT_SNAPSHOT_STALE"
    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [2, 3]
    assert _ton(sp["id"])["stock"] == 3, "tồn giữ nguyên kết quả phiếu trước"


def test_aba_cung_tong_nhung_khac_bang_chung_van_bi_tu_choi(client):
    """Tổng mở quay về đúng 8, nhưng đó không còn là 8 cũ."""
    ctx, sp = _hai_thieu_5_va_3(client)
    cu = _snapshot(sp["id"])
    assert cu["open_quantity"] == 8

    xong = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 3, "stock_snapshot": 0,
        "offline_deficit_snapshot": cu["snapshot"],
    }])
    assert xong.status_code == 200, xong.text
    _nhap_kho(client, ctx, sp["id"], 3)                  # tồn 6
    _ban_offline(client, ctx, sp, 9)                     # thiếu thêm 3
    moi = _snapshot(sp["id"])
    assert moi["open_quantity"] == 8, "tổng giống hệt lúc đầu"
    assert moi["snapshot"] != cu["snapshot"], "nhưng bằng chứng đã khác"

    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 5, "stock_snapshot": -3,
        "offline_deficit_snapshot": cu["snapshot"],
    }])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OFFLINE_DEFICIT_SNAPSHOT_STALE"


def test_san_pham_khong_co_evidence_van_kiem_ke_nhu_cu(client):
    ctx = seller_with_shop(client)
    res = _kiem_ke(client, ctx, [{
        "product_id": ctx["product"]["id"], "counted": 7, "stock_snapshot": 10,
    }])
    assert res.status_code == 200, res.text
    assert res.json()["da_dieu_chinh"][0]["lech"] == -3


# ---------- CAS ----------


def test_cas_tu_choi_khi_dong_da_doi_duoi_chan(client):
    """Hàng rào cuối: dòng đã đổi sau khi đọc thì tuyệt đối không được ghi đè.

    Giữ tham chiếu mạnh tới các ORM object rồi sửa thẳng DB dưới chân chúng -
    đó chính là hình dạng của một lần đọc cũ đi vào câu UPDATE.
    """
    ctx, sp = _hai_thieu_5_va_3(client)
    session = SessionLocal()
    try:
        doc_cu = (
            session.query(models.OfflineStockDeficit)
            .filter(models.OfflineStockDeficit.product_id == sp["id"])
            .order_by(models.OfflineStockDeficit.id)
            .all()
        )
        assert [r.remaining_quantity for r in doc_cu] == [5, 3]
        session.execute(
            text(
                "UPDATE offline_stock_deficits"
                "   SET remaining_quantity = remaining_quantity - 1,"
                "       state_version = state_version + 1"
                " WHERE id = :id"
            ),
            {"id": doc_cu[0].id},
        )
        assert doc_cu[0].remaining_quantity == 5, "ORM vẫn đang cầm bản cũ"

        with pytest.raises(HTTPException) as loi:
            inventory_service.reconcile_offline_stock_deficits(
                session,
                sp["id"],
                6,
                actor_user_id=1,
                resolved_at="2026-08-11 10:00:00.000000",
            )
        assert loi.value.status_code == 409
        assert loi.value.detail["code"] == "OFFLINE_DEFICIT_CAS_CONFLICT"
    finally:
        session.rollback()
        session.close()

    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    _TEST_MIGRATIONS.verify()


def test_cas_conflict_giua_chung_lam_rollback_ca_phieu(client, monkeypatch):
    """Một dòng đã ghi rồi mới xung đột: cả phiếu phải quay lại nguyên trạng."""
    ctx, sp = _hai_thieu_5_va_3(client)
    snapshot = _snapshot(sp["id"])
    goc = inventory_service.reconcile_offline_stock_deficits

    def _no_giua_chung(db, product_id, quantity, **kwargs):
        goc(db, product_id, quantity, **kwargs)
        raise inventory_service._cas_conflict()

    monkeypatch.setattr(
        catalog_service.inventory_service,
        "reconcile_offline_stock_deficits",
        _no_giua_chung,
    )
    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 6, "stock_snapshot": 0,
        "offline_deficit_snapshot": snapshot["snapshot"],
    }])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OFFLINE_DEFICIT_CAS_CONFLICT"

    monkeypatch.undo()
    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    assert _ton(sp["id"])["stock"] == 0
    _TEST_MIGRATIONS.verify()


def test_loi_audit_lam_rollback_ton_gia_von_va_bang_chung(client, monkeypatch):
    ctx, sp = _hai_thieu_5_va_3(client)
    snapshot = _snapshot(sp["id"])
    truoc_ton = _ton(sp["id"])

    def _no(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(catalog_service.models, "SystemLog", _no)
    with pytest.raises(RuntimeError):
        _kiem_ke(client, ctx, [{
            "product_id": sp["id"], "counted": 6, "stock_snapshot": 0,
            "offline_deficit_snapshot": snapshot["snapshot"],
        }])

    monkeypatch.undo()
    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    assert _ton(sp["id"]) == truoc_ton
    _TEST_MIGRATIONS.verify()


# ---------- Bằng chứng phải luôn có issue đi kèm ----------


def _audit(action):
    return _rows(
        "SELECT user_id, shop_id, details FROM system_logs"
        " WHERE action = :a ORDER BY id",
        a=action,
    )


def test_dong_hai_bang_chung_ghi_hai_dong_audit_rieng(client):
    """Mỗi issue đóng là một quyết định về tiền, nên phải có dấu vết riêng."""
    ctx, sp = _hai_thieu_5_va_3(client)
    truoc = len(_audit("OFFLINE_ISSUE_RESOLVED"))

    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 30, "stock_snapshot": 0,
        "offline_deficit_snapshot": _snapshot(sp["id"])["snapshot"],
    }])
    assert res.status_code == 200, res.text

    moi = _audit("OFFLINE_ISSUE_RESOLVED")[truoc:]
    assert len(moi) == 2, "hai bằng chứng đóng là hai transition"
    for dong in moi:
        assert dong["shop_id"] == ctx["shop_id"], "log không có shop là log vô hình"
        assert dong["user_id"] is not None
        assert "TON_AM" in dong["details"]
        assert "OPEN -> RESOLVED" in dong["details"]
    assert any("v1" in dong["details"] for dong in moi)
    # Log kiểm kê chung cũng phải gắn shop.
    assert _audit("STOCKTAKE")[-1]["shop_id"] == ctx["shop_id"]


def test_giam_mot_phan_khong_sinh_audit_resolved(client):
    ctx, sp = _hai_thieu_5_va_3(client)
    truoc = len(_audit("OFFLINE_ISSUE_RESOLVED"))

    res = _kiem_ke(client, ctx, [{
        "product_id": sp["id"], "counted": 3, "stock_snapshot": 0,
        "offline_deficit_snapshot": _snapshot(sp["id"])["snapshot"],
    }])
    assert res.status_code == 200, res.text
    assert len(_audit("OFFLINE_ISSUE_RESOLVED")) == truoc


def test_bang_chung_khong_co_issue_thi_khong_duoc_dong(client):
    """Đóng một khoản thiếu mà không có việc nào để đóng là mất dấu vết.

    Chạy trong session tự rollback: bằng chứng mồ côi là hình dạng 0005 cấm tồn
    tại, giữ lại sẽ làm mọi test sau trong phiên đỏ oan.
    """
    ctx, sp = _hai_thieu_5_va_3(client)
    session = SessionLocal()
    try:
        dau, sau = session.execute(
            text(
                "SELECT d.id, d.order_item_id, i.order_id"
                "  FROM offline_stock_deficits d"
                "  JOIN order_items i ON i.id = d.order_item_id"
                " WHERE d.product_id = :p ORDER BY d.id"
            ),
            {"p": sp["id"]},
        ).fetchall()
        # Hai issue trỏ về CÙNG một bằng chứng: bằng chứng không có chủ rõ ràng,
        # nên không ai được phép đóng nó.
        session.execute(
            text(
                "INSERT INTO offline_receipt_issues"
                " (order_id, order_item_id, product_id, issue_code,"
                "  evidence_kind, evidence_id, severity, state, opened_at,"
                "  state_version)"
                " VALUES (:o, :item, :p, 'TON_AM', 'OFFLINE_STOCK_DEFICIT',"
                "         :e, 'ACTION', 'OPEN', :ts, 0)"
            ),
            # Scope còn trống (đơn của dòng đầu, dòng hàng của dòng sau) nên chỉ
            # còn đúng một điều sai: hai issue cùng trỏ về một bằng chứng.
            {"o": dau[2], "item": sau[1], "p": sp["id"], "e": dau[0],
             "ts": "2026-08-11 10:00:00.000000"},
        )
        goc = dau
        with pytest.raises(HTTPException) as mo_ho:
            inventory_service.resolve_issue_for_evidence(
                session,
                evidence_kind="OFFLINE_STOCK_DEFICIT",
                evidence_id=int(goc[0]),
                actor_user_id=1,
                resolved_at="2026-08-11 10:00:00.000000",
            )
        assert mo_ho.value.detail["code"] == "OFFLINE_ISSUE_EVIDENCE_LINK_INVALID"
        session.rollback()

        # Và bằng chứng hoàn toàn không có issue nào.
        with pytest.raises(HTTPException) as thieu:
            inventory_service.resolve_issue_for_evidence(
                session,
                evidence_kind="OFFLINE_STOCK_DEFICIT",
                evidence_id=999999,
                actor_user_id=1,
                resolved_at="2026-08-11 10:00:00.000000",
            )
        assert thieu.value.status_code == 409
        assert thieu.value.detail["code"] == "OFFLINE_ISSUE_EVIDENCE_LINK_INVALID"
    finally:
        session.rollback()
        session.close()

    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert _ton(sp["id"])["stock"] == 0
    _TEST_MIGRATIONS.verify()


def test_issue_da_bi_ack_thi_khong_bi_dong_len_im_lang(client):
    """Trạng thái lạ phải dừng cả phiếu, không được bỏ qua rồi đóng bằng chứng.

    Chạy trong một session tự rollback: một issue evidence-linked ở trạng thái
    ACKNOWLEDGED là hình dạng 0005 cấm, giữ lại sẽ làm hỏng cả phiên test.
    """
    ctx, sp = _hai_thieu_5_va_3(client)
    session = SessionLocal()
    try:
        deficit_id = _deficits(sp["id"])[0]["id"]
        session.execute(
            text(
                "UPDATE offline_receipt_issues"
                "   SET state = 'ACKNOWLEDGED', reason = 'x',"
                "       resolved_by_user_id = 1, resolved_at = :ts,"
                "       state_version = state_version + 1"
                " WHERE evidence_kind = 'OFFLINE_STOCK_DEFICIT'"
                "   AND evidence_id = :e"
            ),
            {"e": deficit_id, "ts": "2026-08-11 10:00:00.000000"},
        )

        with pytest.raises(HTTPException) as loi:
            inventory_service.resolve_issue_for_evidence(
                session,
                evidence_kind="OFFLINE_STOCK_DEFICIT",
                evidence_id=deficit_id,
                actor_user_id=1,
                resolved_at="2026-08-11 10:00:00.000000",
            )
        assert loi.value.status_code == 409
        assert loi.value.detail["code"] == "OFFLINE_ISSUE_STATE_CONFLICT"
    finally:
        session.rollback()
        session.close()

    assert [d["remaining_quantity"] for d in _deficits(sp["id"])] == [5, 3]
    assert all(i["state"] == "OPEN" for i in _issue_states(sp["id"]))
    _TEST_MIGRATIONS.verify()


# ---------- Không đụng vào đường tracked ----------


def test_kiem_ke_khong_dong_bang_chung_cua_shop_khac(client):
    ctx_a, sp_a = _hai_thieu_5_va_3(client)
    ctx_b = seller_with_shop(client)

    res = _kiem_ke(ctx_b and client, ctx_b, [{
        "product_id": sp_a["id"], "counted": 6, "stock_snapshot": 0,
        "offline_deficit_snapshot": _snapshot(sp_a["id"])["snapshot"],
    }])
    assert res.status_code == 200, res.text
    assert res.json()["bo_qua"][0]["product_id"] == sp_a["id"]
    assert [d["remaining_quantity"] for d in _deficits(sp_a["id"])] == [5, 3]


def test_duong_lay_phieu_dem_tra_token_cho_hang_khong_theo_lo(client):
    ctx, sp = _hai_thieu_5_va_3(client)
    res = client.get(
        f"/api/products/{ctx['shop_id']}/stocktake/batches",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    dong = [p for p in res.json()["products"] if p["product_id"] == sp["id"]]
    assert len(dong) == 1
    assert dong[0]["track_batches"] is False
    assert dong[0]["batches"] == []
    assert dong[0]["offline_deficit_qty"] == 8
    assert dong[0]["offline_deficit_snapshot"] == _snapshot(sp["id"])["snapshot"]
    assert "cost_price" not in dong[0]
