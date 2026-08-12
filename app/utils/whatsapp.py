"""OTP delivery via WhatsApp Business Cloud API (Meta Graph API).

Sends the pre-approved ``rupexi_otp`` template, substituting the live code into
both the body and the "Copy code" button — WhatsApp does not allow free-form
template text, only declared variables:

    curl -X POST 'https://graph.facebook.com/v25.0/<PHONE_NUMBER_ID>/messages' \
        -H 'Authorization: Bearer <ACCESS_TOKEN>' -H 'Content-Type: application/json' \
        -d '{"messaging_product":"whatsapp","to":"+919876543210","type":"template",
             "template":{"name":"rupexi_otp","language":{"code":"en"},"components":[...]}}'

The public interface (`whatsapp_configured`, `send_whatsapp_otp`,
`WhatsAppNotConfigured`, `WhatsAppDeliveryError`) mirrors `app/utils/sms.py` so
OTP generation/verification in `app/api/v1/auth/service.py` doesn't need to
know which channel is behind it.

Credentials come from environment (see app/config.py) — never hardcode them.
"""
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"

# Graph API wants an international number; a leading '+' is accepted and used
# in Meta's own examples, so we normalise to that rather than bare digits.
_NON_DIGITS = re.compile(r"\D")


class WhatsAppNotConfigured(Exception):
    """Raised when WhatsApp Cloud API credentials are missing."""


class WhatsAppDeliveryError(Exception):
    """Raised when the Graph API rejects the message."""


def whatsapp_configured() -> bool:
    """True when we have enough credentials to actually send a WhatsApp message."""
    return bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID)


def _to_whatsapp_number(phone: str, default_country_code: str = "91") -> str:
    """Normalise to Graph API's expected E.164-with-'+' format.

    Accepts '+919876543210', '919876543210' or a bare '9876543210'.
    """
    digits = _NON_DIGITS.sub("", phone or "")
    if not digits:
        return ""
    # A bare national number (10 digits in India) needs the country code.
    if len(digits) <= 10:
        digits = f"{default_country_code}{digits}"
    return f"+{digits}"


def send_whatsapp_otp(to: str, otp: str) -> str:
    """Send [otp] to [to] via the ``rupexi_otp`` WhatsApp template.

    [to] and the OTP text are the only two dynamic pieces — everything else in
    the template payload is fixed. The OTP is substituted into both the body
    parameter and the "copy code" button parameter, matching the approved
    template's variables.

    Raises ``WhatsAppNotConfigured`` if credentials are missing, or
    ``WhatsAppDeliveryError`` if the Graph API returns an error.
    Returns the WhatsApp message id on success.
    """
    if not whatsapp_configured():
        raise WhatsAppNotConfigured(
            "WhatsApp credentials are not configured "
            "(need WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)"
        )

    to_number = _to_whatsapp_number(to)
    if not to_number:
        raise WhatsAppDeliveryError(f"Invalid destination number: {to!r}")

    url = (
        f"{GRAPH_API_BASE}/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_TEMPLATE_NAME,
            "language": {"code": settings.WHATSAPP_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": otp}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": otp}],
                },
            ],
        },
    }

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise WhatsAppDeliveryError(f"WhatsApp request failed: {e}") from e

    detail = resp.text
    payload_out = {}
    try:
        payload_out = resp.json()
    except Exception:
        pass

    if resp.status_code >= 300 or (payload_out or {}).get("error"):
        err = (payload_out or {}).get("error", {})
        raise WhatsAppDeliveryError(
            f"WhatsApp error {resp.status_code}: {err.get('message', detail)}"
        )

    messages = (payload_out or {}).get("messages") or []
    message_id = messages[0].get("id", "") if messages else ""
    logger.info(f"[WhatsApp] OTP sent to {to_number} (message_id={message_id})")
    return message_id
