"""Configuration precedence and test isolation."""

import os

import pytest

from fselling.core import config


def test_explicit_environment_takes_precedence_over_dotenv():
    assert config.SECRET_KEY == "test-secret-key-chi-dung-cho-test"
    assert os.environ["ADMIN_INITIAL_PASSWORD"] == "AdminTest@2026"


def test_test_log_is_outside_project():
    assert config.LOG_FILE == os.environ["LOG_FILE"]
    assert not config.LOG_FILE.endswith("python_app\\request_log.txt")


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
