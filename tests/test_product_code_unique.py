"""B1c: mã nội bộ của sản phẩm phải duy nhất trong mỗi shop.

Bản cũ sinh mã bằng `SP-<timestamp giây>` nên mọi sản phẩm tạo trong cùng một
giây đều trùng mã, và `update_product` không kiểm trùng chút nào.
"""
from __future__ import annotations

from sqlalchemy import text

from conftest import (
    auth,
    create_category,
    create_shop,
    new_seller,
    seller_with_shop,
)
from fselling.core import bootstrap


def _tao_sp(client, token, shop_id, cat_id, name, code=None, price=50000, stock=5):
    data = {"name": name, "price": price, "stock": stock, "category_id": cat_id}
    if code is not None:
        data["code"] = code
    return client.post(
        "/api/products", params={"shop_id": shop_id}, data=data, headers=auth(token)
    )


# ---------- Sinh mã ----------


def test_tao_nhieu_sp_lien_tiep_khong_trung_ma(client):
    """Bài kiểm cốt lõi: bản cũ trượt bài này vì mã lấy theo giây.

    Bốn sản phẩm tạo liên tiếp chắc chắn nằm trong cùng một giây.
    """
    ctx = seller_with_shop(client)
    ma = []
    for i in range(4):
        res = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], f"SP so {i}")
        assert res.status_code == 200, res.text
        ma.append(res.json()["code"])

    assert len(set(ma)) == 4, f"Mã bị trùng: {ma}"


def test_ma_tu_sinh_theo_id_san_pham(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP theo id")
    body = res.json()
    assert body["code"] == f"SP-{body['id']}"


def test_ma_tu_nhap_duoc_giu_nguyen(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP ma rieng", code="TUI-01"
    )
    assert res.json()["code"] == "TUI-01"


def test_ma_chi_co_khoang_trang_thi_tu_sinh(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP trang", code="   "
    )
    body = res.json()
    assert body["code"] == f"SP-{body['id']}"


# ---------- Chống trùng ----------


def test_tao_sp_trung_ma_bi_chan(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP A", code="TRUNG-01")
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP B", code="TRUNG-01"
    )
    assert res.status_code == 400
    assert "SP A" in res.json()["detail"]


def test_sua_sp_sang_ma_cua_sp_khac_bi_chan(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP C", code="GIU-01")
    sp2 = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP D", code="GIU-02"
    ).json()

    res = client.put(
        f"/api/products/{sp2['id']}",
        data={
            "name": "SP D",
            "price": 50000,
            "category_id": ctx["category_id"],
            "code": "GIU-01",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert "SP C" in res.json()["detail"]


def test_sua_sp_giu_nguyen_ma_cua_chinh_no(client):
    """Lưu lại form mà không đổi mã không được báo trùng với chính nó."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP E", code="CHINH-NO"
    ).json()

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": "SP E doi ten",
            "price": 60000,
            "category_id": ctx["category_id"],
            "code": "CHINH-NO",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["code"] == "CHINH-NO"


def test_hai_shop_khac_nhau_duoc_trung_ma(client):
    """Mã chỉ duy nhất trong phạm vi một shop, không phải toàn hệ thống."""
    ctx1 = seller_with_shop(client)
    _tao_sp(client, ctx1["token"], ctx1["shop_id"], ctx1["category_id"], "SP F", code="CHUNG")

    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = create_category(client, token2, shop2)
    res = _tao_sp(client, token2, shop2, cat2, "SP F", code="CHUNG")
    assert res.status_code == 200, res.text


# ---------- Migration dọn mã trùng ----------


def _bo_unique_index(db):
    """Đưa DB về trạng thái bản cũ: chưa có unique index nên trùng mã lọt được."""
    db.execute(text("DROP INDEX IF EXISTS ix_products_shop_code"))
    db.commit()


def test_dedupe_doi_ma_trung_giu_lai_id_nho_nhat(client, db):
    """Mô phỏng dữ liệu do bản cũ tạo (chưa có index, mã trùng) rồi dọn."""
    ctx = seller_with_shop(client)
    a = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Dedupe A").json()
    b = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Dedupe B").json()
    c = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Dedupe C").json()

    _bo_unique_index(db)
    db.execute(
        text("UPDATE products SET code = 'SP-DUP' WHERE id IN (:a, :b, :c)"),
        {"a": a["id"], "b": b["id"], "c": c["id"]},
    )
    db.commit()

    trung, rong = bootstrap.dedupe_product_codes(db)
    assert trung == 2  # giữ 1, đổi 2

    # Dọn xong thì index phải tạo lại được - đây là điều kiện để app khởi động
    # trên một DB cũ mà không âm thầm bỏ qua ràng buộc.
    bootstrap.run_migrations(db)
    assert bootstrap.verify_required_indexes(db) == []

    def _ma(pid):
        return db.execute(
            text("SELECT code FROM products WHERE id = :id"), {"id": pid}
        ).scalar()

    assert _ma(a["id"]) == "SP-DUP"          # id nhỏ nhất giữ mã cũ
    assert _ma(b["id"]) == f"SP-{b['id']}"
    assert _ma(c["id"]) == f"SP-{c['id']}"


def test_dedupe_dien_ma_rong(client, db):
    ctx = seller_with_shop(client)
    sp = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Ma rong").json()

    _bo_unique_index(db)
    db.execute(text("UPDATE products SET code = '' WHERE id = :id"), {"id": sp["id"]})
    db.commit()

    trung, rong = bootstrap.dedupe_product_codes(db)
    assert rong >= 1
    ma = db.execute(
        text("SELECT code FROM products WHERE id = :id"), {"id": sp["id"]}
    ).scalar()
    assert ma == f"SP-{sp['id']}"

    # DB dùng chung cho cả phiên test: trả index về chỗ cũ.
    bootstrap.run_migrations(db)


def test_dedupe_chay_lai_khong_doi_gi_them(client, db):
    """Migration phải chạy lặp lại được - app khởi động lại là chạy lại."""
    bootstrap.dedupe_product_codes(db)
    assert bootstrap.dedupe_product_codes(db) == (0, 0)


def test_dedupe_khong_dung_toi_sp_khong_trung(client, db):
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Yen on", code="YEN-ON"
    ).json()

    bootstrap.dedupe_product_codes(db)

    ma = db.execute(
        text("SELECT code FROM products WHERE id = :id"), {"id": sp["id"]}
    ).scalar()
    assert ma == "YEN-ON"


def test_unique_index_ma_noi_bo_ton_tai(client, db):
    assert "ix_products_shop_code" not in bootstrap.verify_required_indexes(db)
