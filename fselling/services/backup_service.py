"""Sao lưu database SQLite lên Cloudflare R2.

Vì sao có file này: toàn bộ dữ liệu của mọi cửa hàng — sổ nợ, lịch sử ca thu
ngân, giá vốn, phiếu hủy — nằm trong MỘT file SQLite trên MỘT volume của Fly.
Volume hỏng hoặc xóa nhầm là mất trắng, không có đường lùi.

Bốn quyết định đã cân nhắc, đừng tự ý làm khác:

1. **KHÔNG copy file `.db` bằng `shutil`.** SQLite đang được ghi thì bản copy có
   thể rơi vào giữa một transaction, mở ra là hỏng — mà hỏng kiểu này chỉ lộ ra
   đúng lúc cần phục hồi. Dùng API backup của chính SQLite
   (`Connection.backup`): nó chụp một bản NHẤT QUÁN trong khi app vẫn đang bán
   hàng bình thường, không khóa gì lâu.

2. **KHÔNG dùng boto3.** Nó kéo botocore (~50MB) vào image cho đúng một lệnh
   PUT, trên máy Fly 512MB. Ký SigV4 bằng tay hết ~60 dòng hmac/sha256, và dự
   án đã có tiền lệ gọi HTTP bằng `urllib` (xem `tts_service.py`).

3. **KHÔNG tự viết code xóa bản cũ.** Đặt lifecycle rule ngay trên bucket R2
   (Dashboard → bucket → Settings → Object lifecycle rules) là Cloudflare tự
   xóa hộ: không tốn dòng code nào, và không có nguy cơ code xóa nhầm bản mới.
   Code xóa dữ liệu là loại code đắt nhất khi viết sai.

4. **Chỉ sao lưu DB, không sao lưu `uploads/`.** Ảnh sản phẩm nặng hơn nhiều
   lần và chụp lại được; sổ nợ thì không. Muốn thêm ảnh thì làm ở luồng riêng,
   đừng ghép vào đây rồi làm chậm bản sao quan trọng.

Chưa cấu hình đủ biến môi trường thì tính năng TẮT hẳn (`dang_bat()` = False)
và endpoint trả 503. Không có chế độ "sao lưu một nửa".
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import os
import shutil
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..core.config import (
    BACKUP_TIMEOUT_SECONDS,
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET,
    R2_PREFIX,
    R2_SECRET_ACCESS_KEY,
    log_to_file,
)
from ..core.database import db_path as DB_PATH

# R2 không có khái niệm region như S3, nhưng SigV4 vẫn bắt buộc có trường đó.
# Tài liệu Cloudflare yêu cầu ký với đúng chuỗi "auto".
_VUNG = "auto"
_DICH_VU = "s3"
_THUAT_TOAN = "AWS4-HMAC-SHA256"

_HEX = set("0123456789abcdef")


def dang_bat() -> bool:
    """Đủ bốn giá trị mới coi là đã cấu hình. Thiếu một cái là tắt."""
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET)


# ---------- Chụp bản sao ----------
def _chup_ban_sao(dich: str) -> None:
    """Chụp một bản NHẤT QUÁN của DB đang chạy sang `dich`.

    `sqlite3.connect` sẽ TẠO file rỗng nếu đường dẫn không tồn tại, nên phải tự
    kiểm trước: thiếu file mà cứ chạy tiếp là tải lên một bản sao rỗng và tưởng
    đã sao lưu xong — tệ hơn hẳn việc báo lỗi.
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Khong tim thay database: {DB_PATH}")

    nguon = sqlite3.connect(DB_PATH)
    try:
        ban_sao = sqlite3.connect(dich)
        try:
            nguon.backup(ban_sao)
        finally:
            ban_sao.close()
    finally:
        nguon.close()


def _nen(nguon: str, dich: str) -> None:
    with open(nguon, "rb") as vao, gzip.open(dich, "wb", compresslevel=6) as ra:
        shutil.copyfileobj(vao, ra)


