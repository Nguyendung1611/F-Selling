"""Configuration precedence and test isolation."""

import os

from fselling.core import config


def test_explicit_environment_takes_precedence_over_dotenv():
    assert config.SECRET_KEY == "test-secret-key-chi-dung-cho-test"
    assert os.environ["ADMIN_INITIAL_PASSWORD"] == "AdminTest@2026"


def test_test_log_is_outside_project():
    assert config.LOG_FILE == os.environ["LOG_FILE"]
    assert not config.LOG_FILE.endswith("python_app\\request_log.txt")
