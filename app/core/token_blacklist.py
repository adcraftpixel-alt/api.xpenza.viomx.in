"""Refresh-token revocation on logout.

Access tokens are short-lived (settings.ACCESS_TOKEN_EXPIRE_MINUTES, default
60) and are never blacklisted — by the time a blacklist lookup would matter
they've nearly expired anyway. Refresh tokens live for
REFRESH_TOKEN_EXPIRE_DAYS (default 30), so logout needs to actually revoke
them or a leaked refresh token stays usable for a month regardless of logout.

Fails open (treats a token as not-blacklisted) if Redis is unreachable —
consistent with the rest of app/core/rate_limit.py.
"""
import logging

import redis as redis_lib

from app.config import settings

logger = logging.getLogger(__name__)

try:
    _redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    _redis.ping()
except Exception as e:
    logger.warning(f"token_blacklist: Redis unavailable at startup, failing open: {e}")
    _redis = None


def blacklist_token(jti: str, ttl_seconds: int) -> None:
    """Blacklist `jti` for `ttl_seconds` — pass the token's remaining lifetime
    so the blacklist entry expires exactly when the token would have anyway."""
    if _redis is None or not jti or ttl_seconds <= 0:
        return
    try:
        _redis.setex(f"blacklist:{jti}", ttl_seconds, "1")
    except Exception as e:
        logger.warning(f"token_blacklist: could not blacklist {jti}: {e}")


def is_blacklisted(jti: str) -> bool:
    if _redis is None or not jti:
        return False
    try:
        return _redis.exists(f"blacklist:{jti}") == 1
    except Exception as e:
        logger.warning(f"token_blacklist: check failed for {jti}, failing open: {e}")
        return False
