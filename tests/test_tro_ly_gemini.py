"""L4: tầng dự phòng Gemini của trợ lý, và các lớp chặn hao hạn mức.

Mọi test ở đây đều THAY Gemini bằng hàm giả. Không test nào được gọi ra mạng:
gọi thật thì test phụ thuộc vào một dịch vụ ngoài, tốn hạn mức của chủ dự án, và
đỏ vào đúng hôm Google chậm.
"""
import time

import pytest
from conftest import auth, new_staff, seller_with_shop

from fselling import models
from fselling.core import thoi_gian
from fselling.core.database import SessionLocal
from fselling.services import assistant_service, gemini_service, subscription_service

CAU_LA = "bữa giờ tiệm làm ăn ra sao"


@pytest.fixture(autouse=True)
def _don_bo_nho():
    """Cache và bộ đếm phút nằm trong RAM nên phải dọn giữa các test."""
    assistant_service._NHO_CAU_HOI.clear()
    assistant_service._DAU_VET_PHUT.clear()
    yield
    assistant_service._NHO_CAU_HOI.clear()
    assistant_service._DAU_VET_PHUT.clear()


@pytest.fixture
def gemini_gia(monkeypatch):
    """Gemini giả: đếm số lượt bị gọi và luôn trả DOANH_THU/THANG_TRUOC."""
    dem = {"so_lan": 0}

    def _phan_loai(cau_hoi, y_dinh_hop_le, khoang_hop_le):
        dem["so_lan"] += 1
        return ("DOANH_THU", "THANG_TRUOC")

    monkeypatch.setattr(gemini_service, "dang_bat", lambda: True)
    monkeypatch.setattr(gemini_service, "phan_loai", _phan_loai)
    return dem


@pytest.fixture
def shop_pro(client, monkeypatch):
    """Shop đã bật Pro (tầng dự phòng AI là tính năng Pro)."""
    ctx_full = seller_with_shop(client)
    monkeypatch.setattr(subscription_service, "require_pro", lambda db, shop_id, **k: {})
    return {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"], "_full": ctx_full}


def _hoi(client, ctx, cau):
    return client.post(
        f"/api/assistant/{ctx['shop_id']}", json={"cau_hoi": cau}, headers=auth(ctx["token"])
    )


def test_bo_test_khong_bao_gio_goi_gemini_that():
    """Máy dev có `GEMINI_API_KEY` trong `.env` thật.

    `conftest` phải xóa biến đó, nếu không mỗi lần chạy test là tiêu hạn mức
    miễn phí của chủ dự án, và bộ test đỏ ngẫu nhiên vào đúng hôm Google chậm
    hoặc đổi model. Đã dính đúng lỗi này một lần, ngay hôm cắm khóa.
    """
    import os

    assert os.environ.get("GEMINI_API_KEY") == ""
    assert gemini_service.dang_bat() is False


# ---------- Lớp 1: chưa cắm key thì tính năng không tồn tại ----------
def test_chua_cam_key_thi_khong_goi_gi_va_app_chay_nhu_cu(client, monkeypatch):
    goi = {"so_lan": 0}

    def _khong_duoc_goi(*a, **k):
        goi["so_lan"] += 1
        raise AssertionError("Chưa cắm key mà vẫn gọi ra Google")

    monkeypatch.setattr(gemini_service, "phan_loai", _khong_duoc_goi)
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}

    body = _hoi(client, ctx, CAU_LA).json()
    assert body["hieu_duoc"] is False
    assert goi["so_lan"] == 0


# ---------- Lớp mạnh nhất: câu thường gặp không bao giờ chạm Gemini ----------
def test_cau_thuong_gap_khong_ton_luot_nao(client, gemini_gia, shop_pro):
    for cau in ("Hôm nay bán được bao nhiêu?", "Cần nhập hàng gì?", "Hàng nào đang nằm ế?"):
        assert _hoi(client, shop_pro, cau).status_code == 200
    assert gemini_gia["so_lan"] == 0, "câu bộ so khớp nội bộ hiểu được thì không được gọi AI"

    session = SessionLocal()
    try:
        da_dung, _ = assistant_service._con_han_muc(session, shop_pro["shop_id"])
        assert da_dung == 0
    finally:
        session.close()


