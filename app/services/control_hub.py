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
