"""B1a: mã vạch sản phẩm - lưu trữ, chuẩn hóa, chống trùng, tra cứu để quét."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from conftest import (
    auth,
    create_category,
    create_shop,
    new_seller,
    new_staff,
    seller_with_shop,
)
from fselling.core import bootstrap
from fselling.services import catalog_service


def _tao_sp(client, token, shop_id, cat_id, name, barcode=None, price=50000, stock=5):
    data = {"name": name, "price": price, "stock": stock, "category_id": cat_id}
    if barcode is not None:
        data["barcode"] = barcode
    res = client.post(
        "/api/products",
        params={"shop_id": shop_id},
        data=data,
        headers=auth(token),
    )
    return res


# ---------- Chuẩn hóa ----------


@pytest.mark.parametrize(
    "raw, mong_doi",
    [
        ("8934673001234", "8934673001234"),  # EAN-13 thường gặp
        ("  8934673001234  ", "8934673001234"),  # cắt khoảng trắng hai đầu
        ("893 4673 001234", "8934673001234"),  # máy quét chèn khoảng trắng giữa
        ("abc-123", "ABC-123"),  # viết hoa để tra cứu không phân biệt hoa/thường
        ("", None),  # rỗng = chưa gán mã vạch
        ("   ", None),
        (None, None),
    ],
)
def test_chuan_hoa_ma_vach(raw, mong_doi):
    assert catalog_service.normalize_barcode(raw) == mong_doi


@pytest.mark.parametrize("xau", ["123", "abc@123", "SP 1!", "x" * 65])
def test_ma_vach_sai_dinh_dang_bi_tu_choi(xau):
    with pytest.raises(HTTPException) as e:
        catalog_service.normalize_barcode(xau)
    assert e.value.status_code == 400


def test_khong_ep_checksum_ean13():
    """Mã nội bộ Code128 không theo chuẩn EAN vẫn phải nhận được.

    Nếu sau này ai đó thêm kiểm checksum, test này sẽ đỏ - đó là chủ ý.
    """
    assert catalog_service.normalize_barcode("0000000000000") == "0000000000000"
    assert catalog_service.normalize_barcode("KHO-A1-999") == "KHO-A1-999"


# ---------- Tạo & sửa sản phẩm ----------


def test_tao_sp_kem_ma_vach(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Sữa tươi", "8934673001234"
    )
    assert res.status_code == 200, res.text
    assert res.json()["barcode"] == "8934673001234"


def test_tao_sp_khong_co_ma_vach_thi_de_trong(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Bánh mì")
    assert res.status_code == 200, res.text
    assert res.json()["barcode"] is None


def test_ma_vach_duoc_viet_hoa_khi_luu(client):
    ctx = seller_with_shop(client)
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Kẹo", "kho-a1-001"
    )
    assert res.json()["barcode"] == "KHO-A1-001"


def test_danh_sach_sp_tra_ve_ma_vach(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Nước ngọt", "8935001234567")

    res = client.get(f"/api/products/{ctx['shop_id']}", headers=auth(ctx["token"]))
    assert res.status_code == 200
    sp = [p for p in res.json() if p["name"] == "Nước ngọt"][0]
    assert sp["barcode"] == "8935001234567"


def test_sua_sp_doi_ma_vach(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Trà xanh", "1111111111111"
    ).json()

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": "Trà xanh",
            "price": 50000,
            "category_id": ctx["category_id"],
            "barcode": "2222222222222",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["barcode"] == "2222222222222"


def test_sua_sp_khong_gui_barcode_thi_giu_nguyen(client):
    """Form cũ (chưa có ô mã vạch) không được vô tình xóa mã vạch đã gán."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Cà phê", "3333333333333"
    ).json()

    res = client.put(
        f"/api/products/{sp['id']}",
        data={"name": "Cà phê sữa", "price": 60000, "category_id": ctx["category_id"]},
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["barcode"] == "3333333333333"


def test_sua_sp_gui_barcode_rong_thi_xoa_ma(client):
    """Gán nhầm mã vạch phải sửa lại được bằng cách để trống ô."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Mì gói", "4444444444444"
    ).json()

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": "Mì gói",
            "price": 50000,
            "category_id": ctx["category_id"],
            "barcode": "",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["barcode"] is None


# ---------- Chống trùng ----------


def test_hai_sp_cung_shop_khong_duoc_trung_ma_vach(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP A", "5555555555555")
    res = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP B", "5555555555555"
    )
    assert res.status_code == 400
    # Báo rõ sản phẩm nào đang giữ mã, không chỉ "đã tồn tại".
    assert "SP A" in res.json()["detail"]


def test_trung_ma_vach_bat_ca_khi_khac_hoa_thuong(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP C", "kho-b2-007")
    res = _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP D", "KHO-B2-007")
    assert res.status_code == 400


def test_hai_shop_khac_nhau_duoc_dung_cung_ma_vach(client):
    """Mã vạch chỉ duy nhất trong phạm vi một shop, không phải toàn hệ thống."""
    ctx1 = seller_with_shop(client)
    _tao_sp(client, ctx1["token"], ctx1["shop_id"], ctx1["category_id"], "SP X", "6666666666666")

    _, token2 = new_seller(client)
    shop2 = create_shop(client, token2)
    cat2 = create_category(client, token2, shop2)
    res = _tao_sp(client, token2, shop2, cat2, "SP X", "6666666666666")
    assert res.status_code == 200, res.text


def test_nhieu_sp_cung_de_trong_ma_vach(client):
    """NULL không bị unique index chặn - phần lớn sản phẩm sẽ chưa có mã vạch."""
    ctx = seller_with_shop(client)
    assert _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP 1").status_code == 200
    assert _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP 2").status_code == 200
    assert _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP 3").status_code == 200


def test_sua_sp_giu_nguyen_ma_vach_cua_chinh_no(client):
    """Lưu lại form mà không đổi mã vạch không được báo trùng với chính nó."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP Y", "7777777777777"
    ).json()

    res = client.put(
        f"/api/products/{sp['id']}",
        data={
            "name": "SP Y đổi tên",
            "price": 70000,
            "category_id": ctx["category_id"],
            "barcode": "7777777777777",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text


def test_sua_sp_sang_ma_vach_cua_sp_khac_bi_chan(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP M", "8888888888888")
    sp2 = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP N", "9999999999999"
    ).json()

    res = client.put(
        f"/api/products/{sp2['id']}",
        data={
            "name": "SP N",
            "price": 50000,
            "category_id": ctx["category_id"],
            "barcode": "8888888888888",
        },
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 400
    assert "SP M" in res.json()["detail"]


# ---------- Tra cứu để quét ----------


def test_tra_cuu_theo_ma_vach(client):
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Sữa chua", "1234567890123"
    ).json()

    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/1234567890123", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == sp["id"]
    assert res.json()["name"] == "Sữa chua"


def test_tra_cuu_khong_phan_biet_hoa_thuong(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Xúc xích", "KHO-C3-012")

    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/kho-c3-012", headers=auth(ctx["token"])
    )
    assert res.status_code == 200, res.text


def test_tra_cuu_ma_khong_ton_tai_tra_404(client):
    ctx = seller_with_shop(client)
    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/0000000000009", headers=auth(ctx["token"])
    )
    assert res.status_code == 404


def test_tra_cuu_khong_thay_sp_da_an(client):
    """Quét trúng SP đã ẩn mà vẫn bán được thì việc ẩn sản phẩm là vô nghĩa."""
    ctx = seller_with_shop(client)
    sp = _tao_sp(
        client, ctx["token"], ctx["shop_id"], ctx["category_id"], "Hàng ẩn", "1010101010101"
    ).json()
    client.put(f"/api/products/{sp['id']}/status", headers=auth(ctx["token"]))

    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/1010101010101", headers=auth(ctx["token"])
    )
    assert res.status_code == 404


