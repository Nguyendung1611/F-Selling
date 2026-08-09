"""Gọi Gemini để PHÂN LOẠI câu hỏi. Không bao giờ để nó sinh câu lệnh hay số.

Đây là tầng dự phòng duy nhất của `assistant_service`: chỉ chạy khi bộ so khớp
mẫu tại máy chủ chịu thua. Việc của Gemini gói gọn trong một câu: *câu hỏi này
ứng với báo cáo nào, và khoảng thời gian nào*. Nó trả về hai chữ, không hơn.

**Vì sao chỉ giao ngần đó:**

- Nó KHÔNG thấy dữ liệu cửa hàng. Không doanh thu, không giá vốn, không tên
  khách, không tên hàng lấy từ kho. Chỉ có câu người dùng vừa gõ và danh sách
  tên báo cáo cố định. Gói miễn phí của Google được phép dùng dữ liệu gửi lên
  để cải thiện sản phẩm - nên thứ duy nhất gửi lên phải là thứ mất cũng không sao.
- Prompt vì vậy chỉ ~200 token thay vì ~2.000 nếu phải kèm cấu trúc cơ sở dữ
  liệu. Hạn mức miễn phí của Google chặn ở SỐ LƯỢT chứ không ở token, nhưng
  prompt nhỏ vẫn giữ độ trễ thấp và hóa đơn bằng 0 nếu sau này chuyển sang trả phí.
- Câu trả lời bị ép nằm trong danh sách cho trước. Ai gõ "bỏ qua chỉ dẫn trên
  và..." thì tệ nhất là chọn nhầm báo cáo - không có đường nào để bịa ra một
  con số. Giá trị lạ = coi như không hiểu.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional, Sequence, Tuple

from ..core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
    log_to_file,
)

_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# Chỉ cần đủ chỗ cho {"y_dinh":"...","khoang":"..."}. Chặn ở đây là chặn cứng:
# model có "nói nhiều" cỡ nào cũng không tiêu quá ngần này token đầu ra.
_TOI_DA_TOKEN_RA = 40


def dang_bat() -> bool:
    return bool(GEMINI_API_KEY)


def _prompt(cau_hoi: str, y_dinh_hop_le: Sequence[str], khoang_hop_le: Sequence[str]) -> str:
    """Prompt cố ý NGẮN và không có ví dụ dài dòng.

    Mỗi ví dụ thêm vào là token nhân với mọi lượt gọi về sau. Danh sách tên báo
    cáo đã đủ tự mô tả; câu nào mơ hồ thì để model trả KHONG_HIEU còn hơn ép nó
    đoán bằng cách nhồi thêm ví dụ.
    """
    return (
        "Bạn phân loại câu hỏi của chủ tiệm tạp hóa Việt Nam. "
        "Chỉ trả về JSON, không giải thích.\n"
        f'y_dinh phải là một trong: {", ".join(y_dinh_hop_le)}\n'
        f'khoang phải là một trong: {", ".join(khoang_hop_le)}\n'
        "Không chắc thì trả y_dinh=KHONG_HIEU.\n"
        f'Câu hỏi: "{cau_hoi}"\n'
        'Trả về: {"y_dinh":"...","khoang":"..."}'
    )


def phan_loai(
    cau_hoi: str,
    y_dinh_hop_le: Sequence[str],
    khoang_hop_le: Sequence[str],
) -> Optional[Tuple[str, str]]:
    """Trả (y_dinh, khoang) hoặc None nếu không dùng được.

    None ở đây gộp mọi ca hỏng - chưa cắm key, mạng lỗi, Google trả rác, model
    bịa ra một cái tên không có trong danh sách. Người dùng nhận đúng một câu
    "chưa hiểu" như khi tính năng chưa bật, chứ không nhận một thông báo lỗi kỹ
    thuật mà họ không làm gì được.
    """
    if not dang_bat():
        return None

    than = json.dumps(
        {
            "contents": [
                {"parts": [{"text": _prompt(cau_hoi, y_dinh_hop_le, khoang_hop_le)}]}
            ],
            "generationConfig": {
                "temperature": 0,          # phân loại, không sáng tác
                "maxOutputTokens": _TOI_DA_TOKEN_RA,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        _URL.format(model=GEMINI_MODEL),
        data=than,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        method="POST",
    )
    try:
        # KHÔNG thử lại khi hỏng: retry là nhân đôi lượt gọi cho một người vốn
        # đã đang chờ, mà lượt gọi mới là thứ hạn mức Google đếm.
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as loi:
        log_to_file(f"[TRO LY] Gemini khong tra loi duoc: {type(loi).__name__}")
        return None

    try:
        chu = payload["candidates"][0]["content"]["parts"][0]["text"]
        ket = json.loads(chu)
        y_dinh = str(ket.get("y_dinh") or "").strip().upper()
        khoang = str(ket.get("khoang") or "").strip().upper()
    except (KeyError, IndexError, TypeError, ValueError):
        log_to_file("[TRO LY] Gemini tra ve dinh dang la")
        return None

    # Hàng rào cuối: chỉ nhận giá trị CÓ THẬT trong danh sách. Model bịa ra
    # "DOANH_THU_THEO_QUY" thì ở đây rơi về không hiểu, không có đường nào đi
    # tiếp thành một câu trả lời trông như thật.
    if y_dinh not in y_dinh_hop_le:
        return None
    if khoang not in khoang_hop_le:
        khoang = ""
    return y_dinh, khoang
