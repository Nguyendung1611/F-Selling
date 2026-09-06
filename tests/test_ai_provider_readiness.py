"""P0B readiness: pinned Gemini, atomic cost gate, circuit and safe telemetry."""
from __future__ import annotations

import json
import threading

import pytest

from conftest import auth, seller_with_shop
from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import assistant_service, gemini_service, subscription_service


@pytest.fixture(autouse=True)
def _reset_circuit():
    gemini_service._reset_circuit_for_tests()
    yield
    gemini_service._reset_circuit_for_tests()


def test_model_is_exact_stable_and_request_omits_deprecated_sampling(monkeypatch):
    captured = {}

    class Response:
        def read(self):
            return json.dumps({
                "candidates": [{"content": {"parts": [{
                    "text": '{"y_dinh":"DOANH_THU","khoang":"HOM_NAY"}'
                }]}}]
            }).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(gemini_service, "GEMINI_ENABLED", True)
    monkeypatch.setattr(gemini_service, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(gemini_service.urllib.request, "urlopen", fake_urlopen)
    gemini_service._reset_circuit_for_tests()

    result = gemini_service.phan_loai(
        "doanh số bữa ni", ["DOANH_THU"], ["HOM_NAY"]
    )

    assert result == ("DOANH_THU", "HOM_NAY")
    assert gemini_service.GEMINI_MODEL == "gemini-3.5-flash-lite"
    generation = captured["body"]["generationConfig"]
    assert "temperature" not in generation
    assert "topP" not in generation
    assert "topK" not in generation
    assert generation["maxOutputTokens"] == 40
    assert captured["timeout"] == gemini_service.GEMINI_TIMEOUT_SECONDS


def test_alias_or_preview_model_fails_closed(monkeypatch):
    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(gemini_service, "GEMINI_ENABLED", True)
    for model in (
        "gemini-flash-lite-latest",
        "gemini-3.1-flash-lite-preview",
        "gemini-3.7-flash",
    ):
        monkeypatch.setattr(gemini_service, "GEMINI_MODEL", model)
        assert gemini_service.dang_bat() is False


def test_provider_boundary_drops_names_phones_emails_and_unknown_tokens():
    minimized = gemini_service._minimize_question(
        "Bữa ni quán thu vô của khách Nguyễn Văn A 0901234567 a@example.com SKU-X9?"
    )
    assert minimized
    assert "bua ni quan thu vo cua khach" == minimized
    for forbidden in ("nguyen", "van", "0901234567", "example", "sku", "x9"):
        assert forbidden not in minimized


def test_monthly_global_reservation_is_atomic_across_threads(client, monkeypatch):
    ctx = seller_with_shop(client)
    session = SessionLocal()
    try:
        session.query(models.AssistantAiUsage).delete()
        session.commit()
    finally:
        session.close()
    monkeypatch.setattr(assistant_service, "GEMINI_RESERVED_VND_PER_CALL", 25)
    monkeypatch.setattr(assistant_service, "GEMINI_MONTHLY_CAP_VND", 25)
    monkeypatch.setattr(assistant_service, "GEMINI_SHOP_MONTHLY_CAP_VND", 25)
    monkeypatch.setattr(assistant_service, "GEMINI_DEGRADE_PERCENT", 100)
    monkeypatch.setattr(assistant_service, "GEMINI_TRAN_MOI_NGAY", 99)
    barrier = threading.Barrier(6)
    results = []
    lock = threading.Lock()

    def reserve():
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            value = assistant_service._reserve_provider_call(session, ctx["shop_id"])
            with lock:
                results.append(value)
        finally:
            session.close()

    threads = [threading.Thread(target=reserve) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not any(thread.is_alive() for thread in threads)
    assert results.count(True) == 1
    assert results.count(False) == 5
    session = SessionLocal()
    try:
        used, cap = assistant_service._monthly_budget_vnd(session)
        assert (used, cap) == (25, 25)
    finally:
        session.close()


def test_circuit_opens_after_consecutive_failures_without_more_network(monkeypatch):
    calls = {"count": 0}

    def fail(*args, **kwargs):
        calls["count"] += 1
        raise TimeoutError("fake timeout")

    monkeypatch.setattr(gemini_service, "GEMINI_API_KEY", "fake")
    monkeypatch.setattr(gemini_service, "GEMINI_ENABLED", True)
    monkeypatch.setattr(gemini_service, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setattr(gemini_service, "GEMINI_CIRCUIT_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(gemini_service, "GEMINI_CIRCUIT_COOLDOWN_SECONDS", 60)
    monkeypatch.setattr(gemini_service.urllib.request, "urlopen", fail)
    gemini_service._reset_circuit_for_tests()

    for _ in range(3):
        assert gemini_service.phan_loai(
            "bua ni quan thu vao", ["DOANH_THU"], ["HOM_NAY"]
        ) is None

    assert calls["count"] == 2
    assert gemini_service.dang_bat() is True
    assert gemini_service.san_sang() is False


def test_provider_telemetry_is_fixed_and_never_stores_question(
    client, monkeypatch
):
    ctx = seller_with_shop(client)
    marker = "bữa ni quán thu vô của khách Nguyễn Văn 0900000000"
    monkeypatch.setattr(subscription_service, "require_pro", lambda *args, **kwargs: {})
    monkeypatch.setattr(gemini_service, "dang_bat", lambda: True)
    monkeypatch.setattr(gemini_service, "san_sang", lambda: True, raising=False)
    monkeypatch.setattr(
        gemini_service,
        "phan_loai",
        lambda *args, **kwargs: (assistant_service.Y_DINH_DOANH_THU, "HOM_NAY"),
    )

    response = client.post(
        f"/api/assistant/{ctx['shop_id']}",
        json={"cau_hoi": marker},
        headers=auth(ctx["token"]),
    )

    assert response.status_code == 200
    session = SessionLocal()
    try:
        rows = session.query(models.SystemLog).filter(
            models.SystemLog.shop_id == ctx["shop_id"],
            models.SystemLog.action == "ASSISTANT_AI_CALL",
        ).all()
        assert len(rows) == 1
        assert marker not in (rows[0].details or "")
        assert "model=gemini-3.5-flash-lite" in rows[0].details
        assert "outcome=SUCCESS" in rows[0].details
        assert "latency_bucket=" in rows[0].details
    finally:
        session.close()
