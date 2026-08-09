"""L5: giọng nói cho tab Trợ Lý.

Test hồi quy mã nguồn. Nó KHÔNG thay cho bước mở trình duyệt thật - không có
cách nào bấm micro từ pytest - nhưng nó khóa được đúng những chỗ đã trả giá:
nút bấm vào không ra gì, và bộ đọc phát ra một tràng "chấm không không không".
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _function(js: str, start: str, end: str) -> str:
    begin = js.index(start)
    return js[begin:js.index(end, begin)]


def test_nut_mic_mac_dinh_AN_va_chi_hien_khi_that_su_nghe_duoc():
    """Firefox và webview Zalo/Facebook không nghe được.

    Để một cái nút bấm vào không ra gì còn tệ hơn là không có nút - CLAUDE.md
    đã ghi đúng bài học này ở phần `confirm()` bị Chrome chặn.
    """
    html = _read("static/seller.html")
    js = _read("static/js/seller.js")

    vi_tri = html.index('id="assistantMic"')
    assert "display:none" in html[vi_tri:vi_tri + 260], "nút mic phải ẩn sẵn trong HTML"

    kiem_tra = _function(js, "function ngheDuocKhong()", "function docTraLoiDangBat()")
    # Trang chạy http trên IP LAN thì Chrome chặn mic; nút sẽ bấm mãi không ra gì.
    assert "isSecureContext" in kiem_tra
    assert "webkitSpeechRecognition" in kiem_tra

    khoi_tao = _function(js, "function khoiTaoGiongNoiTroLy()", "function batTatNgheTroLy()")
    assert "ngheDuocKhong() ? '' : 'none'" in khoi_tao


def test_chi_nghe_mot_cau_roi_dung():
    """`continuous = true` là micro mở suốt buổi bán hàng."""
    js = _read("static/js/seller.js")
    nghe = _function(js, "function batTatNgheTroLy()", "/** Đổi số tiền sang CHỮ")

    assert "boNghe.lang = 'vi-VN'" in nghe
    assert "boNghe.continuous = false" in nghe
    assert "boNghe.interimResults = false" in nghe


def test_moi_loi_micro_deu_co_cau_noi_rieng():
    """Người dùng chặn micro rồi bấm mãi không hiểu vì sao là ca hay gặp nhất."""
    js = _read("static/js/seller.js")
    locale = _read("static/js/locales/seller.js")
    nghe = _function(js, "function batTatNgheTroLy()", "/** Đổi số tiền sang CHỮ")

    assert "'not-allowed'" in nghe and "'no-speech'" in nghe
    # Người dùng tự bấm dừng thì đừng la họ.
    assert "e.error === 'aborted'" in nghe

    for khoa in (
        "seller.assistant.mic_denied",
        "seller.assistant.mic_no_speech",
        "seller.assistant.mic_failed",
        "seller.assistant.mic_unsupported",
        "seller.assistant.no_voice",
        "seller.assistant.listening",
        "seller.assistant.read_aloud",
    ):
        assert locale.count(f"'{khoa}':") == 2, f"{khoa} phải có cả tiếng Việt và tiếng Anh"

    # Câu báo lỗi micro phải chỉ ra đường thoát cho người mở link trong Zalo.
    assert "Zalo" in locale


def test_doc_tien_bang_CHU_chu_khong_doc_dau_cham():
    """Bộ đọc gặp "3.740.500đ" sẽ đọc "ba chấm bảy bốn không..." - bài học đã
    ghi sẵn trong doc-tien.js, đừng lặp lại nó ở màn khác."""
    js = _read("static/js/seller.js")
    doi = _function(js, "function docDuocCauTraLoi(chu)", "// ===== L2: xả hàng tồn")

    assert "DocTien.docSo" in doi
    assert "' đồng'" in doi
    # CHỈ đổi cụm có đuôi "đ". Các số khác trong câu ("còn đủ bán 0.6 ngày")
    # dùng dấu chấm làm dấu THẬP PHÂN - đổi luôn là đọc sai theo hướng ngược lại.
    assert "đ/g" in doi, "biểu thức phải neo vào ký tự 'đ' của tiền"


def test_dung_lai_bo_doc_cua_POS_thay_vi_viet_moi():
    """`DocTien.noi()` đã xử lý: máy có giọng Việt thì đọc tại chỗ, không có thì
    nhờ server, không cấu hình server thì im lặng. Viết lại là đẻ ra bản sao sẽ
    lệch dần."""
    html = _read("static/seller.html")
    js = _read("static/js/seller.js")

    assert "/js/doc-tien.js" in html, "seller.html phải nạp doc-tien.js"
    assert "DocTien?.noi?.(" in js
    # Không được tự gọi thẳng speechSynthesis ở seller.js - đó là đường vòng qua
    # phần chọn giọng tiếng Việt mà doc-tien.js đã làm đúng.
    assert "new SpeechSynthesisUtterance" not in js
    assert "speechSynthesis.speak" not in js


def test_bao_truoc_khi_may_khong_co_giong_tieng_viet():
    """Chrome trên Windows không có giọng Việt. Bật "đọc câu trả lời" rồi ngồi
    chờ trong im lặng mà không hiểu vì sao là trải nghiệm tệ nhất."""
    js = _read("static/js/seller.js")
    ghi_chu = _function(js, "async function capNhatGhiChuGiong()", "function khoiTaoGiongNoiTroLy()")

    assert "giongTiengViet" in ghi_chu
    assert "kiemTraServer" in ghi_chu
    assert "seller.assistant.no_voice" in ghi_chu


def test_cho_danh_sach_giong_nap_xong_moi_ket_luan():
    """`getVoices()` thường trả RỖNG ở lần gọi đầu rồi mới nạp xong sau.

    Không chờ `voiceschanged` thì dòng ghi chú khẳng định "máy chưa có giọng
    tiếng Việt" trên đúng cái máy đang có - nói sai về máy của người dùng còn tệ
    hơn là không nói gì.
    """
    js = _read("static/js/seller.js")
    khoi_tao = _function(js, "function khoiTaoGiongNoiTroLy()", "function batTatNgheTroLy()")

    assert "voiceschanged" in khoi_tao
    assert "capNhatGhiChuGiong" in khoi_tao
    # Chỉ gắn MỘT lần: mở đi mở lại tab mà cứ gắn thêm là mỗi lần nạp giọng
    # chạy hàng chục lần cập nhật.
    assert "daNgheDoiGiong" in khoi_tao


def test_lua_chon_doc_to_duoc_nho_lai():
    js = _read("static/js/seller.js")
    assert "KHOA_DOC_TRA_LOI = 'troLy.doc'" in js
    assert "localStorage.setItem(KHOA_DOC_TRA_LOI" in js
    # Mặc định TẮT: một cái máy bỗng nói oang oang giữa tiệm là chuyện phải do
    # chủ shop chủ động bật.
    doc_bat = _function(js, "function docTraLoiDangBat()", "function doiDocTraLoi()")
    assert "=== '1'" in doc_bat
