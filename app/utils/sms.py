"""SMS delivery via MSG91 (India-first A2P provider).

Replaces Twilio: cheaper for INR volume, and MSG91 handles the TRAI/DLT
registration Indian carriers require, which Twilio pushes back onto us.

Uses the v5 Flow API, which sends a pre-registered DLT template with variables
substituted — India does not permit free-form A2P text:

    curl -X POST 'https://control.msg91.com/api/v5/flow/' \
        -H 'authkey: <AUTH_KEY>' -H 'Content-Type: application/json' \
        -d '{"template_id":"<ID>","recipients":[{"mobiles":"919876543210","OTP":"123456"}]}'

The public interface (`sms_configured`, `send_sms`, `SMSNotConfigured`,
`SMSDeliveryError`) is unchanged, so the OTP generation/verification in
`app/api/v1/auth/service.py` keeps working untouched.

Credentials come from environment (see app/config.py) — never hardcode them.
"""
import logging
import re
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MSG91_FLOW_URL = "https://control.msg91.com/api/v5/flow/"

# MSG91 wants a bare international number: country code + subscriber, no '+'.
_NON_DIGITS = re.compile(r"\D")


class SMSNotConfigured(Exception):
    """Raised when MSG91 credentials are missing."""


class SMSDeliveryError(Exception):
    """Raised when MSG91 rejects the message."""


def sms_configured() -> bool:
    """True when we have enough credentials to actually send an SMS.

    The DLT template is as mandatory as the auth key — MSG91 rejects the
    request without one, so treat a missing template as "not configured"
    rather than letting every send fail at runtime.
    """
    return bool(settings.MSG91_AUTH_KEY and settings.MSG91_TEMPLATE_ID)


def _to_msg91_mobile(phone: str, default_country_code: str = "91") -> str:
    """Normalise to MSG91's format: digits only, including country code.

    Accepts '+919876543210', '919876543210' or a bare '9876543210'.
    """
    digits = _NON_DIGITS.sub("", phone or "")
    if not digits:
        return digits
    # A bare national number (10 digits in India) needs the country code.
    if len(digits) <= 10:
        return f"{default_country_code}{digits}"
    return digits


def send_sms(
    to: str,
    body: str,
    otp: Optional[str] = None,
    template_id: Optional[str] = None,
) -> str:
    """Send an SMS via MSG91 and return the request id.

    [body] is kept for interface compatibility and logging. MSG91 sends the
    pre-approved DLT template, not arbitrary text, so the code itself is passed
    as the ``OTP`` template variable. When [otp] is not supplied it is
    extracted from [body], which keeps existing callers working unchanged.

    Raises ``SMSNotConfigured`` if credentials are missing, or
    ``SMSDeliveryError`` if MSG91 returns an error.
    """
    if not sms_configured():
        raise SMSNotConfigured(
            "MSG91 credentials are not configured "
            "(need MSG91_AUTH_KEY and MSG91_TEMPLATE_ID)"
        )

    mobile = _to_msg91_mobile(to)
    if not mobile:
        raise SMSDeliveryError(f"Invalid destination number: {to!r}")

    if otp is None:
        # Callers pass a rendered string like "Rupexi OTP: 123456. Valid for…".
        match = re.search(r"\b(\d{4,8})\b", body or "")
        otp = match.group(1) if match else ""

    recipient = {"mobiles": mobile}
    if otp:
        # Must match the variable name in the registered DLT template.
        recipient["OTP"] = otp

    payload = {
        "template_id": template_id or settings.MSG91_TEMPLATE_ID,
        "recipients": [recipient],
    }
    if settings.MSG91_SENDER_ID:
        payload["sender"] = settings.MSG91_SENDER_ID

    try:
        resp = httpx.post(
            MSG91_FLOW_URL,
            json=payload,
            headers={
                "authkey": settings.MSG91_AUTH_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise SMSDeliveryError(f"MSG91 request failed: {e}") from e

    detail = resp.text
    payload_out = {}
    try:
        payload_out = resp.json()
        detail = payload_out.get("message", detail)
    except Exception:
        pass

    # MSG91 returns HTTP 200 with {"type":"error"} for business errors such as
    # an unknown template or exhausted credits, so the status code alone is not
    # enough to call it a success.
    if resp.status_code >= 300 or payload_out.get("type") == "error":
        raise SMSDeliveryError(f"MSG91 error {resp.status_code}: {detail}")

    request_id = payload_out.get("request_id", "") if payload_out else ""
    logger.info(f"[SMS] sent to {mobile} via MSG91 (request_id={request_id})")
    return request_id
