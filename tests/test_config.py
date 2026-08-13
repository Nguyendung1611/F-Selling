"""Configuration precedence and test isolation."""

import os

import pytest

from fselling.core import config
from fselling.services import qr_sales_service, qr_webhook_service


def test_explicit_environment_takes_precedence_over_dotenv():
    assert config.SECRET_KEY == "test-secret-key-chi-dung-cho-test"
    assert os.environ["ADMIN_INITIAL_PASSWORD"] == "AdminTest@2026"


def test_test_log_is_outside_project():
    assert config.LOG_FILE == os.environ["LOG_FILE"]
    assert not config.LOG_FILE.endswith("python_app\\request_log.txt")


def test_qr_sales_runtime_defaults_off_and_has_no_callable_adapter():
    runtime = qr_sales_service.get_runtime()

    assert config.QR_SALES_MODE == "OFF"
    assert runtime.mode == "OFF"
    assert runtime.report_only_mock is False
    assert runtime.render_available is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OFF", "OFF"),
        (" off ", "OFF"),
        ("REPORT_ONLY", "REPORT_ONLY"),
        (" report_only ", "REPORT_ONLY"),
        ("ENFORCE", "OFF"),
        ("", "OFF"),
        ("1", "OFF"),
    ],
)
def test_qr_sales_mode_allowlist_is_strict_and_invalid_values_fail_safe(
    monkeypatch, raw, expected
):
    monkeypatch.setenv("QR_SALES_MODE", raw)

    assert config._qr_sales_mode_from_env() == expected


def test_report_only_environment_alone_cannot_enable_issuance(monkeypatch):
    monkeypatch.setattr(config, "QR_SALES_MODE", "REPORT_ONLY")

    runtime = qr_sales_service.get_runtime()

    assert runtime.mode == "REPORT_ONLY"
    assert runtime.report_only_mock is False
    assert runtime.render_available is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OFF", "OFF"),
        (" report_only ", "REPORT_ONLY"),
        ("ENFORCE", "OFF"),
        ("1", "OFF"),
        ("", "OFF"),
    ],
)
def test_qr_webhook_mode_allowlist_is_strict(monkeypatch, raw, expected):
    monkeypatch.setenv("QR_WEBHOOK_MODE", raw)
    assert config._qr_webhook_mode_from_env() == expected


def test_report_only_environment_alone_cannot_enable_webhook(monkeypatch):
    monkeypatch.setattr(config, "QR_WEBHOOK_MODE", "REPORT_ONLY")
    runtime = qr_webhook_service.get_runtime()
    assert runtime.mode == "REPORT_ONLY"
    assert runtime.enabled_test_adapter is False
    assert isinstance(runtime.adapter, qr_webhook_service.DisabledWebhookAdapter)


@pytest.mark.parametrize("raw", ["khong-phai-so", "0", "-17"])
def test_positive_int_env_gia_tri_loi_fallback_khong_doi_global_constant(
    monkeypatch, raw
):
    name = "FSELLING_TEST_POSITIVE_INT"
    default = 4096
    configured_limit = config.ORDER_WEBHOOK_MAX_BODY_BYTES
    monkeypatch.setenv(name, raw)

    assert config._positive_int_env(name, default) == default
    assert config.ORDER_WEBHOOK_MAX_BODY_BYTES == configured_limit
