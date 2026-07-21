"""Upload ảnh: kiểm tra MIME, đuôi file, magic bytes, kích thước."""
import io
from pathlib import PurePosixPath

from conftest import auth, seller_with_shop

from fselling.services.catalog_service import is_valid_image

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def test_is_valid_image_nhan_dien_dung():
    assert is_valid_image(PNG_BYTES)
    assert is_valid_image(JPEG_BYTES)
    assert is_valid_image(WEBP_BYTES)
    assert not is_valid_image(b"<?php echo 1; ?>" + b"\x00" * 32)
    assert not is_valid_image(b"abc")


def _upload(client, ctx, filename, content, content_type, name="SP Anh"):
    return client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={"name": name, "price": 1000, "stock": 1, "category_id": ctx["category_id"]},
        files={"image": (filename, io.BytesIO(content), content_type)},
        headers=auth(ctx["token"]),
    )


def test_upload_anh_png_hop_le(client):
    ctx = seller_with_shop(client)
    res = _upload(client, ctx, "a.png", PNG_BYTES, "image/png", name="SP PNG")
    assert res.status_code == 200
    assert res.json()["image_url"].startswith("/uploads/")
    # Tên file được sinh bằng UUID, không dùng tên gốc
    assert PurePosixPath(res.json()["image_url"]).name != "a.png"


def test_tu_choi_mime_khong_hop_le(client):
    ctx = seller_with_shop(client)
    res = _upload(client, ctx, "a.php", b"x" * 32, "application/x-php", name="SP PHP")
    assert res.status_code == 400


def test_tu_choi_duoi_file_khong_hop_le(client):
    ctx = seller_with_shop(client)
    res = _upload(client, ctx, "a.svg", PNG_BYTES, "image/png", name="SP SVG")
    assert res.status_code == 400


def test_tu_choi_file_gia_dang_anh(client):
    ctx = seller_with_shop(client)
    res = _upload(client, ctx, "fake.png", b"<script>alert(1)</script>" * 4, "image/png", name="SP Fake")
    assert res.status_code == 400
    assert "không phải ảnh" in res.json()["detail"]


def test_tu_choi_file_qua_lon(client):
    ctx = seller_with_shop(client)
    big = PNG_BYTES + b"\x00" * (2 * 1024 * 1024 + 1)
    res = _upload(client, ctx, "big.png", big, "image/png", name="SP Big")
    assert res.status_code == 400
    assert "quá lớn" in res.json()["detail"]


def test_khong_upload_thi_dung_anh_mac_dinh(client):
    ctx = seller_with_shop(client)
    assert ctx["product"]["image_url"].startswith("https://placehold.co")
