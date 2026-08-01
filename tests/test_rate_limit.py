"""F3: chống dò mật khẩu và chống dò mã OTP.

Trước bản này cả ba đường dưới đây đều cho đoán KHÔNG GIỚI HẠN:

- `POST /api/auth/login` - dò mật khẩu.
- `POST /api/auth/verify-email` - dò mã 6 chữ số để kích hoạt tài khoản người khác.
- `POST /api/auth/forgot-password-reset` - dò mã 6 chữ số để **chiếm tài khoản**.

Đường thứ ba nguy hiểm nhất: 6 chữ số chỉ có một triệu khả năng, và phần thưởng
là đặt được mật khẩu mới cho tài khoản người khác.
"""
import uuid
from datetime import datetime, timedelta

from conftest import SELLER_PASSWORD, login, register_seller

from fselling import models
from fselling.core.config import (
    LOGIN_LOCKOUT_MINUTES,
    LOGIN_MAX_ATTEMPTS,
    OTP_MAX_ATTEMPTS,
)
from fselling.core.database import SessionLocal


def _email(username: str) -> str:
    return f"{username}@example.com"


def _user(username: str) -> models.User:
    session = SessionLocal()
    try:
        return (
            session.query(models.User)
            .filter(models.User.username == username)
            .first()
        )
    finally:
        session.close()


def _sua_user(username: str, **truong) -> None:
    session = SessionLocal()
    try:
        u = session.query(models.User).filter(models.User.username == username).first()
        for k, v in truong.items():
            setattr(u, k, v)
        session.commit()
    finally:
        session.close()


def _dang_nhap_sai(client, username: str, lan: int = 1):
    res = None
    for _ in range(lan):
        res = client.post(
            "/api/auth/login", json={"username": username, "password": "Sai@12345"}
        )
    return res


# ---------- Khóa tạm khi dò mật khẩu ----------
def test_sai_du_nguong_thi_khoa_tam(client):
    username = register_seller(client)

    for i in range(LOGIN_MAX_ATTEMPTS - 1):
        res = _dang_nhap_sai(client, username)
        assert res.status_code == 401, f"Lần sai thứ {i + 1} vẫn chỉ là 401"

    res = _dang_nhap_sai(client, username)
    assert res.status_code == 429, "Lần chạm ngưỡng phải khóa"
    assert _user(username).locked_until is not None


def test_dang_khoa_thi_mat_khau_DUNG_cung_khong_vao_duoc(client):
    """Nếu vẫn cho vào bằng mật khẩu đúng thì lệnh khóa vô nghĩa: kẻ dò cứ việc
    thử tiếp, chỉ cần trúng là xong."""
    username = register_seller(client)
    _dang_nhap_sai(client, username, LOGIN_MAX_ATTEMPTS)

    res = client.post(
        "/api/auth/login", json={"username": username, "password": SELLER_PASSWORD}
    )
    assert res.status_code == 429


def test_het_gio_khoa_thi_vao_lai_duoc(client):
    username = register_seller(client)
    _dang_nhap_sai(client, username, LOGIN_MAX_ATTEMPTS)

    # Kéo mốc khóa về quá khứ thay vì ngồi chờ 15 phút.
    _sua_user(username, locked_until=datetime.utcnow() - timedelta(seconds=1))

    res = client.post(
        "/api/auth/login", json={"username": username, "password": SELLER_PASSWORD}
    )
    assert res.status_code == 200, res.text


def test_dang_nhap_dung_xoa_sach_bo_dem(client):
    """Bộ đếm là "sai LIÊN TIẾP", không phải tổng cộng cả đời - người hay gõ
    nhầm không được phép bị khóa oan sau vài tuần dùng bình thường."""
    username = register_seller(client)
    _dang_nhap_sai(client, username, LOGIN_MAX_ATTEMPTS - 1)
    assert _user(username).failed_login_count == LOGIN_MAX_ATTEMPTS - 1

    assert login(client, username)
    assert _user(username).failed_login_count == 0
    assert _user(username).locked_until is None

    # Và sau đó phải được sai lại đủ số lần từ đầu.
    for _ in range(LOGIN_MAX_ATTEMPTS - 1):
        assert _dang_nhap_sai(client, username).status_code == 401


def test_khoa_tai_khoan_nay_khong_anh_huong_tai_khoan_khac(client):
    a = register_seller(client)
    b = register_seller(client)
    _dang_nhap_sai(client, a, LOGIN_MAX_ATTEMPTS)

    assert login(client, b), "Khóa phải theo từng tài khoản"


