"""SMS delivery via the Twilio REST API.

Uses the same endpoint as:

    curl 'https://api.twilio.com/2010-04-01/Accounts/<SID>/Messages.json' -X POST \
        --data-urlencode 'To=+1...' \
        --data-urlencode 'From=+1...' \
        --data-urlencode 'Body=...' \
        -u <SID>:<AuthToken>

Credentials come from environment (see app/config.py) — never hardcode them.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TWILIO_BASE = "https://api.twilio.com/2010-04-01"


class SMSNotConfigured(Exception):
    """Raised when Twilio credentials are missing."""


class SMSDeliveryError(Exception):
    """Raised when Twilio rejects the message."""


def sms_configured() -> bool:
    """True when we have enough credentials to actually send an SMS."""
    return bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and (settings.TWILIO_FROM_NUMBER or settings.TWILIO_MESSAGING_SERVICE_SID)
    )


def send_sms(to: str, body: str) -> str:
    """Send an SMS via Twilio and return the message SID.

    Raises ``SMSNotConfigured`` if credentials are missing, or
    ``SMSDeliveryError`` if Twilio returns an error.
    """
    if not sms_configured():
        raise SMSNotConfigured("Twilio credentials are not configured")

    url = f"{TWILIO_BASE}/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    data = {"To": to, "Body": body}
    if settings.TWILIO_MESSAGING_SERVICE_SID:
        data["MessagingServiceSid"] = settings.TWILIO_MESSAGING_SERVICE_SID
    else:
        data["From"] = settings.TWILIO_FROM_NUMBER

    try:
        resp = httpx.post(
            url,
            data=data,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise SMSDeliveryError(f"Twilio request failed: {e}") from e

    if resp.status_code >= 300:
        # Twilio returns a JSON body with `message` and `code` on error.
        detail = resp.text
        try:
            payload = resp.json()
            detail = payload.get("message", detail)
        except Exception:
            pass
        raise SMSDeliveryError(f"Twilio error {resp.status_code}: {detail}")

    sid = ""
    try:
        sid = resp.json().get("sid", "")
    except Exception:
        pass
    logger.info(f"[SMS] sent to {to} (sid={sid})")
    return sid
