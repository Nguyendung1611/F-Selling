r"""Sinh bộ MP3 tiếng Việt dùng để ghép câu đọc số tiền tại quầy POS.

Chạy từ thư mục ``python_app``:

    .\.venv\Scripts\python.exe scripts\tao_audio_doc_tien.py

Các file được sinh sẵn và phục vụ như static asset, vì vậy production không
cần cài ``edge-tts`` và không gọi dịch vụ TTS khi có giao dịch.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "static" / "audio"
VOICE = "vi-VN-HoaiMyNeural"

AUDIO_KEYWORDS = {
    # Câu dẫn và hành động
    "da_nhan.mp3": "Đã nhận",
    "tai_khoan.mp3": "Tài khoản",
    "thanh_cong.mp3": "Thành công",

    # Chữ số
    "0.mp3": "Không",
    "1.mp3": "Một",
    "2.mp3": "Hai",
    "3.mp3": "Ba",
    "4.mp3": "Bốn",
    "5.mp3": "Năm",
    "6.mp3": "Sáu",
    "7.mp3": "Bảy",
    "8.mp3": "Tám",
    "9.mp3": "Chín",

    # Cách đọc phụ thuộc vị trí
    "muoi_10.mp3": "Mười",
    "muoi_tens.mp3": "Mươi",
    "lam.mp3": "Lăm",
    "mot_mot.mp3": "Mốt",
    "tu.mp3": "Tư",
    "le.mp3": "Lẻ",

    # Hàng và tiền tệ
    "tram.mp3": "Trăm",
    "nghin.mp3": "Nghìn",
    "trieu.mp3": "Triệu",
    "ty.mp3": "Tỷ",
    "dong.mp3": "Đồng",
}


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Dung ASCII cho console de chay duoc ca tren PowerShell dang o CP1252.
    print(f"Dang tao {len(AUDIO_KEYWORDS)} file MP3 bang giong {VOICE}...")
    for filename, text in AUDIO_KEYWORDS.items():
        filepath = OUTPUT_DIR / filename
        await edge_tts.Communicate(text, VOICE).save(str(filepath))
        print(f"  Da tao {filename}")
    print(f"Hoan thanh. Audio nam tai: {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
