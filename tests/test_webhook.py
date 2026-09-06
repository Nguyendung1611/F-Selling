"""Webhook thanh toán: fail-closed, body limit, log redaction, gửi lặp."""
import re

import pytest
from conftest import auth, seller_with_shop

from fselling.services import payment_service
from fselling.routers import webhooks

SECRET = "webhook-secret-test"

# `seller_with_shop` tạo sản phẩm giá 100000, `_tao_don` mua đúng 1 cái.
TONG_TIEN = 100000


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: SECRET)
    return SECRET


@pytest.fixture
def khong_co_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "get_webhook_secret", lambda: "")


def _tao_don(client):
    ctx = seller_with_shop(client)
    order_id = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={"items": [{"product_name": ctx["product"]["name"], "price": 100000, "quantity": 1}]},
        headers=auth(ctx["token"]),
    ).json()["order_id"]
    return ctx, order_id


def _trang_thai(client, ctx, order_id):
    return client.get(f"/api/orders/{order_id}", headers=auth(ctx["token"])).json()["status"]


def test_thieu_secret_thi_tu_choi_fail_closed(client, khong_co_secret):
    ctx, order_id = _tao_don(client)
    res = client.post("/api/orders/webhook", json={"order_id": order_id})
    assert res.status_code == 503
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_sai_secret_bi_tu_choi(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": order_id},
        headers={"X-Webhook-Secret": "sai-secret"},
    )
    assert res.status_code == 401
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_khong_gui_secret_bi_tu_choi(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post("/api/orders/webhook", json={"order_id": order_id})
    assert res.status_code == 401
    assert _trang_thai(client, ctx, order_id) == "PENDING"


def test_secret_dung_cap_nhat_don_sang_paid(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": order_id, "amount": TONG_TIEN},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert res.json()["order_ids"] == [order_id]
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_chap_nhan_secret_qua_header_authorization(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    for header in (f"Bearer {SECRET}", f"Apikey {SECRET}"):
        res = client.post(
            "/api/orders/webhook",
            json={"order_id": order_id, "amount": TONG_TIEN},
            headers={"Authorization": header},
        )
        assert res.status_code == 200


def test_webhook_gui_lap_khong_xu_ly_lai(client, webhook_secret):
    from fselling import models
    from fselling.core.database import SessionLocal

    ctx, order_id = _tao_don(client)
    headers = {"X-Webhook-Secret": SECRET}
    payload = {"order_id": order_id, "amount": TONG_TIEN, "id": "TXN-LAP-1"}

    for _ in range(3):
        res = client.post("/api/orders/webhook", json=payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["order_ids"] == [order_id]

    assert _trang_thai(client, ctx, order_id) == "PAID"

    # Chỉ được ghi đúng 1 log WEBHOOK_PAYMENT cho đơn này, và tồn kho không bị trừ thêm
    session = SessionLocal()
    try:
        logs = (
            session.query(models.SystemLog)
            .filter(
                models.SystemLog.action == "WEBHOOK_PAYMENT",
                models.SystemLog.details.like(f"Order {order_id} %"),
            )
            .all()
        )
        assert len(logs) == 1
        prod = session.query(models.Product).filter(
            models.Product.id == ctx["product"]["id"]
        ).first()
        assert prod.stock == 9
    finally:
        session.close()


def test_khong_tim_thay_ma_don_tra_400(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        json={"content": "chuyen khoan khong co ma"},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 400


def test_don_khong_ton_tai_tra_404(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        json={"order_id": 999999},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 404


def test_body_khong_phai_json_van_bi_chan_boi_secret(client, webhook_secret):
    res = client.post(
        "/api/orders/webhook",
        content=b"khong-phai-json",
        headers={"X-Webhook-Secret": "sai"},
    )
    assert res.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Webhook-Secret": "sai-secret"},
    ],
    ids=["missing-client-secret", "wrong-client-secret"],
)
def test_secret_sai_hoac_thieu_khong_doc_parse_log_body_hay_goi_service(
    client, webhook_secret, monkeypatch, headers
):
    raw_marker = b'"email":"raw-payload-marker@example.com" BROKEN JSON'
    body_reads = []
    json_parses = []
    log_messages = []

    async def forbidden_stream(_request):
        body_reads.append(True)
        raise AssertionError("request sai secret khong duoc doc body stream")
        yield b""  # pragma: no cover - giữ đây là async generator

    async def forbidden_json(_request):
        json_parses.append(True)
        raise AssertionError("request sai secret khong duoc parse JSON")

    def forbidden_service(_db, _request_data):
        raise AssertionError("request sai secret khong duoc goi order service")

    monkeypatch.setattr(webhooks.Request, "stream", forbidden_stream)
    monkeypatch.setattr(webhooks.Request, "json", forbidden_json)
    monkeypatch.setattr(
        webhooks.order_service, "apply_webhook_payment", forbidden_service
    )
    monkeypatch.setattr(webhooks, "log_to_file", log_messages.append)

    res = client.post("/api/orders/webhook", content=raw_marker, headers=headers)

    assert res.status_code == 401
    assert body_reads == []
    assert json_parses == []
    assert log_messages == []
    assert raw_marker.decode() not in "\n".join(log_messages)


def test_thieu_server_secret_khong_doc_parse_log_body_hay_goi_service(
    client, khong_co_secret, monkeypatch
):
    raw_marker = b'{"note":"SERVER-SECRET-MISSING" BROKEN JSON'
    body_reads = []
    json_parses = []
    log_messages = []

    async def forbidden_stream(_request):
        body_reads.append(True)
        raise AssertionError("thieu server secret khong duoc doc body stream")
        yield b""  # pragma: no cover

    async def forbidden_json(_request):
        json_parses.append(True)
        raise AssertionError("thieu server secret khong duoc parse JSON")

    def forbidden_service(_db, _request_data):
        raise AssertionError("thieu server secret khong duoc goi order service")

    monkeypatch.setattr(webhooks.Request, "stream", forbidden_stream)
    monkeypatch.setattr(webhooks.Request, "json", forbidden_json)
    monkeypatch.setattr(
        webhooks.order_service, "apply_webhook_payment", forbidden_service
    )
    monkeypatch.setattr(webhooks, "log_to_file", log_messages.append)

    res = client.post(
        "/api/orders/webhook",
        content=raw_marker,
        headers={"X-Webhook-Secret": "candidate-does-not-matter"},
    )

    assert res.status_code == 503
    assert body_reads == []
    assert json_parses == []
    assert log_messages == []
    assert raw_marker.decode() not in "\n".join(log_messages)


def test_body_vuot_limit_co_content_length_bi_chan_truoc_khi_doc_stream(
    client, webhook_secret, monkeypatch
):
    monkeypatch.setattr(webhooks, "ORDER_WEBHOOK_MAX_BODY_BYTES", 64)
    body_reads = []

    async def forbidden_stream(_request):
        body_reads.append(True)
        raise AssertionError("Content-Length vuot tran phai bi chan som")
        yield b""  # pragma: no cover

    def forbidden_service(_db, _request_data):
        raise AssertionError("body qua lon khong duoc goi order service")

    monkeypatch.setattr(webhooks.Request, "stream", forbidden_stream)
    monkeypatch.setattr(
        webhooks.order_service, "apply_webhook_payment", forbidden_service
    )
    body = b'{"padding":"' + (b"x" * 80) + b'"}'
    res = client.post(
        "/api/orders/webhook",
        content=body,
        headers={
            "X-Webhook-Secret": SECRET,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )

    assert res.status_code == 413
    assert body_reads == []


def test_body_json_dung_bang_limit_duoc_chap_nhan(
    client, webhook_secret, monkeypatch
):
    body = b'{"order_id":1,"amount":1}'
    monkeypatch.setattr(webhooks, "ORDER_WEBHOOK_MAX_BODY_BYTES", len(body))
    service_calls = []

    def fake_service(_db, request_data):
        service_calls.append(request_data)
        return {"paid": [], "unreconciled": [], "rejected": []}

    monkeypatch.setattr(webhooks.order_service, "apply_webhook_payment", fake_service)
    res = client.post(
        "/api/orders/webhook",
        content=body,
        headers={
            "X-Webhook-Secret": SECRET,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )

    assert res.status_code == 200
    assert service_calls == [{"order_id": 1, "amount": 1}]


def test_body_vuot_limit_khong_co_content_length_van_bi_chan_theo_stream(
    client, webhook_secret, monkeypatch
):
    monkeypatch.setattr(webhooks, "ORDER_WEBHOOK_MAX_BODY_BYTES", 64)
    seen_content_lengths = []
    original_stream = webhooks.Request.stream

    async def observed_stream(request):
        seen_content_lengths.append(request.headers.get("content-length"))
        async for chunk in original_stream(request):
            yield chunk

    def forbidden_service(_db, _request_data):
        raise AssertionError("body qua lon khong duoc goi order service")

    monkeypatch.setattr(webhooks.Request, "stream", observed_stream)
    monkeypatch.setattr(
        webhooks.order_service, "apply_webhook_payment", forbidden_service
    )
    body = b'{"padding":"' + (b"x" * 80) + b'"}'
    res = client.post(
        "/api/orders/webhook",
        content=iter((body[:31], body[31:])),
        headers={
            "X-Webhook-Secret": SECRET,
            "Content-Type": "application/json",
        },
    )

    assert res.status_code == 413
    assert seen_content_lengths
    assert all(value is None for value in seen_content_lengths)


def test_content_length_noi_nho_hon_that_van_bi_chan_theo_stream(
    client, webhook_secret, monkeypatch
):
    monkeypatch.setattr(webhooks, "ORDER_WEBHOOK_MAX_BODY_BYTES", 64)
    stream_calls = []
    original_stream = webhooks.Request.stream

    async def observed_stream(request):
        stream_calls.append(request.headers.get("content-length"))
        async for chunk in original_stream(request):
            yield chunk

    def forbidden_service(_db, _request_data):
        raise AssertionError("body qua lon khong duoc goi order service")

    monkeypatch.setattr(webhooks.Request, "stream", observed_stream)
    monkeypatch.setattr(
        webhooks.order_service, "apply_webhook_payment", forbidden_service
    )
    body = b'{"padding":"' + (b"x" * 80) + b'"}'
    res = client.post(
        "/api/orders/webhook",
        content=body,
        headers={
            "X-Webhook-Secret": SECRET,
            "Content-Type": "application/json",
            "Content-Length": "1",
        },
    )

    assert res.status_code == 413
    assert stream_calls
    assert all(value == "1" for value in stream_calls)


def test_route_log_webhook_chi_co_metadata_khong_co_du_lieu_client(
    client, webhook_secret, monkeypatch
):
    ctx, order_id = _tao_don(client)
    route_logs = []
    monkeypatch.setattr(webhooks, "log_to_file", route_logs.append)
    forbidden_values = (
        SECRET,
        "raw-payload-marker@example.com",
        "NGUYEN VAN RAW PAYLOAD",
        "ghi chu tuy y cua client",
        "0123456789",
        "FREE-FORM-TXN-ONE",
        "FREE-FORM-TXN-TWO",
    )
    common = {
        "content": f"ORDER{order_id}",
        "accountNumber": "0123456789",
        "email": "raw-payload-marker@example.com",
        "name": "NGUYEN VAN RAW PAYLOAD",
        "note": "ghi chu tuy y cua client",
    }

    first = client.post(
        "/api/orders/webhook",
        json={**common, "transferAmount": TONG_TIEN, "id": "FREE-FORM-TXN-ONE"},
        headers={"X-Webhook-Secret": SECRET},
    )
    second = client.post(
        "/api/orders/webhook",
        json={**common, "transferAmount": 1, "id": "FREE-FORM-TXN-TWO"},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert first.status_code == 200
    assert first.json()["order_ids"] == [order_id]
    assert second.status_code == 200

    assert len(route_logs) == 2
    assert all(
        re.fullmatch(r"ORDER WEBHOOK AUTHENTICATED body_bytes=\d+", message)
        for message in route_logs
    )
    for value in forbidden_values:
        assert value not in "\n".join(route_logs)


def test_dinh_dang_casso_danh_sach_giao_dich(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"data": [{"description": f"CK ORDER{order_id} noi dung", "amount": TONG_TIEN}]},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_dinh_dang_payos_ordercode(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"data": {"orderCode": order_id, "description": "", "amount": TONG_TIEN}},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


def test_dinh_dang_sepay_content(client, webhook_secret):
    ctx, order_id = _tao_don(client)
    res = client.post(
        "/api/orders/webhook",
        json={"content": f"ORDER{order_id}", "transferAmount": 100000},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert res.status_code == 200
    assert _trang_thai(client, ctx, order_id) == "PAID"


# --- Unit test cho bộ phân tích payload (không cần HTTP) ---
def test_extract_order_ids_cac_dinh_dang():
    assert payment_service.extract_order_ids({"order_id": 7}) == [7]
    assert payment_service.extract_order_ids({"data": [{"description": "ORDER12"}]}) == [12]
    assert payment_service.extract_order_ids({"content": "abc ORDER3 xyz"}) == [3]
    assert payment_service.extract_order_ids({"data": {"orderCode": 9, "description": ""}}) == [9]
    assert payment_service.extract_order_ids({}) == []
    assert payment_service.extract_order_ids({"note": "order55"}) == [55]  # fallback, khong phan biet hoa thuong


def test_build_qr_url_chua_ma_don():
    class _Shop:
        bank_code = "VCB"
        bank_account_no = "123"
        bank_account_name = "TEST"

    url = payment_service.build_qr_url(_Shop(), 150000.0, 42)
    assert "amount=150000" in url
    assert "addInfo=ORDER42" in url