def test_tra_cuu_can_dang_nhap(client):
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP Auth", "1212121212121")

    res = client.get(f"/api/products/{ctx['shop_id']}/barcode/1212121212121")
    assert res.status_code == 401


def test_khong_tra_cuu_duoc_ma_vach_cua_shop_khac(client):
    """Seller shop A không được dò mã vạch trong shop B."""
    ctx1 = seller_with_shop(client)
    _tao_sp(client, ctx1["token"], ctx1["shop_id"], ctx1["category_id"], "SP riêng", "1313131313131")

    _, token2 = new_seller(client)
    res = client.get(
        f"/api/products/{ctx1['shop_id']}/barcode/1313131313131", headers=auth(token2)
    )
    assert res.status_code == 403


def test_nhan_vien_tra_cuu_duoc_ma_vach_shop_minh(client):
    """Nhân viên đứng quầy POS phải quét được, không chỉ chủ shop."""
    ctx = seller_with_shop(client)
    _tao_sp(client, ctx["token"], ctx["shop_id"], ctx["category_id"], "SP NV", "1414141414141")
    _, staff_token = new_staff(client, ctx)

    res = client.get(
        f"/api/products/{ctx['shop_id']}/barcode/1414141414141", headers=auth(staff_token)
    )
    assert res.status_code == 200, res.text


# ---------- Migration ----------


def test_unique_index_ma_vach_ton_tai(client, db):
    """Bảo vệ ràng buộc ở tầng DB.

    `run_migrations` cố tình nuốt lỗi để chạy lặp lại được, nên một lệnh CREATE
    UNIQUE INDEX thất bại sẽ trôi qua im lặng. Test này bắt đúng trường hợp đó.
    """
    assert bootstrap.verify_required_indexes(db) == []
