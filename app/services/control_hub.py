"""
Rupexi → VIOMX Control Hub client.

The Control Hub is the source of truth for plans/pricing and per-plan caps.
Rupexi pulls them here and reports purchases so buyers appear in the Hub.
All calls are best-effort: the Hub being down must never break Rupexi.
"""
import logging

import httpx

from app.config import settings

log = logging.getLogger("rupexi.control_hub")

_TIMEOUT = 8.0


def is_configured() -> bool:
    return bool(settings.CONTROL_HUB_URL and settings.CONTROL_HUB_KEY)


def _headers() -> dict:
    return {"X-Product-Key": settings.CONTROL_HUB_KEY}


def fetch_plans() -> list | None:
    """GET the Hub's plans + caps for this product. Returns list or None on failure."""
    if not is_configured():
        return None
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}/ingest/plans"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        return body.get("plans", [])
    except Exception as e:  # network / auth / parse
        log.warning("control_hub.fetch_plans failed: %s", e)
        return None


def report_purchase(payload: dict) -> bool:
    """POST a purchase to the Hub ingest endpoint. Best-effort."""
    if not is_configured():
        return False
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}/ingest/purchase"
    try:
        resp = httpx.post(url, headers=_headers(), json=payload, timeout=_TIMEOUT)
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
    notify_email: str | None = None,
    notify_phone: str | None = None,
) -> dict:
    """Ask the Hub to create a Razorpay recurring Subscription (mandate +
    auto-debit) on our behalf — the Razorpay secret lives only in the Hub's
    database, never here. Returns the Hub's `data` dict (subscription_id,
    key_id, short_url, status). Unlike fetch_plans/report_purchase this is
    NOT best-effort: without a subscription there is nothing to authorise on
    the mobile side, so callers must handle the raised exceptions.
    """
    if not is_configured():
        raise HubNotConfigured("CONTROL_HUB_URL/CONTROL_HUB_KEY are not configured")
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}/internal/create-subscription"
    body = {
        "plan_name": plan_name,
        "start_at": start_at,
        "notify_email": notify_email,
        "notify_phone": notify_phone,
    }
    try:
        resp = httpx.post(url, headers=_headers(), json=body, timeout=_TIMEOUT)
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
    url = f"{settings.CONTROL_HUB_URL.rstrip('/')}/internal/cancel-subscription"
    body = {"subscription_id": subscription_id, "at_cycle_end": at_cycle_end}
    try:
        resp = httpx.post(url, headers=_headers(), json=body, timeout=_TIMEOUT)
    except Exception as e:
        raise HubRequestError(f"Could not reach Control Hub: {e}") from e
    if resp.status_code >= 400:
        raise HubRequestError(f"Control Hub error {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if payload.get("status") != "cancelled":
        raise HubRequestError(payload.get("detail") or "Control Hub could not cancel the subscription")
    return payload.get("data") or {}
