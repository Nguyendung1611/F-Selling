"""Gửi email OTP qua SMTP mà không ghi dữ liệu nhạy cảm vào log."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..core.config import SMTP_TIMEOUT_SECONDS
from ..core.i18n import get_locale, tr

DEFAULT_SUBJECT = "F-Selling: Mã xác minh của bạn"
logger = logging.getLogger(__name__)


def _build_body(otp_code: str) -> str:
    return f"""
        <html lang="{get_locale()}">
        <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2 style="color: #4F46E5;">{tr("Mã xác minh F-Selling")}</h2>
            <p>{tr("Chào bạn,")}</p>
            <p>{tr("Mã xác minh (OTP) của bạn là:")}</p>
            <div style="font-size: 24px; font-weight: bold; background: #F3F4F6; padding: 10px 20px; border-radius: 8px; display: inline-block; letter-spacing: 2px; color: #4F46E5; margin: 15px 0;">
                {otp_code}
            </div>
            <p>{tr("Mã này có hiệu lực trong vòng 15 phút. Vui lòng không chia sẻ mã này với bất kỳ ai.")}</p>
            <hr style="border: none; border-top: 1px solid #E5E7EB; margin-top: 30px;">
            <p style="font-size: 12px; color: #9CA3AF;">{tr("Hệ thống F-Selling - Ứng dụng bán hàng thông minh.")}</p>
        </body>
        </html>
        """


def send_otp_email(email_to: str, otp_code: str, subject: str = DEFAULT_SUBJECT) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        logger.warning("smtp_send_skipped_missing_credentials")
        return False

    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except (TypeError, ValueError):
        logger.warning("smtp_send_skipped_invalid_port")
        return False

    server = None
    sent = False
    cleanup_ok = True
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = email_to
        msg["Subject"] = tr(subject)
        msg.attach(MIMEText(_build_body(otp_code), "html", "utf-8"))

        # timeout BẮT BUỘC: không có nó thì smtplib chờ vô hạn khi máy chủ mail
        # không phản hồi, và mỗi lần chờ giữ một luồng của threadpool FastAPI.
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, email_to, msg.as_string())
        sent = True
    except Exception:
        # Exception SMTP có thể chứa recipient, username, credential hoặc body.
        # Chỉ ghi mã sự kiện cố định, tuyệt đối không log exception thô.
        logger.warning("smtp_send_failed")
    finally:
        if server is not None:
            # `quit()` cũng đi qua mạng nên cũng hỏng được; đóng socket kiểu gì
            # cũng phải xảy ra, nếu không thì rò rỉ kết nối sau mỗi lần lỗi.
            try:
                server.quit()
            except Exception:
                cleanup_ok = False
                logger.warning("smtp_cleanup_failed")
                try:
                    server.close()
                except Exception:
                    # Không có dữ liệu nào an toàn để lấy từ exception cleanup.
                    pass

    return sent and cleanup_ok
