"""Bộ MP3 ghép câu phải luôn đi cùng logic đọc tiền ở frontend."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "static" / "audio"

REQUIRED_AUDIO = {
    "da_nhan.mp3", "tai_khoan.mp3", "thanh_cong.mp3",
    "canh_bao_thieu_tien.mp3",
    "con_thieu.mp3", "chuyen_thua.mp3", "can_hoan_lai.mp3",
    "0.mp3", "1.mp3", "2.mp3", "3.mp3", "4.mp3",
    "5.mp3", "6.mp3", "7.mp3", "8.mp3", "9.mp3",
    "muoi_10.mp3", "muoi_tens.mp3", "lam.mp3", "mot_mot.mp3",
    "tu.mp3", "le.mp3", "tram.mp3", "nghin.mp3", "trieu.mp3",
    "ty.mp3", "dong.mp3",
}


def test_du_28_file_mp3_doc_tien():
    assert {p.name for p in AUDIO_DIR.glob("*.mp3")} == REQUIRED_AUDIO


def test_cac_file_co_du_lieu_mp3_hop_le():
    for name in REQUIRED_AUDIO:
        data = (AUDIO_DIR / name).read_bytes()
        assert len(data) > 500, f"{name} rỗng hoặc bị cắt"
        assert data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}, (
            f"{name} không có header MP3"
        )


def test_pos_nap_truoc_va_doc_bo_mp3_khi_paid():
    doc_tien = (ROOT / "static" / "js" / "doc-tien.js").read_text(encoding="utf-8")
    pos = (ROOT / "static" / "js" / "pos.js").read_text(encoding="utf-8")
    seller = (ROOT / "static" / "seller.html").read_text(encoding="utf-8")
    pos_html = (ROOT / "static" / "pos.html").read_text(encoding="utf-8")

    assert "function tepDocSoTien(soTien)" in doc_tien
    assert "Promise.all(tep.map(taiTep))" in doc_tien
    assert "return noiSoTien(soTien, cauDaNhan(soTien, orderId));" in doc_tien
    assert "DocTien.chuanBiSoTien(res.total);" in pos
    assert "DocTien.thongBaoDaNhan(" in pos
    assert "DocTien.canhBaoThieuTien(" in pos
    assert "DocTien.canhBaoThuaTien(" in pos
    assert "TEP_CON_THIEU" in doc_tien
    assert "TEP_CHUYEN_THUA" in doc_tien
    assert "TEP_CAN_HOAN_LAI" in doc_tien
    assert "if (!ok) noiBangThietBi(cauChu)" not in doc_tien
    assert "confirmPayment" not in pos
    assert "Xác nhận Đã Nhận Tiền" not in pos_html
    assert 'id="dtGiong"' not in seller
    assert "DocTien.thuDuTien()" in seller
    assert "DocTien.thuThieuTien()" in seller
    assert "DocTien.thuThuaTien()" in seller
