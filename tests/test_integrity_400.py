"""Vi phạm ràng buộc duy nhất ở tầng DB phải thành 400 có nghĩa, không phải 500.

Giữa lúc service kiểm trùng và lúc commit vẫn có khe: hai request cùng gửi một
mã có thể cùng vượt qua bước kiểm. Unique index chặn được, nhưng nếu để nguyên
`IntegrityError` thì người dùng nhận 500 và không biết phải đổi mã.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from conftest import auth, seller_with_shop
from fselling.core import bootstrap
from fselling.services import catalog_service


def _tao(client, ctx, ten, code=None, barcode=None):
    data = {"name": ten, "price": 1000, "stock": 1, "category_id": ctx["category_id"]}
    if code is not None:
        data["code"] = code
    if barcode is not None:
        data["barcode"] = barcode
    return client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data=data,
        headers=auth(ctx["token"]),
    )


# ---------- Dịch lỗi: kiểm thẳng _commit_bat_trung ----------


class _DbGia:
    """Session giả: commit() ném đúng lỗi mình muốn, ghi nhận có rollback không."""

    def __init__(self, loi):
        self.loi = loi
        self.da_rollback = False

    def commit(self):
        raise self.loi

    def rollback(self):
        self.da_rollback = True


def _loi_unique(cot):
    return IntegrityError(
        "stmt", {}, Exception(f"UNIQUE constraint failed: {cot}")
    )


@pytest.mark.parametrize(
    "cot, trong_thong_bao",
    [
        ("products.shop_id, products.code", "Mã sản phẩm"),
        ("products.shop_id, products.barcode", "Mã vạch"),
        ("products.shop_id, products.name", "Tên sản phẩm"),
    ],
)
def test_dich_loi_trung_thanh_400(cot, trong_thong_bao):
    db = _DbGia(_loi_unique(cot))
    with pytest.raises(HTTPException) as e:
        catalog_service._commit_bat_trung(db)
    assert e.value.status_code == 400
    assert trong_thong_bao in e.value.detail
    assert db.da_rollback, "phải rollback trước khi ném ra, nếu không session kẹt"


def test_loi_integrity_la_van_nem_tiep():
    """Không được nuốt lỗi lạ - đó là bug cần lộ ra thành 500, không phải 400."""
    db = _DbGia(IntegrityError("stmt", {}, Exception("FOREIGN KEY constraint failed")))
    with pytest.raises(IntegrityError):
        catalog_service._commit_bat_trung(db)
    assert db.da_rollback


# ---------- Đi hết đường HTTP: tắt bước kiểm để mô phỏng khe race ----------


def test_trung_ma_sp_o_tang_db_tra_400(client, monkeypatch):
    ctx = seller_with_shop(client)
    assert _tao(client, ctx, "Race A", code="RACE-01").status_code == 200

    monkeypatch.setattr(catalog_service, "_ensure_code_unique", lambda *a, **k: None)
    res = _tao(client, ctx, "Race B", code="RACE-01")
    assert res.status_code == 400, res.text
    assert "Mã sản phẩm" in res.json()["detail"]


def test_trung_ma_vach_o_tang_db_tra_400(client, monkeypatch):
    ctx = seller_with_shop(client)
    assert _tao(client, ctx, "Race C", barcode="7770000000001").status_code == 200

    monkeypatch.setattr(catalog_service, "_ensure_barcode_unique", lambda *a, **k: None)
    res = _tao(client, ctx, "Race D", barcode="7770000000001")
    assert res.status_code == 400, res.text
    assert "Mã vạch" in res.json()["detail"]


def test_session_van_dung_duoc_sau_khi_bi_tu_choi(client, monkeypatch):
    """Sau lỗi trùng, request kế tiếp phải chạy bình thường (không kẹt transaction)."""
    ctx = seller_with_shop(client)
    assert _tao(client, ctx, "Race E", code="RACE-09").status_code == 200

    monkeypatch.setattr(catalog_service, "_ensure_code_unique", lambda *a, **k: None)
    assert _tao(client, ctx, "Race F", code="RACE-09").status_code == 400
    monkeypatch.undo()

    assert _tao(client, ctx, "Race G", code="RACE-10").status_code == 200
    ds = client.get(f"/api/products/{ctx['shop_id']}")
    assert ds.status_code == 200
    ma = sorted(p["code"] for p in ds.json() if p["code"].startswith("RACE-"))
    assert ma == ["RACE-09", "RACE-10"]


# ---------- Ràng buộc tên ở tầng DB ----------


def test_unique_index_ten_san_pham_ton_tai(client, db):
    """Trước đây tên trùng lọt qua trong im lặng vì DB không có ràng buộc nào."""
    assert "ix_products_shop_name" not in bootstrap.verify_required_indexes(db)


def test_tao_sp_trung_ten_van_bi_chan_o_tang_service(client):
    ctx = seller_with_shop(client)
    assert _tao(client, ctx, "Ten Doc Nhat").status_code == 200
    res = _tao(client, ctx, "Ten Doc Nhat")
    assert res.status_code == 400
    assert "đã tồn tại" in res.json()["detail"]
