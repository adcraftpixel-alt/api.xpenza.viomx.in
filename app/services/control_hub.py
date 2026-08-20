"""
Rupexi → VIOMX Control Hub client.

The Control Hub is the source of truth for plans/pricing and per-plan caps.
Rupexi pulls them here and reports purchases so buyers appear in the Hub.
All calls are best-effort: the Hub being down must never break Rupexi.

Requests are HMAC-signed (app/core/signing.py) instead of sending
CONTROL_HUB_KEY itself as a bearer value: X-Product-Code identifies which
product's key the Hub should verify against, and X-Signature proves
possession of that key without ever putting it on the wire.
"""
import json
import logging

import httpx

from app.config import settings
from app.core import signing

log = logging.getLogger("rupexi.control_hub")

_TIMEOUT = 8.0


def is_configured() -> bool:
    return bool(settings.CONTROL_HUB_URL and settings.CONTROL_HUB_KEY)


def _signed_headers(body: bytes) -> dict:
    return {
        "X-Product-Code": settings.PRODUCT_CODE,
        "Content-Type": "application/json",
        **signing.signed_headers(settings.CONTROL_HUB_KEY, body),
    }


def _get(path: str) -> httpx.Response:
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}{path}"
    return httpx.get(url, headers=_signed_headers(b""), timeout=_TIMEOUT)


def _post(path: str, payload: dict) -> httpx.Response:
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}{path}"
    body = json.dumps(payload).encode()
    return httpx.post(url, headers=_signed_headers(body), content=body, timeout=_TIMEOUT)


def fetch_plans() -> list | None:
    """GET the Hub's plans + caps for this product. Returns list or None on failure."""
    if not is_configured():
        return None
    try:
        resp = _get("/ingest/plans")
        resp.raise_for_status()
        body = resp.json()
        return body.get("plans", [])
    except Exception as e:  # network / auth / parse
        log.warning("control_hub.fetch_plans failed: %s", e)
        return None


def register_tenant(external_user_id: str, email: str, name: str | None = None,
                     phone: str | None = None) -> bool:
    """Register (or just confirm) this user as a Tenant in the Hub as soon as
    they sign up/log in — independent of whether they've purchased anything
    yet, so the Hub has visibility into every registered user, not just
    paying ones. Best-effort and idempotent: safe to call on every login."""
    if not is_configured():
        return False
    try:
        resp = _post("/ingest/register", {
            "external_user_id": external_user_id,
            "email": email,
            "name": name,
            "phone": phone,
        })
        resp.raise_for_status()
        return True
    except Exception as e:
        log.warning("control_hub.register_tenant failed: %s", e)
        return False


def report_purchase(payload: dict) -> bool:
    """POST a purchase to the Hub ingest endpoint. Best-effort."""
    if not is_configured():
        return False
    try:
        resp = _post("/ingest/purchase", payload)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.warning("control_hub.report_purchase failed: %s", e)
        return False


class HubNotConfigured(Exception):
    """Raised when CONTROL_HUB_URL/CONTROL_HUB_KEY are unset."""


class HubRequestError(Exception):
    """Raised when the Hub rejects or fails a subscription request."""


def create_subscription(
    plan_name: str,
    start_at: int,
    external_user_id: str,
    notify_email: str | None = None,
    notify_phone: str | None = None,
) -> dict:
    """Ask the Hub to create a Razorpay recurring Subscription (mandate +
    auto-debit) on our behalf — the Razorpay secret lives only in the Hub's
    database, never here. Returns the Hub's `data` dict (subscription_id,
    key_id, short_url, status). Unlike fetch_plans/report_purchase this is
    NOT best-effort: without a subscription there is nothing to authorise on
    the mobile side, so callers must handle the raised exceptions.

    [external_user_id] lets the Hub attribute this Subscription to the right
    Tenant the moment it's created, rather than only finding out via a later
    report_purchase() call (which depends on a webhook actually arriving).
    """
    if not is_configured():
        raise HubNotConfigured("CONTROL_HUB_URL/CONTROL_HUB_KEY are not configured")
    body = {
        "plan_name": plan_name,
        "start_at": start_at,
        "external_user_id": external_user_id,
        "notify_email": notify_email,
        "notify_phone": notify_phone,
    }
    try:
        resp = _post("/internal/create-subscription", body)
    except Exception as e:
        raise HubRequestError(f"Could not reach Control Hub: {e}") from e
    if resp.status_code >= 400:
        raise HubRequestError(f"Control Hub error {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if payload.get("status") != "created":
        raise HubRequestError(payload.get("detail") or "Control Hub could not create the subscription")
    return payload.get("data") or {}


def cancel_subscription(subscription_id: str, at_cycle_end: bool = True) -> dict:
    """Ask the Hub to cancel a Razorpay recurring Subscription it owns on our
    behalf. Not best-effort — a failure here must surface to the caller."""
    if not is_configured():
        raise HubNotConfigured("CONTROL_HUB_URL/CONTROL_HUB_KEY are not configured")
    body = {"subscription_id": subscription_id, "at_cycle_end": at_cycle_end}
    try:
        resp = _post("/internal/cancel-subscription", body)
    except Exception as e:
        raise HubRequestError(f"Could not reach Control Hub: {e}") from e
    if resp.status_code >= 400:
        raise HubRequestError(f"Control Hub error {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if payload.get("status") != "cancelled":
        raise HubRequestError(payload.get("detail") or "Control Hub could not cancel the subscription")
    return payload.get("data") or {}