def _ten_khoa(luc: Optional[datetime] = None) -> str:
    """Tên sắp xếp được theo thời gian, để lifecycle rule quét theo tiền tố."""
    luc = luc or datetime.now(timezone.utc)
    tien_to = (R2_PREFIX or "").strip("/")
    ten = f"fselling-{luc.strftime('%Y%m%d-%H%M%S')}.db.gz"
    return f"{tien_to}/{ten}" if tien_to else ten


# ---------- Ký AWS Signature V4 ----------
def _bam_hex(du_lieu: bytes) -> str:
    return hashlib.sha256(du_lieu).hexdigest()


def _hmac_bytes(khoa: bytes, tin: str) -> bytes:
    return hmac.new(khoa, tin.encode("utf-8"), hashlib.sha256).digest()


def _khoa_ky(secret: str, ngay: str) -> bytes:
    """Khóa ký dẫn xuất bốn bước theo đặc tả SigV4 (ngày → vùng → dịch vụ → hằng)."""
    k = _hmac_bytes(f"AWS4{secret}".encode("utf-8"), ngay)
    k = _hmac_bytes(k, _VUNG)
    k = _hmac_bytes(k, _DICH_VU)
    return _hmac_bytes(k, "aws4_request")


def _ky_yeu_cau(
    phuong_thuc: str, host: str, duong_dan: str, than: bytes, luc: datetime
) -> Dict[str, str]:
    """Sinh bộ header đã ký cho một request tới R2.

    Chuỗi `yeu_cau_chuan` phải khớp ĐÚNG TỪNG KÝ TỰ với thứ máy chủ tự dựng lại,
    kể cả dòng trống. `header_chuan` đã kết thúc bằng `\\n`, nên khi `join` bằng
    `\\n` sẽ tạo ra dòng trống ngăn cách — đó là đúng đặc tả, không phải thừa.

    Sai một ký tự ở đây thì R2 trả `SignatureDoesNotMatch`, không nói sai chỗ nào.
    Hai nguyên nhân hay gặp nhất ngoài lỗi code: sai khóa, và đồng hồ máy lệch
    quá 15 phút.
    """
    amz_date = luc.strftime("%Y%m%dT%H%M%SZ")
    ngay = luc.strftime("%Y%m%d")
    bam_than = _bam_hex(than)
    duong_dan_ma_hoa = urllib.parse.quote(duong_dan, safe="/~")

    header_chuan = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{bam_than}\n"
        f"x-amz-date:{amz_date}\n"
    )
    header_da_ky = "host;x-amz-content-sha256;x-amz-date"

    yeu_cau_chuan = "\n".join([
        phuong_thuc,
        duong_dan_ma_hoa,
        "",  # query string rỗng
        header_chuan,
        header_da_ky,
        bam_than,
    ])

    pham_vi = f"{ngay}/{_VUNG}/{_DICH_VU}/aws4_request"
    chuoi_de_ky = "\n".join([
        _THUAT_TOAN,
        amz_date,
        pham_vi,
        _bam_hex(yeu_cau_chuan.encode("utf-8")),
    ])
    chu_ky = hmac.new(
        _khoa_ky(R2_SECRET_ACCESS_KEY, ngay),
        chuoi_de_ky.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "Host": host,
        "x-amz-content-sha256": bam_than,
        "x-amz-date": amz_date,
        "Authorization": (
            f"{_THUAT_TOAN} Credential={R2_ACCESS_KEY_ID}/{pham_vi}, "
            f"SignedHeaders={header_da_ky}, Signature={chu_ky}"
        ),
    }