def test_cau_la_thi_moi_goi_va_tra_loi_dung_khoang_ai_chon(client, gemini_gia, shop_pro):
    body = _hoi(client, shop_pro, CAU_LA).json()

    assert gemini_gia["so_lan"] == 1
    assert body["hieu_duoc"] is True
    assert body["y_dinh"] == assistant_service.Y_DINH_DOANH_THU
    assert body["dung_ai"] is True
    # Gemini chọn THANG_TRUOC nên câu trả lời phải nói về tháng trước.
    assert "tháng trước" in body["tra_loi"].lower()


# ---------- Lớp: nhớ câu đã hỏi ----------
def test_hoi_lai_y_het_thi_khong_ton_them_luot(client, gemini_gia, shop_pro):
    _hoi(client, shop_pro, CAU_LA)
    _hoi(client, shop_pro, CAU_LA)
    _hoi(client, shop_pro, CAU_LA.upper())      # khác hoa thường vẫn là một câu

    assert gemini_gia["so_lan"] == 1


# ---------- Lớp: trần mỗi ngày, đếm trong DB ----------
def test_het_tran_ngay_thi_ngung_goi(client, gemini_gia, shop_pro, monkeypatch):
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_NGAY", 3)
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_PHUT", 99)

    for i in range(6):
        _hoi(client, shop_pro, f"{CAU_LA} lan thu {i}")

    assert gemini_gia["so_lan"] == 3, "phải dừng đúng ở trần"

    session = SessionLocal()
    try:
        da_dung, _ = assistant_service._con_han_muc(session, shop_pro["shop_id"])
        assert da_dung == 3
    finally:
        session.close()


def test_bo_dem_nam_trong_db_nen_restart_khong_reset(client, gemini_gia, shop_pro, monkeypatch):
    """Bộ đếm trong RAM thì khởi động lại là hạn mức về 0 - mà restart thì ép
    được. Cùng bài học với bộ đếm chống dò mật khẩu (mục 17)."""
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_NGAY", 2)
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_PHUT", 99)
    for i in range(2):
        _hoi(client, shop_pro, f"{CAU_LA} {i}")

    # Giả lập restart: xóa sạch mọi thứ đang nằm trong bộ nhớ tiến trình.
    assistant_service._NHO_CAU_HOI.clear()
    assistant_service._DAU_VET_PHUT.clear()

    _hoi(client, shop_pro, f"{CAU_LA} sau khi restart")
    assert gemini_gia["so_lan"] == 2, "hạn mức phải sống sót qua restart"


def test_tran_dem_rieng_tung_shop(client, gemini_gia, monkeypatch):
    """Một tiệm đốt hết phần của mình không được kéo tiệm khác xuống theo."""
    monkeypatch.setattr(subscription_service, "require_pro", lambda db, shop_id, **k: {})
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_NGAY", 1)
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_PHUT", 99)

    a = seller_with_shop(client)
    b = seller_with_shop(client)
    ctx_a = {"shop_id": a["shop_id"], "token": a["token"]}
    ctx_b = {"shop_id": b["shop_id"], "token": b["token"]}

    _hoi(client, ctx_a, f"{CAU_LA} 1")
    _hoi(client, ctx_a, f"{CAU_LA} 2")          # shop A đã hết trần
    _hoi(client, ctx_b, f"{CAU_LA} 3")          # shop B vẫn còn nguyên

    assert gemini_gia["so_lan"] == 2


# ---------- Lớp: chống bấm dồn ----------
def test_giu_enter_khong_dot_het_han_muc(client, gemini_gia, shop_pro, monkeypatch):
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_PHUT", 2)
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_NGAY", 99)

    for i in range(8):
        _hoi(client, shop_pro, f"{CAU_LA} lan {i}")

    assert gemini_gia["so_lan"] == 2


