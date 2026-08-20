"""
Tests for the auth security hardening layer: per-IP rate limiting, account
lockout, OTP send cooldown / verify-attempt cap, and refresh-token revocation
on logout. See app/core/rate_limit.py and app/core/token_blacklist.py.
"""
import os

import redis as redis_lib
from fastapi import HTTPException

from app.core import rate_limit

_redis = redis_lib.from_url(os.environ["REDIS_URL"], decode_responses=True)

# TEST-NET-3 (RFC 5737) — safe, non-routable, deterministic key for tests
# instead of relying on TestClient's internal client-IP string.
TEST_IP = "203.0.113.5"


def test_login_ip_rate_limit(client, registered_user):
    # Pre-seed the counter at the limit so one real request is enough to
    # observe the boundary, instead of 11 slow round trips.
    _redis.set(f"rl:login:ip:{TEST_IP}", 10, ex=60)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrong"},
        headers={"X-Forwarded-For": TEST_IP},
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_login_account_lockout(client, registered_user):
    # Pre-seed 4 prior failures so this request's failure trips the lock.
    _redis.set("failcount:login:test@example.com", 4, ex=900)
    fifth_fail = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrong"},
    )
    assert fifth_fail.status_code == 401  # this failure is the one that locks

    locked_out = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},  # correct pw
    )
    assert locked_out.status_code == 423
    assert "Retry-After" in locked_out.headers


def test_login_success_clears_failure_count(client, registered_user):
    _redis.set("failcount:login:test@example.com", 3, ex=900)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},
    )
    assert response.status_code == 200
    assert _redis.get("failcount:login:test@example.com") is None


def test_otp_send_cooldown(client):
    phone = "+919000000099"
    first = client.post("/api/v1/auth/send-otp", json={"phone": phone})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/send-otp", json={"phone": phone})
    assert second.status_code == 429


def test_otp_verify_attempt_cap(client):
    phone = "+919000000098"
    send = client.post("/api/v1/auth/send-otp", json={"phone": phone})
    assert send.status_code == 200

    # OTP is now randomly generated (app/api/v1/auth/service.py::send_otp) —
    # read the real code straight out of Redis instead of assuming a fixed
    # value, and pick a wrong guess guaranteed not to collide with it.
    real_otp = _redis.get(f"otp:{phone}")
    assert real_otp is not None
    wrong_otp = "000000" if real_otp != "000000" else "999999"

    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/verify-otp", json={"phone": phone, "otp": wrong_otp}
        )
        assert resp.status_code == 400

    # The real OTP is now rejected too — the code was invalidated once the
    # attempt cap was exceeded, forcing a resend instead of letting a script
    # grind through the keyspace.
    resp = client.post(
        "/api/v1/auth/verify-otp", json={"phone": phone, "otp": real_otp}
    )
    assert resp.status_code == 400


def test_refresh_token_revoked_after_logout(client, registered_user):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123!"},
    )
    assert login.status_code == 200
    refresh = login.json()["refresh_token"]

    logout = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert logout.status_code == 200

    reuse = client.post("/api/v1/auth/refresh-token", json={"refresh_token": refresh})
    assert reuse.status_code == 401


def test_reviewer_bypass_phone_skips_whatsapp(client, monkeypatch, caplog):
    """App Store/Play Store reviewer bypass (settings.REVIEWER_BYPASS_PHONE):
    this one number always gets the fixed OTP and never touches WhatsApp."""
    from app.config import settings

    bypass_phone = "+919878101955"
    monkeypatch.setattr(settings, "REVIEWER_BYPASS_PHONE", bypass_phone)
    monkeypatch.setattr(settings, "REVIEWER_BYPASS_OTP", "111111")

    with caplog.at_level("INFO"):
        send = client.post("/api/v1/auth/send-otp", json={"phone": bypass_phone})
    assert send.status_code == 200
    assert _redis.get(f"otp:{bypass_phone}") == "111111"
    assert any("[REVIEWER-BYPASS]" in r.getMessage() for r in caplog.records)

    verify = client.post(
        "/api/v1/auth/verify-otp", json={"phone": bypass_phone, "otp": "111111"}
    )
    assert verify.status_code == 200


def test_non_bypass_phone_still_uses_real_otp_flow(client, monkeypatch, caplog):
    from app.config import settings

    monkeypatch.setattr(settings, "REVIEWER_BYPASS_PHONE", "+919878101955")
    monkeypatch.setattr(settings, "REVIEWER_BYPASS_OTP", "111111")

    other_phone = "+919000000097"
    with caplog.at_level("INFO"):
        send = client.post("/api/v1/auth/send-otp", json={"phone": other_phone})
    assert send.status_code == 200
    stored = _redis.get(f"otp:{other_phone}")
    assert stored is not None and stored != "111111"
    assert not any("[REVIEWER-BYPASS]" in r.getMessage() for r in caplog.records)
    assert any("[OTP-DEV]" in r.getMessage() for r in caplog.records)


def test_global_limit_helper_enforces_ceiling():
    _redis.set("rl:global:198.51.100.9", rate_limit.GLOBAL_LIMIT, ex=60)
    try:
        rate_limit.enforce_global_limit("198.51.100.9")
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 429


def test_captcha_is_noop_when_no_provider_configured():
    # CAPTCHA_PROVIDER is "" by default (config.py) — the gate must never
    # block until a real provider is configured.
    assert rate_limit.verify_captcha(None) is True
    rate_limit.enforce_captcha_if_required("192.0.2.1", None)  # must not raise
