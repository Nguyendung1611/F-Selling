"""Gửi email OTP qua SMTP. Không cấu hình SMTP -> in OTP ra console (như code cũ)."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..core.i18n import get_locale, tr

DEFAULT_SUBJECT = "F-Selling: Mã xác minh của bạn"


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
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        print("\n" + "=" * 80)
        print(f" WARNING: SMTP EMAIL NOT CONFIGURRED. BACKUP OTP FOR {email_to}: {otp_code}")
        print("=" * 80 + "\n")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = email_to
        msg["Subject"] = tr(subject)
        msg.attach(MIMEText(_build_body(otp_code), "html", "utf-8"))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, email_to, msg.as_string())
        server.quit()
        return True
    except (smtplib.SMTPException, OSError) as e:
        print(f"Error sending mail to {email_to}: {e}")
        print("\n" + "=" * 80)
        print(f" BACKUP OTP FOR {email_to}: {otp_code} (Mail sending failed: {e})")
        print("=" * 80 + "\n")
        return False
