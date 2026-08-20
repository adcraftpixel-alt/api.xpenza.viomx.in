"""HMAC request signing for the Rupexi <-> VIOMX Control Hub service APIs.

Replaces sending the shared secret itself on every request (a bare
X-Product-Key / X-Service-Key string compare) with proving knowledge of it:
the caller signs {timestamp}.{nonce}.{body} with HMAC-SHA256 and the secret
never goes over the wire. A timestamp window plus a per-nonce replay guard
also close the "captured request replayed later" gap a static key comparison
left open.

Single-instance, in-memory nonce cache — same reasoning as
app/core/rate_limit.py: no confirmed Redis/multi-instance deployment for this
app, so a module-level dict is the honest match for the actual deployment
reality. This bounds replay of a leaked/logged request, not distributed abuse.
"""
import hashlib
import hmac
import secrets
import time

REPLAY_WINDOW_SECONDS = 300  # 5 minutes — bounds clock skew and replay alike.

_seen_nonces: dict[str, float] = {}


def _prune(now: float) -> None:
    cutoff = now - REPLAY_WINDOW_SECONDS
    for nonce, seen_at in list(_seen_nonces.items()):
        if seen_at < cutoff:
            del _seen_nonces[nonce]


def _sign(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    msg = f"{timestamp}.{nonce}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def signed_headers(secret: str, body: bytes = b"") -> dict:
    """Headers for an outbound signed request. Call fresh per request —
    timestamp+nonce must be unique each time for replay protection to mean
    anything (two legitimate identical requests must still produce distinct
    signatures)."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(8)
    return {
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": _sign(secret, timestamp, nonce, body),
    }


def verify(
    secret: str,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    body: bytes,
) -> tuple[bool, str]:
    """Verify an inbound signed request. Returns (ok, reason-if-not-ok)."""
    if not timestamp or not nonce or not signature:
        return False, "Missing timestamp, nonce, or signature"
    try:
        ts = float(timestamp)
    except ValueError:
        return False, "Invalid timestamp"

    now = time.time()
    if abs(now - ts) > REPLAY_WINDOW_SECONDS:
        return False, "Timestamp outside allowed window"

    expected = _sign(secret, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        return False, "Invalid signature"

    _prune(now)
    if nonce in _seen_nonces:
        return False, "Replayed nonce"
    _seen_nonces[nonce] = now
    return True, ""