def test_username_khong_ton_tai_van_tra_401_giong_het(client):
    """Không được lộ username nào có thật qua mã lỗi."""
    res = client.post(
        "/api/auth/login",
        json={"username": f"khong_co_{uuid.uuid4().hex[:6]}", "password": "Sai@12345"},
    )
    assert res.status_code == 401

    username = register_seller(client)
    sai = _dang_nhap_sai(client, username)
    assert sai.status_code == 401
    assert sai.json()["detail"] == res.json()["detail"], (
        "Thông báo phải giống hệt nhau, nếu không là chỉ luôn tài khoản nào có thật"
    )


def test_username_khong_ton_tai_khong_bao_gio_bi_khoa(client):
    """Không có hàng user để đếm; phải trả 401 mãi chứ không được 429 hay 500."""
    ten = f"khong_co_{uuid.uuid4().hex[:6]}"
    for _ in range(LOGIN_MAX_ATTEMPTS + 2):
        res = client.post(
            "/api/auth/login", json={"username": ten, "password": "Sai@12345"}
        )
        assert res.status_code == 401


def test_thong_bao_khoa_co_kem_so_phut(client):
    username = register_seller(client)
    res = _dang_nhap_sai(client, username, LOGIN_MAX_ATTEMPTS)
    assert str(LOGIN_LOCKOUT_MINUTES) in res.json()["detail"]


# ---------- Chặn dò mã OTP: xác minh email ----------
def _dang_ky_chua_xac_minh(client) -> str:
    username = f"otp_{uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": SELLER_PASSWORD,
            "email": _email(username),
        },
    )
    assert res.status_code == 200, res.text
    return username


def _nhap_ma_sai(client, username: str, lan: int = 1):
    res = None
    for _ in range(lan):
        res = client.post(
            "/api/auth/verify-email",
            json={"email": _email(username), "code": "000000"},
        )
    return res


def test_nhap_sai_ma_du_nguong_thi_huy_ma(client, _no_real_email):
    username = _dang_ky_chua_xac_minh(client)
    ma_that = _no_real_email[-1]["code"]

    for i in range(OTP_MAX_ATTEMPTS - 1):
        assert _nhap_ma_sai(client, username).status_code == 400, f"lần {i + 1}"

    assert _nhap_ma_sai(client, username).status_code == 429
    assert _user(username).verification_code is None, "Chạm ngưỡng là mã phải bị hủy"

    # Mã thật cũng vô dụng: nó đã bị hủy rồi.
    res = client.post(
        "/api/auth/verify-email", json={"email": _email(username), "code": ma_that}
    )
    assert res.status_code in (400, 429)
    assert _user(username).is_verified is False


def test_huy_ma_chu_khong_khoa_tai_khoan(client, _no_real_email):
    """CỐ Ý không khóa tài khoản theo email: khóa kiểu đó thì ai biết email của
    bạn cũng vô hiệu hóa được tài khoản bạn, chỉ bằng cách gõ bừa vài lần."""
    username = _dang_ky_chua_xac_minh(client)
    _nhap_ma_sai(client, username, OTP_MAX_ATTEMPTS)

    u = _user(username)
    assert u.locked_until is None, "Dò mã KHÔNG được khóa tài khoản"

    # Chủ tài khoản chỉ cần xin mã mới là dùng tiếp được.
    _sua_user(username, verification_code_sent_at=None)
    res = client.post("/api/auth/resend-code", json={"email": _email(username)})
    assert res.status_code == 200, res.text
    ma_moi = _no_real_email[-1]["code"]
    res = client.post(
        "/api/auth/verify-email", json={"email": _email(username), "code": ma_moi}
    )
    assert res.status_code == 200, res.text


def test_ma_moi_reset_bo_dem_sai(client, _no_real_email):
    """Mã mới là bí mật mới; số lần đoán hụt mã cũ không nói gì về nó."""
    username = _dang_ky_chua_xac_minh(client)
    _nhap_ma_sai(client, username, OTP_MAX_ATTEMPTS - 1)
    assert _user(username).verification_attempts == OTP_MAX_ATTEMPTS - 1

    _sua_user(username, verification_code_sent_at=None)
    client.post("/api/auth/resend-code", json={"email": _email(username)})
    assert _user(username).verification_attempts == 0

    # Và được sai lại đủ số lần từ đầu chứ không bị chặn ngay.
    assert _nhap_ma_sai(client, username).status_code == 400


