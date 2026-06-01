import logging
from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, html_content: str, plain_text: str = "") -> bool:
    """Send an email via SendGrid. Falls back to logging if key is missing."""
    if not settings.SENDGRID_API_KEY:
        logger.warning(f"[EMAIL STUB] To: {to_email} | Subject: {subject}")
        logger.debug(f"[EMAIL STUB] Body: {plain_text or html_content}")
        return True

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email="noreply@aifinanceos.com",
            to_emails=to_email,
            subject=subject,
            html_content=html_content,
            plain_text_content=plain_text,
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Email sent to {to_email}, status: {response.status_code}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_otp_email(to_email: str, otp: str) -> bool:
    subject = "Your OTP for AI Finance OS"
    html = f"""
    <h2>Your OTP Code</h2>
    <p>Your one-time password is: <strong style="font-size:24px">{otp}</strong></p>
    <p>This code expires in 5 minutes.</p>
    """
    return send_email(to_email, subject, html, f"Your OTP is: {otp}")


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    subject = "Reset your AI Finance OS password"
    html = f"""
    <h2>Password Reset</h2>
    <p>Click the link below to reset your password:</p>
    <a href="{reset_url}">{reset_url}</a>
    <p>This link expires in 1 hour. If you did not request this, ignore this email.</p>
    """
    return send_email(to_email, subject, html, f"Reset password: {reset_url}")
