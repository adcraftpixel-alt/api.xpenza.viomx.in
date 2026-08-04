"""Shared Firebase Admin SDK bootstrap.

Two subsystems need an initialised Firebase app:

* ``app.utils.fcm``            — push notifications
* ``app.api.v1.auth.service``  — phone-auth ID-token verification

``firebase_admin.initialize_app()`` raises if called twice, so every caller must
go through :func:`get_firebase_app` rather than initialising on its own.

Returns ``None`` (never raises) when ``FIREBASE_SERVICE_ACCOUNT`` is unset, so
local dev and tests keep working without credentials.
"""

import json
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_app: Optional[Any] = None
_init_failed = False


def firebase_configured() -> bool:
    """True when a service-account JSON has been supplied."""
    from app.config import settings

    creds = getattr(settings, "FIREBASE_SERVICE_ACCOUNT", "") or ""
    if not isinstance(creds, str):
        return bool(creds)
    return creds.strip() not in ("", "{}")


def _load_credentials_dict() -> dict:
    """Parse FIREBASE_SERVICE_ACCOUNT into a dict.

    The private key contains newlines. Depending on how the value was pasted
    into the environment it arrives either correctly escaped (``\\n`` inside the
    JSON string) or already expanded, which breaks ``json.loads``. Handle both.
    """
    from app.config import settings

    raw = settings.FIREBASE_SERVICE_ACCOUNT
    if not isinstance(raw, str):
        return dict(raw)

    try:
        cred_dict = json.loads(raw)
    except json.JSONDecodeError:
        # Real newlines were pasted into the JSON string — re-escape and retry.
        cred_dict = json.loads(raw.replace("\n", "\\n"))

    # Some secret stores strip the escaping on the way out; restore it so the
    # PEM parser sees real line breaks.
    key = cred_dict.get("private_key")
    if isinstance(key, str) and "\\n" in key:
        cred_dict["private_key"] = key.replace("\\n", "\n")

    return cred_dict


def get_firebase_app():
    """Return the initialised Firebase app, or ``None`` when unconfigured.

    Safe to call on every request — initialisation happens once and the result
    (including failure) is cached.
    """
    global _app, _init_failed

    if _app is not None:
        return _app
    if _init_failed or not firebase_configured():
        return None

    with _lock:
        if _app is not None:
            return _app
        if _init_failed:
            return None
        try:
            import firebase_admin
            from firebase_admin import credentials

            # Another code path (or a previous process fork) may have already
            # initialised the default app.
            if firebase_admin._apps:
                _app = firebase_admin.get_app()
                return _app

            cred_dict = _load_credentials_dict()
            _app = firebase_admin.initialize_app(
                credentials.Certificate(cred_dict)
            )
            logger.info(
                "Firebase Admin initialised (project=%s)",
                cred_dict.get("project_id"),
            )
            return _app
        except Exception as e:
            # Cache the failure: retrying per-request would stall every call.
            _init_failed = True
            logger.error(f"Firebase Admin init failed: {e}")
            return None


def reset_for_tests() -> None:
    """Clear the cached app so tests can re-init with different settings."""
    global _app, _init_failed
    _app = None
    _init_failed = False
