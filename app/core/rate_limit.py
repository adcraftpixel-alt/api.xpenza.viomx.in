"""Redis-backed request throttling, account lockout, and abuse alerting.

Everything here fails OPEN when Redis is unreachable (logs a warning and lets
the request through) rather than taking the API down — nginx's `limit_req`
zones (infrastructure/nginx/nginx.conf) are the backstop layer in front of
this, so a Redis outage degrades to "infra-level limiting only", not "no
limiting at all".
"""
import logging
import time
from contextlib import contextmanager
from typing import Optional

import redis as redis_lib
from fastapi import HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)

try:
    _redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
except Exception as e:
    logger.warning(f"rate_limit: Redis unavailable at startup, failing open: {e}")
    _redis = None


def get_client_ip(request: Request) -> str:
    """Best-effort client IP. Only nginx should ever be able to reach uvicorn
    directly (see infrastructure/nginx/nginx.conf), so the first hop in
    X-Forwarded-For is trusted."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _incr_with_ttl(key: str, window_seconds: int) -> int:
    if _redis is None:
        return 0
    try:
        pipe = _redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = pipe.execute()
        return int(count)
    except Exception as e:
        logger.warning(f"rate_limit: Redis error on {key}, failing open: {e}")
        return 0


# ── Per-IP / per-route request throttling ──────────────────────────────────

def enforce_rate_limit(
    key: str,
    limit: int,
    window_seconds: int,
    message: str = "Too many requests. Please try again later.",
) -> None:
    """Fixed-window counter. Raises 429 once `key` exceeds `limit` hits within
    `window_seconds`."""
    count = _incr_with_ttl(f"rl:{key}", window_seconds)
    if count > limit:
        ttl = window_seconds
        if _redis is not None:
            try:
                ttl = max(_redis.ttl(f"rl:{key}"), 1)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
            headers={"Retry-After": str(ttl)},
        )


GLOBAL_LIMIT = 300
GLOBAL_WINDOW = 60


def enforce_global_limit(ip: str) -> None:
    """Second layer behind nginx: caps total requests per IP across every
    route, so a script hammering a non-auth endpoint still gets throttled
    even when it's run directly against the backend (bypassing nginx)."""
    enforce_rate_limit(
        f"global:{ip}", GLOBAL_LIMIT, GLOBAL_WINDOW,
        message="Too many requests. Please slow down.",
    )


UNAUTHORIZED_ALERT_THRESHOLD = 20
UNAUTHORIZED_ALERT_WINDOW = 300


def note_unauthorized(ip: str) -> None:
    """Tracks 401 responses per IP across ALL endpoints (not just login) and
    fires one alert email per window once the spike threshold is crossed."""
    count = _incr_with_ttl(f"401count:{ip}", UNAUTHORIZED_ALERT_WINDOW)
    if count == UNAUTHORIZED_ALERT_THRESHOLD:
        _send_alert(
            f"401spike:{ip}",
            f"IP {ip} produced {count} HTTP 401 responses in "
            f"{UNAUTHORIZED_ALERT_WINDOW}s — possible credential stuffing "
            f"or stolen-token probing.",
        )


# ── Account / IP lockout with progressive delay ────────────────────────────

DEFAULT_FAIL_LIMIT = 5
DEFAULT_FAIL_WINDOW = 15 * 60
DEFAULT_LOCK_SECONDS = 15 * 60
PROGRESSIVE_DELAY_STEP = 0.4
PROGRESSIVE_DELAY_MAX = 2.0


def _norm(key: str) -> str:
    return key.strip().lower()


def check_lock(key: str) -> None:
    """Raise 423 if `key` (e.g. "login:alice@example.com" or "login-ip:1.2.3.4")
    is currently locked out."""
    if _redis is None:
        return
    try:
        ttl = _redis.ttl(f"lock:{_norm(key)}")
    except Exception as e:
        logger.warning(f"rate_limit: lock check failed for {key}, failing open: {e}")
        return
    if ttl and ttl > 0:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Too many failed attempts. Try again in {ttl} seconds.",
            headers={"Retry-After": str(ttl)},
        )


def record_failure(
    key: str,
    fail_limit: int = DEFAULT_FAIL_LIMIT,
    window_seconds: int = DEFAULT_FAIL_WINDOW,
    lock_seconds: int = DEFAULT_LOCK_SECONDS,
) -> int:
    """Increment the failure counter for `key`, lock it out once `fail_limit`
    is hit, and sleep briefly (capped) so scripted retries slow down well
    before the hard lockout lands. Returns the failure count."""
    if _redis is None:
        return 0
    norm_key = _norm(key)
    count = _incr_with_ttl(f"failcount:{norm_key}", window_seconds)
    if count <= 0:
        return count

    time.sleep(min(PROGRESSIVE_DELAY_STEP * count, PROGRESSIVE_DELAY_MAX))

    if count >= fail_limit:
        try:
            _redis.setex(f"lock:{norm_key}", lock_seconds, "1")
            _redis.delete(f"failcount:{norm_key}")
        except Exception as e:
            logger.warning(f"rate_limit: could not set lock for {key}: {e}")
        if count == fail_limit:
            _send_alert(
                f"lockout:{norm_key}",
                f"'{key}' was locked out after {fail_limit} failed attempts "
                f"within {window_seconds}s.",
            )
    return count


