"""I09-C: durable offline issue rows, read model and acknowledge lifecycle.

`orders.offline_issue` is a comma-joined string. It cannot say which line broke,
how much is still missing, or who acknowledged what - so a shop owner who fixes
one problem still sees the order sitting on "Cần xử lý" forever. Every test here
is one way that string used to lie.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from conftest import (
    _TEST_MIGRATIONS,
    _unique,
    auth,
    create_product,
    new_seller,
    new_staff,
    seller_with_shop,
)

from fselling.core.database import SessionLocal
from fselling.services import offline_service


def _uid() -> str:
    return "off-" + _uuid.uuid4().hex


def _phieu(items, *, luc_ban=None, uuid=None, may="POS-01", tien_dua=None):
    tong = sum(i["unit_price"] * i["quantity"] for i in items)
    return {
        "offline_uuid": uuid or _uid(),
        "sold_at": (luc_ban or datetime.utcnow()).isoformat(),
        "items": items,
        "cash_tendered": tong if tien_dua is None else tien_dua,
        "device_label": may,
    }


def _dong(product, *, so_luong=1, gia=None):
    return {
        "product_id": product["id"],
        "product_name": product["name"],
        "unit_price": product["price"] if gia is None else gia,
        "quantity": so_luong,
    }


def _gui(client, ctx, phieu):
    return client.post(
        f"/api/orders/{ctx['shop_id']}/offline",
        json=phieu,
        headers=auth(ctx["token"]),
    )


def _mo_ca(client, ctx, tien_dau=0):
    res = client.post(
        f"/api/shifts/{ctx['shop_id']}/open",
        json={"opening_cash_amount": tien_dau},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _issues(client, ctx, token=None, **params):
    res = client.get(
        f"/api/orders/{ctx['shop_id']}/offline-issues",
        params=params,
        headers=auth(token or ctx["token"]),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _rows(sql, **params):
    session = SessionLocal()
    try:
        return [dict(r._mapping) for r in session.execute(text(sql), params)]
    finally:
        session.close()


def _issue_rows(order_id):
    return _rows(
        """SELECT id, order_id, order_item_id, product_id, issue_code,
                  evidence_kind, evidence_id, severity, state, reason,
                  resolution_kind, resolved_by_user_id, state_version
           FROM offline_receipt_issues WHERE order_id = :o ORDER BY id""",
        o=order_id,
    )


# ---------- Ingest: đúng scope cho từng loại vướng mắc ----------


def test_ton_am_non_batch_tao_evidence_exact_va_issue_theo_dong(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)

    res = _gui(client, ctx, _phieu([_dong(ctx["product"], so_luong=14)]))
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    # Tồn 10, bán 14 -> thiếu đúng 4, không phải "âm 4" ở một con số tổng nào.
    evidence = _rows(
        """SELECT d.* FROM offline_stock_deficits d
           JOIN order_items i ON i.id = d.order_item_id
           WHERE i.order_id = :o""",
        o=order_id,
    )
    assert len(evidence) == 1
    assert evidence[0]["deficit_quantity"] == 4
    assert evidence[0]["remaining_quantity"] == 4
    assert evidence[0]["state_version"] == 0
    assert evidence[0]["resolution_kind"] is None
    assert evidence[0]["resolved_by_user_id"] is None
    assert evidence[0]["resolved_at"] is None

    issues = _issue_rows(order_id)
    assert [i["issue_code"] for i in issues] == ["TON_AM"]
    assert issues[0]["evidence_kind"] == "OFFLINE_STOCK_DEFICIT"
    assert issues[0]["evidence_id"] == evidence[0]["id"]
    assert issues[0]["order_item_id"] is not None
    assert (issues[0]["severity"], issues[0]["state"]) == ("ACTION", "OPEN")


def test_hai_dong_cung_san_pham_thieu_tao_hai_evidence_rieng(client):
    """Bội số dòng phải giữ nguyên: gộp lại là mất dấu một dòng hàng thật."""
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)

    # Tồn 10. Theo thứ tự canonical (giá thấp trước): dòng 12 lấy hết 10 rồi
    # thiếu 2, dòng 3 tiếp theo không còn gì nên thiếu cả 3.
    res = _gui(
        client,
        ctx,
        _phieu([
            _dong(ctx["product"], so_luong=12),
            _dong(ctx["product"], so_luong=3, gia=ctx["product"]["price"] + 1000),
        ]),
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    evidence = _rows(
        """SELECT d.id, d.order_item_id, d.deficit_quantity
           FROM offline_stock_deficits d
           JOIN order_items i ON i.id = d.order_item_id
           WHERE i.order_id = :o ORDER BY d.id""",
        o=order_id,
    )
    assert [row["deficit_quantity"] for row in evidence] == [2, 3]
    assert len({row["order_item_id"] for row in evidence}) == 2

    issues = _issue_rows(order_id)
    ton_am = [i for i in issues if i["issue_code"] == "TON_AM"]
    assert len(ton_am) == 2, "hai dòng hỏng là hai việc phải xử lý, không phải một"
    assert {i["evidence_id"] for i in ton_am} == {row["id"] for row in evidence}


def test_gia_doi_la_thong_tin_nen_ghi_thang_resolved(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)

    res = _gui(
        client,
        ctx,
        _phieu([_dong(ctx["product"], so_luong=1, gia=ctx["product"]["price"] - 5000)]),
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    assert "GIA_DOI" in res.json()["issues"], "response cũ không được đổi"

    issues = _issue_rows(order_id)
    assert [i["issue_code"] for i in issues] == ["GIA_DOI"]
    assert issues[0]["severity"] == "INFO"
    assert issues[0]["state"] == "RESOLVED"
    assert issues[0]["resolution_kind"] == "INFORMATIONAL_AT_INGEST"
    assert issues[0]["resolved_by_user_id"] is not None
    assert issues[0]["order_item_id"] is not None

    # Đơn ghi đúng giá khách đã trả; không có gì phải làm nên không chiếm chỗ.
    assert _issues(client, ctx) == []


def test_sp_khong_con_theo_dong_va_khong_bao_gio_tu_resolve(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = create_product(
        client, ctx["token"], ctx["shop_id"], _unique("SP"), 50000, 5,
        ctx["category_id"],
    )
    res = client.delete(f"/api/products/{sp['id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200, res.text

    res = _gui(client, ctx, _phieu([_dong(sp, so_luong=2)]))
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    issues = _issue_rows(order_id)
    assert [i["issue_code"] for i in issues] == ["SP_KHONG_CON"]
    assert issues[0]["evidence_kind"] == "CATALOG"
    assert (issues[0]["severity"], issues[0]["state"]) == ("ACTION", "OPEN")
    assert issues[0]["order_item_id"] is not None
    assert issues[0]["evidence_id"] is None


def test_van_de_ca_thuoc_ve_ca_phieu_khong_thuoc_dong_nao(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    hom_qua = datetime.utcnow() - timedelta(days=1)

    res = _gui(client, ctx, _phieu([_dong(ctx["product"])], luc_ban=hom_qua))
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    issues = _issue_rows(order_id)
    assert [i["issue_code"] for i in issues] == ["KHONG_CO_CA"]
    assert issues[0]["evidence_kind"] == "SHIFT"
    assert issues[0]["order_item_id"] is None
    assert issues[0]["product_id"] is None


def test_phieu_tron_nhieu_van_de_tao_dung_scope_tung_loai(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    da_xoa = create_product(
        client, ctx["token"], ctx["shop_id"], _unique("SP"), 50000, 5,
        ctx["category_id"],
    )
    client.delete(f"/api/products/{da_xoa['id']}", headers=auth(ctx["token"]))
    hom_qua = datetime.utcnow() - timedelta(days=1)

    res = _gui(
        client,
        ctx,
        _phieu(
            [
                _dong(ctx["product"], so_luong=14),
                _dong(da_xoa, so_luong=1),
            ],
            luc_ban=hom_qua,
        ),
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    issues = _issue_rows(order_id)
    theo_ma = {i["issue_code"]: i for i in issues}
    assert set(theo_ma) == {"TON_AM", "SP_KHONG_CON", "KHONG_CO_CA"}
    assert theo_ma["TON_AM"]["order_item_id"] is not None
    assert theo_ma["SP_KHONG_CON"]["order_item_id"] is not None
    assert theo_ma["KHONG_CO_CA"]["order_item_id"] is None
    # Bản sao tương thích vẫn phải khớp bảng issue, verifier 0005 soi cả hai chiều.
    assert set(res.json()["issues"]) == set(theo_ma)
    _TEST_MIGRATIONS.verify()


def test_gui_lai_cung_phieu_khong_nhan_doi_issue_hay_evidence(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    phieu = _phieu([_dong(ctx["product"], so_luong=14)])

    dau = _gui(client, ctx, phieu)
    assert dau.status_code == 200, dau.text
    order_id = dau.json()["order_id"]

    lai = _gui(client, ctx, phieu)
    assert lai.status_code == 200, lai.text
    assert lai.json()["created"] is False
    assert lai.json()["order_id"] == order_id

    assert len(_issue_rows(order_id)) == 1
    evidence = _rows(
        """SELECT d.id FROM offline_stock_deficits d
           JOIN order_items i ON i.id = d.order_item_id WHERE i.order_id = :o""",
        o=order_id,
    )
    assert len(evidence) == 1


# ---------- Read model ----------


def test_mac_dinh_chi_hien_open_va_history_tra_lai_duoc(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    hom_qua = datetime.utcnow() - timedelta(days=1)
    thong_tin = _gui(
        client, ctx,
        _phieu([_dong(ctx["product"], gia=ctx["product"]["price"] - 1000)]),
    )
    can_lam = _gui(client, ctx, _phieu([_dong(ctx["product"])], luc_ban=hom_qua))
    assert thong_tin.status_code == 200 and can_lam.status_code == 200

    mo = _issues(client, ctx)
    assert [m["order_id"] for m in mo] == [can_lam.json()["order_id"]]
    assert mo[0]["issues"] == ["KHONG_CO_CA"]
    assert mo[0]["issue_details"][0]["state"] == "OPEN"
    assert mo[0]["issue_details"][0]["severity"] == "ACTION"

    da_xong = _issues(client, ctx, state="RESOLVED")
    assert [m["order_id"] for m in da_xong] == [thong_tin.json()["order_id"]]

    tat_ca = {m["order_id"] for m in _issues(client, ctx, state="ALL")}
    assert tat_ca == {thong_tin.json()["order_id"], can_lam.json()["order_id"]}


def test_read_model_giu_field_tuong_thich_va_khong_lo_bang_chung_noi_bo(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    res = _gui(
        client, ctx,
        _phieu([_dong(ctx["product"], so_luong=14)], may="POS-KIOT-2"),
    )
    assert res.status_code == 200, res.text

    ds = _issues(client, ctx)
    assert len(ds) == 1
    muc = ds[0]
    assert {"order_id", "sold_at", "total", "device", "shift_id", "issues"} <= set(muc)
    assert muc["device"] == "POS-KIOT-2", "chủ shop cần biết máy nào bán"
    assert "TON_AM" in muc["issues"]

    chi_tiet = muc["issue_details"][0]
    assert chi_tiet["remaining_quantity"] == 4
    assert chi_tiet["state_version"] == 0
    assert chi_tiet["evidence_kind"] == "OFFLINE_STOCK_DEFICIT"

    phang = str(muc)
    for cam in ("fingerprint", "offline_uuid", "cost", "reason"):
        assert cam not in phang


def test_state_khong_hop_le_bi_tu_choi(client):
    ctx = seller_with_shop(client)
    res = client.get(
        f"/api/orders/{ctx['shop_id']}/offline-issues",
        params={"state": "DA_XONG_HET"},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400


def test_khong_doc_duoc_van_de_cua_shop_khac(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    _gui(client, ctx, _phieu([_dong(ctx["product"], so_luong=14)]))
    _, token_b = new_seller(client)

    res = client.get(
        f"/api/orders/{ctx['shop_id']}/offline-issues", headers=auth(token_b)
    )
    assert res.status_code == 403


# ---------- Acknowledge ----------


def _mot_issue(client, ctx, code):
    for muc in _issues(client, ctx, state="ALL"):
        for chi_tiet in muc["issue_details"]:
            if chi_tiet["code"] == code:
                return chi_tiet
    raise AssertionError(f"khong tim thay issue {code}")


def _ack(client, ctx, issue, *, token=None, reason="Da doi chieu so ca", version=None):
    return client.post(
        f"/api/orders/{ctx['shop_id']}/offline-issues/{issue['id']}/acknowledge",
        json={
            "reason": reason,
            "state_version": issue["state_version"] if version is None else version,
        },
        headers=auth(token or ctx["token"]),
    )


def _ctx_khong_co_ca(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    hom_qua = datetime.utcnow() - timedelta(days=1)
    res = _gui(client, ctx, _phieu([_dong(ctx["product"])], luc_ban=hom_qua))
    assert res.status_code == 200, res.text
    return ctx, res.json()["order_id"]


def test_chu_shop_ack_duoc_van_de_ca_va_co_audit(client):
    ctx, order_id = _ctx_khong_co_ca(client)
    issue = _mot_issue(client, ctx, "KHONG_CO_CA")

    res = _ack(client, ctx, issue)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "ACKNOWLEDGED"
    assert res.json()["state_version"] == issue["state_version"] + 1

    row = _issue_rows(order_id)[0]
    assert row["state"] == "ACKNOWLEDGED"
    assert row["reason"] == "Da doi chieu so ca"
    assert row["resolution_kind"] is None, "xác nhận không phải là một resolution"
    assert row["resolved_by_user_id"] is not None

    audit = _rows(
        "SELECT details FROM system_logs WHERE action = 'OFFLINE_ISSUE_ACK'"
    )
    assert any(f"#{order_id}" in a["details"] for a in audit)
    # Đã xác nhận thì rời màn "Cần xử lý" nhưng vẫn tra lại được.
    assert _issues(client, ctx) == []
    assert [m["order_id"] for m in _issues(client, ctx, state="ACKNOWLEDGED")] == [
        order_id
    ]
    _TEST_MIGRATIONS.verify()


def test_nhan_vien_kho_khong_ack_duoc_du_co_quyen_kiem_ke(client):
    ctx, _order_id = _ctx_khong_co_ca(client)
    issue = _mot_issue(client, ctx, "KHONG_CO_CA")
    _, kho = new_staff(client, ctx, staff_role="WAREHOUSE")

    res = _ack(client, ctx, issue, token=kho)
    assert res.status_code == 403


def test_ton_am_exact_khong_bao_gio_ack_duoc(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    _gui(client, ctx, _phieu([_dong(ctx["product"], so_luong=14)]))
    issue = _mot_issue(client, ctx, "TON_AM")

    res = _ack(client, ctx, issue)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OFFLINE_ISSUE_EVIDENCE_REQUIRED"
    assert _issue_rows(issue["id"] and _issues(client, ctx)[0]["order_id"])[0][
        "state"
    ] == "OPEN"


def test_sp_khong_con_can_phuc_hoi_chu_khong_phai_nut_da_xem(client):
    ctx = seller_with_shop(client)
    _mo_ca(client, ctx)
    sp = create_product(
        client, ctx["token"], ctx["shop_id"], _unique("SP"), 50000, 5,
        ctx["category_id"],
    )
    client.delete(f"/api/products/{sp['id']}", headers=auth(ctx["token"]))
    _gui(client, ctx, _phieu([_dong(sp, so_luong=1)]))
    issue = _mot_issue(client, ctx, "SP_KHONG_CON")

    res = _ack(client, ctx, issue)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OFFLINE_ISSUE_RECOVERY_REQUIRED"


def test_version_cu_bi_tu_choi_va_ack_hai_lan_khong_nhan_audit(client):
    ctx, order_id = _ctx_khong_co_ca(client)
    issue = _mot_issue(client, ctx, "KHONG_CO_CA")

    assert _ack(client, ctx, issue).status_code == 200
    truoc = len(_rows("SELECT id FROM system_logs WHERE action='OFFLINE_ISSUE_ACK'"))

    lai = _ack(client, ctx, issue)
    assert lai.status_code == 409
    assert lai.json()["detail"]["code"] == "OFFLINE_ISSUE_STATE_CONFLICT"
    sau = len(_rows("SELECT id FROM system_logs WHERE action='OFFLINE_ISSUE_ACK'"))
    assert sau == truoc, "retry không được nhân audit"


def test_ly_do_toan_khoang_trang_bi_tu_choi_truoc_moi_side_effect(client):
    ctx, order_id = _ctx_khong_co_ca(client)
    issue = _mot_issue(client, ctx, "KHONG_CO_CA")

    res = _ack(client, ctx, issue, reason="    ")
    assert res.status_code == 400
    assert _issue_rows(order_id)[0]["state"] == "OPEN"


def test_loi_audit_lam_rollback_ca_transition(client, monkeypatch):
    ctx, order_id = _ctx_khong_co_ca(client)
    issue = _mot_issue(client, ctx, "KHONG_CO_CA")

    def _no(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(offline_service.order_service, "_them_nhat_ky", _no)
    with pytest.raises(RuntimeError):
        _ack(client, ctx, issue)

    assert _issue_rows(order_id)[0]["state"] == "OPEN"
    assert _issue_rows(order_id)[0]["reason"] is None
