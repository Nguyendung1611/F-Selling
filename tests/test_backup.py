"""Kiểm sao lưu DB lên Cloudflare R2.

Không test nào ở đây gọi mạng thật: `urlopen` luôn bị thay bằng hàm giả.

Trọng tâm không phải "code có chạy không" mà là ba câu hỏi thật sự quan trọng:
bản sao có mở lại được không, có bị tính là xong khi thật ra hỏng không, và
người lạ có gọi được endpoint không.
"""
from __future__ import annotations

import gzip
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

from fselling.routers import cron as cron_router
from fselling.services import backup_service

R2_GIA = {
    "R2_ACCOUNT_ID": "taikhoan123",
    "R2_ACCESS_KEY_ID": "AKIAGIA",
    "R2_SECRET_ACCESS_KEY": "secret-gia-chi-dung-cho-test",
    "R2_BUCKET": "fselling-backup",
    "R2_PREFIX": "backup",
}


def _cau_hinh_r2(monkeypatch):
    for ten, gia_tri in R2_GIA.items():
        monkeypatch.setattr(backup_service, ten, gia_tri)


def _tao_db(duong_dan: str, so_dong: int = 3) -> None:
    conn = sqlite3.connect(duong_dan)
    try:
        conn.execute("CREATE TABLE khach (id INTEGER PRIMARY KEY, ten TEXT)")
        for i in range(so_dong):
            conn.execute("INSERT INTO khach (ten) VALUES (?)", (f"khach {i}",))
        conn.commit()
    finally:
        conn.close()


def _giai_nen_va_doc(goi_gz: bytes, tmp_path) -> list:
    """Giải nén bytes .gz thành file .db rồi đọc bảng khach."""
    ra = tmp_path / "phuc_hoi.db"
    ra.write_bytes(gzip.decompress(goi_gz))
    conn = sqlite3.connect(str(ra))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return [r[0] for r in conn.execute("SELECT ten FROM khach ORDER BY id")]
    finally:
        conn.close()


class _PhanHoiGia:
    def __init__(self, etag: str):
        self.headers = {"ETag": f'"{etag}"'}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _gia_lap_upload(monkeypatch, etag_tu: str = "md5", ghi_lai: dict = None):
    """Thay urlopen bằng hàm giả. `etag_tu="md5"` = trả ETag đúng như R2 thật."""
    import hashlib

    def _fake(req, timeout=None):
        if ghi_lai is not None:
            ghi_lai["url"] = req.full_url
            ghi_lai["method"] = req.get_method()
            ghi_lai["headers"] = dict(req.headers)
            ghi_lai["body"] = req.data
            ghi_lai["timeout"] = timeout
        etag = (
            hashlib.md5(req.data, usedforsecurity=False).hexdigest()
            if etag_tu == "md5"
            else etag_tu
        )
        return _PhanHoiGia(etag)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)


# ---------- Chụp bản sao ----------
def test_ban_sao_mo_lai_duoc_va_du_du_lieu(tmp_path, monkeypatch):
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))

    dich = tmp_path / "sao.db"
    backup_service._chup_ban_sao(str(dich))

    conn = sqlite3.connect(str(dich))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM khach").fetchone()[0] == 3
    finally:
        conn.close()


def test_ban_sao_bo_qua_transaction_chua_commit(tmp_path, monkeypatch):
    """Đây là lý do KHÔNG dùng shutil.copy.

    Trong lúc chụp vẫn có người đang ghi. Bản sao phải là một trạng thái NHẤT
    QUÁN - tức là mọi thứ đã commit, và không dính nửa vời của giao dịch đang dở.
    """
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))

    dang_ghi = sqlite3.connect(str(goc))
    try:
        dang_ghi.execute("INSERT INTO khach (ten) VALUES ('chua commit')")

        dich = tmp_path / "sao.db"
        backup_service._chup_ban_sao(str(dich))
    finally:
        dang_ghi.rollback()
        dang_ghi.close()

    conn = sqlite3.connect(str(dich))
    try:
        ten = [r[0] for r in conn.execute("SELECT ten FROM khach")]
    finally:
        conn.close()
    assert "chua commit" not in ten
    assert len(ten) == 3