# ---------- Lớp: chỉ gói Pro ----------
def test_shop_free_khong_dung_tang_du_phong(client, gemini_gia):
    """Không monkeypatch require_pro: shop mới tạo hết trial là Free."""
    ctx_full = seller_with_shop(client)
    ctx = {"shop_id": ctx_full["shop_id"], "token": ctx_full["token"]}

    session = SessionLocal()
    try:
        # Hạ shop về Free bằng cách xóa mọi quyền lợi Pro đang có.
        session.query(models.ShopSubscription).filter(
            models.ShopSubscription.shop_id == ctx["shop_id"]
        ).delete()
        session.commit()
    finally:
        session.close()

    body = _hoi(client, ctx, CAU_LA).json()
    assert body["hieu_duoc"] is False
    assert gemini_gia["so_lan"] == 0


# ---------- Lớp: chặn rác trước khi tốn lượt ----------
def test_chuoi_rac_khong_ton_luot(client, gemini_gia, shop_pro):
    for rac in ("???", "123456", "🙂🙂", "%%%%"):
        _hoi(client, shop_pro, rac)
    assert gemini_gia["so_lan"] == 0


# ---------- Hàng rào cuối: giá trị lạ từ AI bị chặn ----------
def test_ai_bia_ra_bao_cao_khong_co_that_thi_coi_nhu_chua_hieu(client, shop_pro, monkeypatch):
    monkeypatch.setattr(gemini_service, "dang_bat", lambda: True)
    monkeypatch.setattr(
        gemini_service, "phan_loai",
        lambda *a, **k: None,      # gemini_service đã loại giá trị lạ, trả None
    )
    body = _hoi(client, shop_pro, CAU_LA).json()
    assert body["hieu_duoc"] is False


def test_gemini_service_loai_gia_tri_ngoai_danh_sach(monkeypatch):
    """Kiểm thẳng hàng rào trong gemini_service, không qua HTTP."""
    import json as _json

    class _GiaResponse:
        def __init__(self, chu):
            self._chu = chu

        def read(self):
            return _json.dumps(
                {"candidates": [{"content": {"parts": [{"text": self._chu}]}}]}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "khoa-gia")
    monkeypatch.setattr(gemini_service, "dang_bat", lambda: True)

    def _tra(chu):
        monkeypatch.setattr(
            gemini_service.urllib.request, "urlopen",
            lambda req, timeout=None: _GiaResponse(chu),
        )
        return gemini_service.phan_loai(
            "abc", ["DOANH_THU", "SO_DON"], ["HOM_NAY", "THANG_TRUOC"]
        )

    assert _tra('{"y_dinh":"DOANH_THU","khoang":"HOM_NAY"}') == ("DOANH_THU", "HOM_NAY")
    # Báo cáo bịa ra -> None, không có đường nào đi tiếp thành câu trả lời thật.
    assert _tra('{"y_dinh":"DOANH_THU_THEO_QUY","khoang":"HOM_NAY"}') is None
    # Khoảng thời gian lạ -> bỏ khoảng, giữ báo cáo (rơi về mặc định).
    assert _tra('{"y_dinh":"SO_DON","khoang":"THE_KY_NAY"}') == ("SO_DON", "")
    # Không phải JSON -> None.
    assert _tra("xin chao") is None


def test_gemini_treo_thi_tra_loi_chua_hieu_chu_khong_vo(monkeypatch):
    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "khoa-gia")
    monkeypatch.setattr(gemini_service, "dang_bat", lambda: True)

    def _treo(req, timeout=None):
        raise TimeoutError("qua gio")

    monkeypatch.setattr(gemini_service.urllib.request, "urlopen", _treo)
    assert gemini_service.phan_loai("abc", ["DOANH_THU"], ["HOM_NAY"]) is None


def test_prompt_khong_chua_du_lieu_cua_hang():
    """Thứ duy nhất gửi ra ngoài là câu hỏi + tên báo cáo.

    Gói miễn phí của Google được phép dùng dữ liệu gửi lên để cải thiện sản
    phẩm, nên phải chắc chắn không có con số nào của cửa hàng đi kèm.
    """
    prompt = gemini_service._prompt(
        "thang roi lai bao nhieu", ["DOANH_THU", "LAI"], ["HOM_NAY", "THANG_TRUOC"]
    )
    assert "thang roi lai bao nhieu" in prompt
    assert "DOANH_THU" in prompt
    # Prompt phải NGẮN: mỗi chữ thêm vào là token nhân với mọi lượt gọi về sau.
    assert len(prompt) < 700, len(prompt)
