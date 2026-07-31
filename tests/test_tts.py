"""D3: endpoint sinh giọng đọc tiếng Việt phía server.

Đây là TẦNG DỰ PHÒNG cho máy không có sẵn giọng Việt. Chưa cấu hình nhà cung
cấp thì phải trả 503 rõ ràng để frontend lùi về giọng thiết bị, không được vỡ.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from conftest import auth, new_seller
from fselling.services import tts_service


def _token(client):
    return new_seller(client)[1]


# ---------- Chưa cấu hình ----------


def test_chua_cau_hinh_thi_status_bao_tat(client):
    res = client.get("/api/tts/status", headers=auth(_token(client)))
    assert res.status_code == 200
    assert res.json() == {"enabled": False}


def test_chua_cau_hinh_thi_tra_503(client):
    res = client.post("/api/tts", json={"text": "Đã nhận một trăm nghìn đồng"},
                      headers=auth(_token(client)))
    assert res.status_code == 503
    assert "chưa cấu hình" in res.json()["detail"].lower()


# ---------- Phân quyền ----------


def test_can_dang_nhap(client):
    assert client.post("/api/tts", json={"text": "xin chào"}).status_code == 401
    assert client.get("/api/tts/status").status_code == 401


# ---------- Giới hạn đầu vào ----------


def test_noi_dung_rong_bi_tu_choi(client):
    res = client.post("/api/tts", json={"text": "   "}, headers=auth(_token(client)))
    assert res.status_code == 400


def test_noi_dung_qua_dai_bi_tu_choi(client):
    """Endpoint tiêu hạn mức trả phí, không để ai biến thành máy đọc sách."""
    res = client.post("/api/tts", json={"text": "a" * 1000}, headers=auth(_token(client)))
    assert res.status_code == 400
    assert "quá dài" in res.json()["detail"]


def test_chan_do_dai_TRUOC_khi_kiem_cau_hinh(client, monkeypatch):
    """Chuỗi dài phải bị chặn ngay, kể cả khi server đã cấu hình nhà cung cấp."""
    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "google")
    monkeypatch.setattr(tts_service, "TTS_API_KEY", "key-gia")
    res = client.post("/api/tts", json={"text": "a" * 1000}, headers=auth(_token(client)))
    assert res.status_code == 400


# ---------- Có cấu hình: dùng nhà cung cấp giả ----------


@pytest.fixture
def nha_cung_cap_gia(monkeypatch, tmp_path):
    """Giả lập một nhà cung cấp trả về mp3 cố định, đếm số lần bị gọi."""
    dem = {"so_lan": 0}

    def _gia(text):
        dem["so_lan"] += 1
        return b"ID3-mp3-gia-" + text.encode("utf-8")[:10]

    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "gia")
    monkeypatch.setattr(tts_service, "TTS_API_KEY", "key-gia")
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path / "tts_cache"))
    monkeypatch.setitem(tts_service._BO_CHUYEN_DOI, "gia", _gia)
    return dem


def test_tra_ve_mp3(client, nha_cung_cap_gia):
    res = client.post(
        "/api/tts",
        json={"text": "Đã nhận năm nghìn đồng"},
        headers={**auth(_token(client)), "Accept-Language": "en"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.headers["content-language"] == "vi"
    assert res.content.startswith(b"ID3-mp3-gia-")
    assert nha_cung_cap_gia["so_lan"] == 1


def test_lan_hai_lay_tu_cache_khong_goi_lai(client, nha_cung_cap_gia):
    """Cửa hàng bán quanh vài mức giá quen, cùng một câu lặp rất nhiều lần."""
    tok = _token(client)
    cau = {"text": "Đã nhận sáu nghìn đồng, đơn hàng số ba"}

    r1 = client.post("/api/tts", json=cau, headers=auth(tok))
    r2 = client.post("/api/tts", json=cau, headers=auth(tok))

    assert r1.headers["X-TTS-Cache"] == "miss"
    assert r2.headers["X-TTS-Cache"] == "hit"
    assert r1.content == r2.content
    assert nha_cung_cap_gia["so_lan"] == 1      # chỉ gọi nhà cung cấp đúng 1 lần


def test_cau_khac_nhau_thi_goi_lai(client, nha_cung_cap_gia):
    tok = _token(client)
    client.post("/api/tts", json={"text": "câu một"}, headers=auth(tok))
    client.post("/api/tts", json={"text": "câu hai"}, headers=auth(tok))
    assert nha_cung_cap_gia["so_lan"] == 2


def test_status_bao_bat_khi_da_cau_hinh(client, nha_cung_cap_gia):
    res = client.get("/api/tts/status", headers=auth(_token(client)))
    assert res.json() == {"enabled": True}


def test_nha_cung_cap_la_thi_bao_503(client, monkeypatch, tmp_path):
    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "khong-ton-tai")
    monkeypatch.setattr(tts_service, "TTS_API_KEY", "key")
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path))
    res = client.post("/api/tts", json={"text": "abc"}, headers=auth(_token(client)))
    assert res.status_code == 503


def test_azure_thieu_region_bi_chan(client, monkeypatch, tmp_path):
    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "azure")
    monkeypatch.setattr(tts_service, "TTS_API_KEY", "key")
    monkeypatch.setattr(tts_service, "TTS_AZURE_REGION", "")
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path))
    res = client.post("/api/tts", json={"text": "abc"}, headers=auth(_token(client)))
    assert res.status_code == 503
    assert "TTS_AZURE_REGION" in res.json()["detail"]


def test_nha_cung_cap_loi_thi_tra_502(client, monkeypatch, tmp_path):
    import urllib.error

    def _no(text):
        raise urllib.error.URLError("mat mang")

    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "gia")
    monkeypatch.setattr(tts_service, "TTS_API_KEY", "key")
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setitem(tts_service._BO_CHUYEN_DOI, "gia", _no)

    res = client.post("/api/tts", json={"text": "abc"}, headers=auth(_token(client)))
    assert res.status_code == 502


# ---------- Khóa cache ----------


def test_khoa_cache_tach_theo_giong(monkeypatch, tmp_path):
    """Đổi giọng phải ra file khác, không phát nhầm bản ghi của giọng cũ."""
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "google")

    monkeypatch.setattr(tts_service, "TTS_VOICE", "giong-A")
    a = tts_service._duong_dan_cache("xin chào")
    monkeypatch.setattr(tts_service, "TTS_VOICE", "giong-B")
    b = tts_service._duong_dan_cache("xin chào")
    assert a != b


def test_khoa_cache_tach_theo_nha_cung_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_service, "TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(tts_service, "TTS_VOICE", "")

    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "google")
    a = tts_service._duong_dan_cache("xin chào")
    monkeypatch.setattr(tts_service, "TTS_PROVIDER", "azure")
    b = tts_service._duong_dan_cache("xin chào")
    assert a != b


def test_thoat_xml_cho_ssml():
    """Nội dung lọt vào SSML phải được thoát, tránh vỡ cú pháp XML."""
    assert tts_service._thoat_xml("a & b <c>") == "a &amp; b &lt;c&gt;"