def test_thieu_file_db_thi_bao_loi_chu_khong_tao_file_rong(tmp_path, monkeypatch):
    """sqlite3.connect tự tạo file rỗng. Nếu không chặn, ta sẽ tải lên một bản
    sao rỗng và tưởng là đã sao lưu xong."""
    monkeypatch.setattr(backup_service, "DB_PATH", str(tmp_path / "khong-ton-tai.db"))
    with pytest.raises(FileNotFoundError):
        backup_service._chup_ban_sao(str(tmp_path / "sao.db"))


def test_ten_khoa_sap_xep_duoc_theo_thoi_gian():
    som = backup_service._ten_khoa(datetime(2026, 8, 5, 1, 30, 0, tzinfo=timezone.utc))
    muon = backup_service._ten_khoa(datetime(2026, 8, 5, 2, 30, 0, tzinfo=timezone.utc))
    assert som == "backup/fselling-20260805-013000.db.gz"
    assert som < muon  # lifecycle rule và mắt người đều dựa vào thứ tự này


# ---------- Bật/tắt ----------
def test_thieu_bat_ky_bien_nao_cung_la_tat(monkeypatch):
    for thieu in R2_GIA:
        _cau_hinh_r2(monkeypatch)
        monkeypatch.setattr(backup_service, thieu, "")
        if thieu == "R2_PREFIX":
            assert backup_service.dang_bat(), "R2_PREFIX rỗng vẫn chạy được"
        else:
            assert not backup_service.dang_bat(), f"thiếu {thieu} mà vẫn bật"


def test_du_bon_bien_thi_bat(monkeypatch):
    _cau_hinh_r2(monkeypatch)
    assert backup_service.dang_bat()


# ---------- Chữ ký SigV4 ----------
def _ky_thu(monkeypatch, than: bytes = b"noi dung"):
    _cau_hinh_r2(monkeypatch)
    return backup_service._ky_yeu_cau(
        "PUT",
        "taikhoan123.r2.cloudflarestorage.com",
        "/fselling-backup/backup/a.db.gz",
        than,
        datetime(2026, 8, 5, 1, 30, 0, tzinfo=timezone.utc),
    )


def test_header_ky_dung_khuon(monkeypatch):
    h = _ky_thu(monkeypatch)
    assert h["x-amz-date"] == "20260805T013000Z"
    assert h["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAGIA/20260805/auto/s3/aws4_request")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in h["Authorization"]
    assert "Signature=" in h["Authorization"]
    # payload hash phải là sha256 của đúng thân request
    import hashlib
    assert h["x-amz-content-sha256"] == hashlib.sha256(b"noi dung").hexdigest()


def test_cung_dau_vao_thi_cung_chu_ky(monkeypatch):
    assert _ky_thu(monkeypatch)["Authorization"] == _ky_thu(monkeypatch)["Authorization"]


def test_doi_noi_dung_thi_doi_chu_ky(monkeypatch):
    a = _ky_thu(monkeypatch, b"noi dung A")["Authorization"]
    b = _ky_thu(monkeypatch, b"noi dung B")["Authorization"]
    assert a != b


def test_doi_secret_thi_doi_chu_ky(monkeypatch):
    a = _ky_thu(monkeypatch)["Authorization"]
    monkeypatch.setattr(backup_service, "R2_SECRET_ACCESS_KEY", "secret-khac")
    b = backup_service._ky_yeu_cau(
        "PUT",
        "taikhoan123.r2.cloudflarestorage.com",
        "/fselling-backup/backup/a.db.gz",
        b"noi dung",
        datetime(2026, 8, 5, 1, 30, 0, tzinfo=timezone.utc),
    )["Authorization"]
    assert a != b


# ---------- Đối chiếu ETag ----------
def test_etag_lech_thi_bao_loi():
    with pytest.raises(RuntimeError, match="ETag lech"):
        backup_service._kiem_etag("0" * 32, b"noi dung")


def test_etag_dung_thi_khong_sao():
    import hashlib
    du_lieu = b"noi dung"
    backup_service._kiem_etag(hashlib.md5(du_lieu, usedforsecurity=False).hexdigest(), du_lieu)


def test_etag_khong_phai_md5_thi_bo_qua():
    """Bucket bật mã hóa riêng hoặc dùng multipart trả ETag khuôn khác. Chặn một
    bản sao hợp lệ còn tệ hơn không kiểm."""
    backup_service._kiem_etag("abc-2", b"noi dung")


