r"""Sinh icon PWA (192x192 va 512x512) tu con so, khong can Pillow.

Chay tu thu muc ``python_app``:

    .\.venv\Scripts\python.exe scripts\tao_icon_pwa.py

Vi sao tu ve thay vi cat tu logo.png: logo hien tai la banner ngang 709x352,
cat vuong se meo hoac mat chu. Va them Pillow vao requirements chi de cat mot
buc anh la khong dang - anh nay ve xong mot lan roi thoi.

Anh duoc ve FULL-BLEED (kin toan bo khung, khong co goc trong suot) vi manifest
khai `purpose: "any maskable"`. Android tu bo goc theo hinh dang cua may (tron,
vuong bo goc, giot nuoc...), nen phan quan trong phai nam trong vung an toan
80% o giua. Chu F o day nam gon trong khoang do.

Muon doi mau thi sua CAM / TRANG ben duoi roi chay lai. Nho commit ca file PNG.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

THU_MUC = Path(__file__).resolve().parents[1] / "static" / "img"

CAM = (249, 115, 22, 255)      # --primary #F97316
TRANG = (255, 255, 255, 255)

# Toa do chu F theo ti le canh anh (0..1). Giu trong khoang 0.2-0.8 de khong bi
# mat khi Android bo goc.
THANH_DOC = (0.30, 0.25, 0.43, 0.78)   # trai, tren, phai, duoi
THANH_TREN = (0.30, 0.25, 0.71, 0.37)
THANH_GIUA = (0.30, 0.45, 0.63, 0.57)


def _chunk(loai: bytes, du_lieu: bytes) -> bytes:
    return (
        struct.pack(">I", len(du_lieu))
        + loai
        + du_lieu
        + struct.pack(">I", zlib.crc32(loai + du_lieu) & 0xFFFFFFFF)
    )


def ghi_png(duong_dan: Path, canh: int, hang: list[bytearray]) -> None:
    """Ghi anh RGBA 8-bit. `hang` la danh sach `canh` dong, moi dong `canh`*4 byte."""
    tho = b"".join(b"\x00" + bytes(d) for d in hang)  # \x00 = filter None moi dong
    duong_dan.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", canh, canh, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(tho, 9))
        + _chunk(b"IEND", b"")
    )


def _trong_hop(x: int, y: int, canh: int, hop: tuple) -> bool:
    trai, tren, phai, duoi = hop
    return (trai * canh <= x < phai * canh) and (tren * canh <= y < duoi * canh)


def ve_icon(canh: int) -> list[bytearray]:
    hang: list[bytearray] = []
    for y in range(canh):
        dong = bytearray()
        for x in range(canh):
            la_chu = (
                _trong_hop(x, y, canh, THANH_DOC)
                or _trong_hop(x, y, canh, THANH_TREN)
                or _trong_hop(x, y, canh, THANH_GIUA)
            )
            dong += bytes(TRANG if la_chu else CAM)
        hang.append(dong)
    return hang


def main() -> int:
    THU_MUC.mkdir(parents=True, exist_ok=True)
    for canh in (192, 512):
        dich = THU_MUC / f"icon-{canh}.png"
        ghi_png(dich, canh, ve_icon(canh))
        print(f"Da tao {dich.name}: {canh}x{canh}, {dich.stat().st_size:,} byte")
    print("\nXong. Nho commit ca hai file PNG.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
