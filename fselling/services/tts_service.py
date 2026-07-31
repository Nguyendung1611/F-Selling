"""Sinh giọng đọc tiếng Việt ở phía server.

Chỉ là TẦNG DỰ PHÒNG. Máy nào đã có sẵn giọng tiếng Việt thì frontend tự đọc
bằng `SpeechSynthesis` - nhanh hơn, không tốn lượt gọi, không cần mạng. Server
chỉ vào cuộc khi thiết bị không có giọng Việt nào (thường là Chrome trên
Windows: bộ giọng Google kèm theo Chrome không có tiếng Việt).

Chưa cấu hình nhà cung cấp thì `tao_audio` ném 503 và frontend im lặng lùi về
giọng thiết bị - app không vỡ, chỉ là đọc bằng giọng nước ngoài.

LƯU Ý: hai bộ chuyển đổi bên dưới viết theo tài liệu REST của Google và Azure
nhưng CHƯA gọi thử bằng key thật. Lần đầu cắm key nên bấm "Thử giọng" để xác
nhận, và xem `request_log.txt` nếu có lỗi.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Tuple

from fastapi import HTTPException

from ..core.config import (
    TTS_API_KEY,
    TTS_AZURE_REGION,
    TTS_CACHE_DIR,
    TTS_MAX_CHARS,
    TTS_PROVIDER,
    TTS_VOICE,
    log_to_file,
)
from ..core.i18n import tr

_TIMEOUT = 15


def dang_bat() -> bool:
    return bool(TTS_PROVIDER and TTS_API_KEY)


def _kiem_tra_cau_hinh() -> None:
    if not dang_bat():
        raise HTTPException(
            status_code=503,
            detail=tr(
                "Server chưa cấu hình giọng đọc (thiếu TTS_PROVIDER/TTS_API_KEY)"
            ),
        )
    if TTS_PROVIDER == "azure" and not TTS_AZURE_REGION:
        raise HTTPException(
            status_code=503,
            detail=tr("Azure cần TTS_AZURE_REGION (ví dụ: southeastasia)"),
        )


def _duong_dan_cache(text: str) -> str:
    """Tên file theo nội dung + nhà cung cấp + giọng.

    Cùng một câu được đọc đi đọc lại rất nhiều (cửa hàng bán quanh vài mức giá
    quen thuộc), nên cache theo nội dung cắt được phần lớn lượt gọi API.
    Đổi nhà cung cấp hoặc đổi giọng sẽ ra khóa khác, không phát nhầm file cũ.
    """
    khoa = f"{TTS_PROVIDER}|{TTS_VOICE}|{text}".encode("utf-8")
    return os.path.join(TTS_CACHE_DIR, hashlib.sha256(khoa).hexdigest() + ".mp3")


def _goi_google(text: str) -> bytes:
    """Google Cloud Text-to-Speech. Trả về mp3.

    Doc: POST https://texttospeech.googleapis.com/v1/text:synthesize
    Khóa API truyền qua header X-Goog-Api-Key.
    """
    body = json.dumps({
        "input": {"text": text},
        "voice": {
            "languageCode": "vi-VN",
            **({"name": TTS_VOICE} if TTS_VOICE else {}),
        },
        "audioConfig": {"audioEncoding": "MP3"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        data=body,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": TTS_API_KEY},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        payload = json.loads(r.read().decode("utf-8"))
    am_thanh = payload.get("audioContent")
    if not am_thanh:
        raise HTTPException(
            status_code=502,
            detail=tr("Google không trả về dữ liệu âm thanh"),
        )
    return base64.b64decode(am_thanh)


def _goi_azure(text: str) -> bytes:
    """Azure Speech. Trả về mp3.

    Doc: POST https://<region>.tts.speech.microsoft.com/cognitiveservices/v1
    Thân request là SSML, khóa truyền qua header Ocp-Apim-Subscription-Key.
    """
    giong = TTS_VOICE or "vi-VN-HoaiMyNeural"
    ssml = (
        "<speak version='1.0' xml:lang='vi-VN'>"
        f"<voice xml:lang='vi-VN' name='{giong}'>{_thoat_xml(text)}</voice>"
        "</speak>"
    ).encode("utf-8")

    req = urllib.request.Request(
        f"https://{TTS_AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml,
        headers={
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
            "Ocp-Apim-Subscription-Key": TTS_API_KEY,
            "User-Agent": "F-Selling",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _thoat_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&apos;")
    )


_BO_CHUYEN_DOI = {"google": _goi_google, "azure": _goi_azure}


def tao_audio(text: str) -> Tuple[bytes, bool]:
    """Trả về (dữ liệu mp3, lấy_từ_cache).

    Ném HTTPException khi chưa cấu hình hoặc nhà cung cấp lỗi - router dịch
    tiếp cho client. KHÔNG nuốt lỗi: frontend cần biết để còn lùi về giọng máy.
    """
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=tr("Thiếu nội dung cần đọc"))
    if len(text) > TTS_MAX_CHARS:
        # Endpoint này tốn tiền theo ký tự. Câu thông báo dài nhất cũng chỉ
        # khoảng 80 ký tự, nên chặn ở đây để không ai biến nó thành dịch vụ
        # đọc sách miễn phí bằng hạn mức của chủ shop.
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Nội dung quá dài (tối đa {maximum} ký tự)",
                maximum=TTS_MAX_CHARS,
            ),
        )

    _kiem_tra_cau_hinh()

    duong_dan = _duong_dan_cache(text)
    if os.path.exists(duong_dan):
        try:
            with open(duong_dan, "rb") as f:
                return f.read(), True
        except OSError:
            pass    # cache hỏng thì gọi lại nhà cung cấp

    ham = _BO_CHUYEN_DOI.get(TTS_PROVIDER)
    if ham is None:
        raise HTTPException(
            status_code=503,
            detail=tr(
                "TTS_PROVIDER='{provider}' không hỗ trợ. Dùng 'google' hoặc 'azure'.",
                provider=TTS_PROVIDER,
            ),
        )

    try:
        du_lieu = ham(text)
    except urllib.error.HTTPError as e:
        chi_tiet = e.read().decode("utf-8", "replace")[:200]
        log_to_file(f"TTS {TTS_PROVIDER} lỗi {e.code}: {chi_tiet}")
        raise HTTPException(
            status_code=502,
            detail=tr("Nhà cung cấp giọng đọc lỗi {code}", code=e.code),
        )
    except urllib.error.URLError as e:
        log_to_file(f"TTS {TTS_PROVIDER} không kết nối được: {e}")
        raise HTTPException(
            status_code=502,
            detail=tr("Không kết nối được nhà cung cấp giọng đọc"),
        )

    if not du_lieu:
        raise HTTPException(
            status_code=502,
            detail=tr("Nhà cung cấp trả về dữ liệu rỗng"),
        )

    try:
        os.makedirs(TTS_CACHE_DIR, exist_ok=True)
        with open(duong_dan, "wb") as f:
            f.write(du_lieu)
    except OSError as e:
        # Không ghi được cache thì vẫn phát được tiếng, chỉ là lần sau gọi lại.
        log_to_file(f"TTS không ghi được cache: {e}")

    return du_lieu, False