# ---------- Tải lên ----------
def test_tai_len_gui_dung_url_method_va_timeout(monkeypatch):
    _cau_hinh_r2(monkeypatch)
    monkeypatch.setattr(backup_service, "BACKUP_TIMEOUT_SECONDS", 42)
    ghi = {}
    _gia_lap_upload(monkeypatch, ghi_lai=ghi)

    backup_service._tai_len("backup/a.db.gz", b"noi dung")

    assert ghi["url"] == "https://taikhoan123.r2.cloudflarestorage.com/fselling-backup/backup/a.db.gz"
    assert ghi["method"] == "PUT"
    assert ghi["body"] == b"noi dung"
    assert ghi["timeout"] == 42
    # urllib chuẩn hóa tên header về dạng Title-Case
    assert "Authorization" in ghi["headers"]


def test_r2_tu_choi_thi_nem_loi_kem_chi_tiet(monkeypatch):
    _cau_hinh_r2(monkeypatch)

    def _fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {}, __import__("io").BytesIO(b"<Error>SignatureDoesNotMatch</Error>")
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    with pytest.raises(RuntimeError, match="SignatureDoesNotMatch"):
        backup_service._tai_len("backup/a.db.gz", b"x")


# ---------- Toàn luồng ----------
def test_chay_sao_luu_tai_len_dung_noi_dung_phuc_hoi_duoc(tmp_path, monkeypatch):
    """Test quan trọng nhất: thứ tải lên R2 phải giải nén ra được một DB SQLite
    lành lặn, đủ dữ liệu."""
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))
    _cau_hinh_r2(monkeypatch)
    ghi = {}
    _gia_lap_upload(monkeypatch, ghi_lai=ghi)

    ket_qua = backup_service.chay_sao_luu()

    assert ket_qua["khoa"].startswith("backup/fselling-")
    assert ket_qua["khoa"].endswith(".db.gz")
    assert ket_qua["byte_nen"] == len(ghi["body"])
    assert ket_qua["byte_goc"] > 0
    assert _giai_nen_va_doc(ghi["body"], tmp_path) == ["khach 0", "khach 1", "khach 2"]


def test_chua_cau_hinh_thi_khong_goi_mang(tmp_path, monkeypatch):
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))
    monkeypatch.setattr(backup_service, "R2_BUCKET", "")

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("Chua cau hinh ma van goi mang")

    monkeypatch.setattr(urllib.request, "urlopen", _khong_duoc_goi)
    with pytest.raises(RuntimeError, match="Chua cau hinh R2"):
        backup_service.chay_sao_luu()


# ---------- Endpoint ----------
def test_endpoint_503_khi_chua_cau_hinh_secret(client, monkeypatch):
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "")
    res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "gi-cung-duoc"})
    assert res.status_code == 503


def test_endpoint_401_khi_sai_secret(client, monkeypatch):
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "dung-secret")
    res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "sai-secret"})
    assert res.status_code == 401


def test_endpoint_401_khi_thieu_header(client, monkeypatch):
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "dung-secret")
    assert client.post("/api/cron/backup").status_code == 401


def test_endpoint_503_khi_dung_secret_nhung_chua_cau_hinh_r2(client, monkeypatch):
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "dung-secret")
    monkeypatch.setattr(backup_service, "R2_BUCKET", "")
    res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "dung-secret"})
    assert res.status_code == 503


def test_endpoint_chay_duoc_va_tra_thong_tin_ban_sao(client, tmp_path, monkeypatch):
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))
    _cau_hinh_r2(monkeypatch)
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "dung-secret")
    _gia_lap_upload(monkeypatch)

    res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "dung-secret"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["khoa"].startswith("backup/fselling-")
    assert body["byte_nen"] > 0


def test_endpoint_that_bai_thi_tra_500_chu_khong_nuot_loi(client, tmp_path, monkeypatch):
    """Khác webhook ngân hàng (luôn 200): ở đây mã lỗi là cách DUY NHẤT dịch vụ
    cron biết bản sao hỏng để báo động."""
    goc = tmp_path / "goc.db"
    _tao_db(str(goc))
    monkeypatch.setattr(backup_service, "DB_PATH", str(goc))
    _cau_hinh_r2(monkeypatch)
    monkeypatch.setattr(cron_router, "BACKUP_CRON_SECRET", "dung-secret")
    _gia_lap_upload(monkeypatch, etag_tu="0" * 32)  # ETag lệch = bản sao có thể cụt

    res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "dung-secret"})
    assert res.status_code == 500
    assert "ETag lech" in res.json()["detail"]