def record_success(key: str) -> None:
    if _redis is None:
        return
    norm_key = _norm(key)
    try:
        _redis.delete(f"failcount:{norm_key}")
        _redis.delete(f"lock:{norm_key}")
    except Exception:
        pass


@contextmanager
def track_outcome(
    *,
    ip: str,
    identifier: Optional[str] = None,
    ip_fail_limit: int = 20,
    ip_lock_seconds: int = 10 * 60,
    id_fail_limit: int = DEFAULT_FAIL_LIMIT,
    id_lock_seconds: int = DEFAULT_LOCK_SECONDS,
):
    """Wrap a login-style call: a 401 raised inside the block counts as a
    failed attempt for both the IP and the account identifier; anything else
    (success, or a non-401 error like 423/429) clears the failure streak."""
    try:
        yield
    except HTTPException as e:
        if e.status_code == status.HTTP_401_UNAUTHORIZED:
            record_failure(f"login-ip:{ip}", fail_limit=ip_fail_limit, lock_seconds=ip_lock_seconds)
            if identifier:
                record_failure(f"login:{identifier}", fail_limit=id_fail_limit, lock_seconds=id_lock_seconds)
        raise
    else:
        record_success(f"login-ip:{ip}")
        if identifier:
            record_success(f"login:{identifier}")


# ── CAPTCHA gate (disabled until CAPTCHA_PROVIDER is configured) ───────────

def _verify_turnstile(token: str) -> bool:
    import httpx
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.CAPTCHA_SECRET_KEY, "response": token},
            timeout=5,
        )
        return bool(resp.json().get("success"))
    except Exception as e:
        logger.error(f"Turnstile verification request failed: {e}")
        return False


def _verify_hcaptcha(token: str) -> bool:
    import httpx
    try:
        resp = httpx.post(
            "https://hcaptcha.com/siteverify",
            data={"secret": settings.CAPTCHA_SECRET_KEY, "response": token},
            timeout=5,
        )
        return bool(resp.json().get("success"))
    except Exception as e:
        logger.error(f"hCaptcha verification request failed: {e}")
        return False


def verify_captcha(token: Optional[str]) -> bool:
    if not settings.CAPTCHA_PROVIDER:
        # No provider configured — the gate is a no-op scaffold until one is
        # wired in (set CAPTCHA_PROVIDER + CAPTCHA_SECRET_KEY).
        return True
    if not token:
        return False
    if settings.CAPTCHA_PROVIDER == "turnstile":
        return _verify_turnstile(token)
    if settings.CAPTCHA_PROVIDER == "hcaptcha":
        return _verify_hcaptcha(token)
    logger.warning(f"Unknown CAPTCHA_PROVIDER '{settings.CAPTCHA_PROVIDER}', treating as disabled")
    return True


def enforce_captcha_if_required(ip: str, token: Optional[str]) -> None:
    """Once an IP has racked up CAPTCHA_FAIL_THRESHOLD failed logins, demand
    (and verify) a captcha token on subsequent attempts. No-op entirely until
    CAPTCHA_PROVIDER is set."""
    if not settings.CAPTCHA_PROVIDER:
        return
    if _redis is None:
        return
    try:
        fail_count = int(_redis.get(f"failcount:{_norm(f'login-ip:{ip}')}") or 0)
    except Exception:
        return
    if fail_count >= settings.CAPTCHA_FAIL_THRESHOLD and not verify_captcha(token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captcha verification required.",
        )


# ── Alerting ────────────────────────────────────────────────────────────

ALERT_COOLDOWN_SECONDS = 60 * 60


def _send_alert(dedupe_key: str, detail: str) -> None:
    """Fire-and-forget admin email, deduped so one sustained attack doesn't
    flood the admin's inbox — at most one email per dedupe_key per hour."""
    if _redis is not None:
        try:
            if not _redis.set(f"alerted:{dedupe_key}", "1", nx=True, ex=ALERT_COOLDOWN_SECONDS):
                return
        except Exception:
            pass  # if we can't dedupe, still try to send rather than stay silent

    logger.warning(f"[SECURITY ALERT] {detail}")
    try:
        from app.utils.email import send_email
        send_email(
            to_email=settings.ADMIN_ALERT_EMAIL,
            subject="[Rupexi] Security alert — possible brute-force activity",
            html_content=f"<pre>{detail}</pre>",
            plain_text=detail,
        )
    except Exception as e:
        logger.error(f"Could not send security alert email: {e}")