def test_xac_minh_thanh_cong_reset_bo_dem(client, _no_real_email):
    username = _dang_ky_chua_xac_minh(client)
    _nhap_ma_sai(client, username, OTP_MAX_ATTEMPTS - 1)
    ma = _user(username).verification_code

    res = client.post(
        "/api/auth/verify-email", json={"email": _email(username), "code": ma}
    )
    assert res.status_code == 200, res.text
    assert _user(username).verification_attempts == 0


# ---------- Chặn dò mã OTP: đặt lại mật khẩu ----------
def test_do_ma_dat_lai_mat_khau_bi_chan(client, _no_real_email):
    """Đường nguy hiểm nhất: đoán trúng 6 chữ số là chiếm được tài khoản."""
    username = register_seller(client)
    client.post("/api/auth/forgot-password-request", json={"email": _email(username)})

    for _ in range(OTP_MAX_ATTEMPTS - 1):
        res = client.post(
            "/api/auth/forgot-password-reset",
            json={
                "email": _email(username),
                "code": "000000",
                "new_password": "Cuop@2026abc",
            },
        )
        assert res.status_code == 400

    res = client.post(
        "/api/auth/forgot-password-reset",
        json={
            "email": _email(username),
            "code": "000000",
            "new_password": "Cuop@2026abc",
        },
    )
    assert res.status_code == 429
    assert _user(username).verification_code is None

    # Mật khẩu cũ phải còn nguyên - không được đổi được gì cả.
    assert login(client, username, SELLER_PASSWORD)


def test_dat_lai_mat_khau_thanh_cong_go_luon_khoa_dang_nhap(client, _no_real_email):
    """Đổi được mật khẩu nghĩa là đã chứng minh sở hữu email, không có lý do gì
    bắt chủ tài khoản ngồi chờ hết giờ khóa."""
    username = register_seller(client)
    _dang_nhap_sai(client, username, LOGIN_MAX_ATTEMPTS)
    assert _user(username).locked_until is not None

    client.post("/api/auth/forgot-password-request", json={"email": _email(username)})
    ma = _no_real_email[-1]["code"]
    res = client.post(
        "/api/auth/forgot-password-reset",
        json={"email": _email(username), "code": ma, "new_password": "Moi@2026abc"},
    )
    assert res.status_code == 200, res.text
    assert _user(username).locked_until is None
    assert login(client, username, "Moi@2026abc")


# ---------- Cooldown xin mã ----------
def test_xin_ma_lien_tuc_bi_chan(client, _no_real_email):
    username = register_seller(client)
    assert client.post(
        "/api/auth/forgot-password-request", json={"email": _email(username)}
    ).status_code == 200

    res = client.post(
        "/api/auth/forgot-password-request", json={"email": _email(username)}
    )
    assert res.status_code == 429, "Xin mã lần hai ngay lập tức phải bị chặn"


def test_het_cooldown_thi_xin_lai_duoc(client, _no_real_email):
    username = register_seller(client)
    client.post("/api/auth/forgot-password-request", json={"email": _email(username)})

    _sua_user(username, verification_code_sent_at=datetime.utcnow() - timedelta(hours=1))
    res = client.post(
        "/api/auth/forgot-password-request", json={"email": _email(username)}
    )
    assert res.status_code == 200, res.text


def test_cooldown_dung_chung_cho_moi_duong_xin_ma(client, _no_real_email):
    """Hai endpoint cùng gửi mail tới một hộp thư, nên phải chung một cooldown -
    nếu tách riêng thì luân phiên hai đường là gửi được gấp đôi."""
    username = _dang_ky_chua_xac_minh(client)  # register vừa gửi một mã

    res = client.post("/api/auth/resend-code", json={"email": _email(username)})
    assert res.status_code == 429

    res = client.post(
        "/api/auth/forgot-password-request", json={"email": _email(username)}
    )
    assert res.status_code == 429


def test_so_mail_da_gui_khong_tang_khi_bi_chan(client, _no_real_email):
    username = _dang_ky_chua_xac_minh(client)
    so_mail = len(_no_real_email)

    client.post("/api/auth/resend-code", json={"email": _email(username)})
    assert len(_no_real_email) == so_mail, "Bị chặn thì tuyệt đối không gửi mail"
