"""I03: SMTP failure must not leak OTP, recipients, or credentials."""
from __future__ import annotations

import logging

from fselling.core.config import SMTP_TIMEOUT_SECONDS
from fselling.services import email_service

# `conftest` thay hàm module bằng fake autouse để các test HTTP không gửi mail.
# Giữ tham chiếu này lúc collection để các test I03 gọi implementation thật.
SEND_OTP_EMAIL = email_service.send_otp_email


OTP = "otp-I03-741852"
RECIPIENT = "recipient-I03@example.test"
USERNAME = "user-I03@example.test"
PASSWORD = "password-I03-secret"
SUBJECT = "subject-I03-private"
BODY = "body-I03-private"
INVALID_PORT = "port-I03-invalid"
SENTINELS = (OTP, RECIPIENT, USERNAME, PASSWORD, SUBJECT, BODY, INVALID_PORT)


def _configure_smtp(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp-I03.example.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", USERNAME)
    monkeypatch.setenv("SMTP_PASSWORD", PASSWORD)


def _assert_no_secret_output(capsys, caplog) -> None:
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text
    for sentinel in SENTINELS:
        assert sentinel not in output


def test_missing_smtp_credentials_returns_false_without_connecting_or_leaking(
    monkeypatch, capsys, caplog
):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("SMTP_PORT", INVALID_PORT)

    def _must_not_connect(*_args, **_kwargs):
        raise AssertionError("SMTP must not be constructed without credentials")

    monkeypatch.setattr(email_service.smtplib, "SMTP", _must_not_connect)
    caplog.set_level(logging.WARNING, logger=email_service.__name__)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is False
    _assert_no_secret_output(capsys, caplog)
    assert "smtp_send_skipped_missing_credentials" in caplog.text


def test_invalid_smtp_port_returns_false_without_connecting_or_leaking(
    monkeypatch, capsys, caplog
):
    _configure_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", INVALID_PORT)

    def _must_not_connect(*_args, **_kwargs):
        raise AssertionError("SMTP must not be constructed with an invalid port")

    monkeypatch.setattr(email_service.smtplib, "SMTP", _must_not_connect)
    caplog.set_level(logging.WARNING, logger=email_service.__name__)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is False
    _assert_no_secret_output(capsys, caplog)
    assert caplog.messages == ["smtp_send_skipped_invalid_port"]


def test_smtp_constructor_failure_returns_false_without_leaking(
    monkeypatch, capsys, caplog
):
    _configure_smtp(monkeypatch)
    raw_error = RuntimeError(" ".join(SENTINELS))

    def _constructor_failure(*_args, **_kwargs):
        raise raw_error

    monkeypatch.setattr(email_service.smtplib, "SMTP", _constructor_failure)
    caplog.set_level(logging.WARNING, logger=email_service.__name__)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is False
    _assert_no_secret_output(capsys, caplog)
    assert "smtp_send_failed" in caplog.text


def test_smtp_send_failure_closes_connection_without_leaking(monkeypatch, capsys, caplog):
    _configure_smtp(monkeypatch)
    raw_error = RuntimeError(" ".join(SENTINELS))

    class SendFailingSMTP:
        instance = None

        def __init__(self, *_args, **_kwargs):
            self.quit_called = False
            self.close_called = False
            SendFailingSMTP.instance = self

        def starttls(self):
            pass

        def login(self, *_args):
            pass

        def sendmail(self, *_args):
            raise raw_error

        def quit(self):
            self.quit_called = True

        def close(self):
            self.close_called = True

    monkeypatch.setattr(email_service.smtplib, "SMTP", SendFailingSMTP)
    caplog.set_level(logging.WARNING, logger=email_service.__name__)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is False
    assert SendFailingSMTP.instance.quit_called is True
    _assert_no_secret_output(capsys, caplog)
    assert "smtp_send_failed" in caplog.text


def test_smtp_quit_failure_closes_connection_and_returns_false_without_leaking(
    monkeypatch, capsys, caplog
):
    _configure_smtp(monkeypatch)
    raw_error = RuntimeError(" ".join(SENTINELS))

    class QuitFailingSMTP:
        instance = None

        def __init__(self, *_args, **_kwargs):
            self.close_called = False
            QuitFailingSMTP.instance = self

        def starttls(self):
            pass

        def login(self, *_args):
            pass

        def sendmail(self, *_args):
            pass

        def quit(self):
            raise raw_error

        def close(self):
            self.close_called = True

    monkeypatch.setattr(email_service.smtplib, "SMTP", QuitFailingSMTP)
    caplog.set_level(logging.WARNING, logger=email_service.__name__)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is False
    assert QuitFailingSMTP.instance.close_called is True
    _assert_no_secret_output(capsys, caplog)
    assert "smtp_cleanup_failed" in caplog.text


def test_smtp_success_passes_timeout_and_closes_connection(monkeypatch):
    _configure_smtp(monkeypatch)

    class SuccessfulSMTP:
        instance = None

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.closed = False
            SuccessfulSMTP.instance = self

        def starttls(self):
            pass

        def login(self, *_args):
            pass

        def sendmail(self, *_args):
            pass

        def quit(self):
            self.closed = True

    monkeypatch.setattr(email_service.smtplib, "SMTP", SuccessfulSMTP)

    assert SEND_OTP_EMAIL(RECIPIENT, OTP, SUBJECT) is True
    assert SuccessfulSMTP.instance.args == ("smtp-I03.example.test", 2525)
    assert SuccessfulSMTP.instance.kwargs == {"timeout": SMTP_TIMEOUT_SECONDS}
    assert SuccessfulSMTP.instance.closed is True