# ---------- Tải lên ----------
def _kiem_etag(etag: str, du_lieu: bytes) -> None:
    """Đối chiếu ETag với nội dung vừa gửi.

    HTTP 200 chỉ nói "máy chủ nhận rồi", KHÔNG nói "nhận đủ". Với PUT thường
    (không multipart, bucket không bật mã hóa riêng), S3/R2 trả ETag = MD5 của
    nội dung — nên muốn đối chiếu thì phải tính đúng thuật toán đó. Đây KHÔNG
    phải dùng MD5 cho mục đích bảo mật.

    ETag không đúng khuôn 32 ký tự hex thì bỏ qua thay vì báo lỗi: bucket cấu
    hình khác sẽ trả khuôn khác, và chặn một bản sao hợp lệ còn tệ hơn không kiểm.
    """
    etag = etag.lower()
    if len(etag) != 32 or any(c not in _HEX for c in etag):
        return
    thuc_te = hashlib.md5(du_lieu, usedforsecurity=False).hexdigest()
    if thuc_te != etag:
        raise RuntimeError(
            f"ETag lech: R2 bao {etag}, tinh duoc {thuc_te}. Ban sao co the bi cut."
        )


def _tai_len(khoa: str, du_lieu: bytes) -> str:
    """PUT nội dung lên R2, trả về ETag."""
    host = f"{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    duong_dan = f"/{R2_BUCKET}/{khoa}"
    headers = _ky_yeu_cau("PUT", host, duong_dan, du_lieu, datetime.now(timezone.utc))
    headers["Content-Type"] = "application/gzip"

    req = urllib.request.Request(
        f"https://{host}{urllib.parse.quote(duong_dan, safe='/~')}",
        data=du_lieu,
        headers=headers,
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=BACKUP_TIMEOUT_SECONDS) as r:
            return (r.headers.get("ETag") or "").strip('"')
    except urllib.error.HTTPError as e:
        # R2 trả lỗi dạng XML. Đọc ra mới biết là sai khóa, sai tên bucket hay
        # lệch đồng hồ — thiếu nó thì chỉ còn con số 403 không tra được gì.
        chi_tiet = ""
        try:
            chi_tiet = e.read().decode("utf-8", "replace")[:500]
        except OSError:
            pass
        raise RuntimeError(f"R2 tu choi ({e.code}): {chi_tiet}") from e


# ---------- Đầu vào chính ----------
def chay_sao_luu() -> Dict[str, Any]:
    """Chụp — nén — tải lên — đối chiếu. Trả về thông tin bản sao vừa tạo.

    Ném lỗi khi thất bại, KHÔNG nuốt: người gọi (endpoint cron) phải trả mã lỗi
    ra ngoài để dịch vụ cron báo động. Một bản sao thất bại trong im lặng thì
    còn tệ hơn không có bản sao nào, vì nó tạo cảm giác an toàn giả.
    """
    if not dang_bat():
        raise RuntimeError(
            "Chua cau hinh R2 (can R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET)"
        )

    bat_dau = time.monotonic()
    thu_muc = tempfile.mkdtemp(prefix="fselling_backup_")
    try:
        anh_chup = os.path.join(thu_muc, "snapshot.db")
        _chup_ban_sao(anh_chup)

        goi = anh_chup + ".gz"
        _nen(anh_chup, goi)
        with open(goi, "rb") as f:
            du_lieu = f.read()

        khoa = _ten_khoa()
        etag = _tai_len(khoa, du_lieu)
        _kiem_etag(etag, du_lieu)

        ket_qua: Dict[str, Any] = {
            "khoa": khoa,
            "byte_goc": os.path.getsize(anh_chup),
            "byte_nen": len(du_lieu),
            "etag": etag,
            "giay": round(time.monotonic() - bat_dau, 2),
        }
        log_to_file(f"BACKUP OK: {ket_qua}")
        print(f"[BACKUP] Da tai len {khoa} ({len(du_lieu)} byte, {ket_qua['giay']}s)")
        return ket_qua
    finally:
        shutil.rmtree(thu_muc, ignore_errors=True)
