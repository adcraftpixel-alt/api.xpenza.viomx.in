"""
Tests for PUT /users/me — profile updates and Control Hub re-sync.
"""


def test_update_me_name_email_syncs_to_control_hub(client, auth_headers, db, monkeypatch):
    """Onboarding submits the user's real name/email via PUT /users/me; this
    must re-register the tenant with the Control Hub so it stops seeing the
    phone-placeholder name / synthetic email from initial login."""
    from app.services import control_hub

    calls = []
    monkeypatch.setattr(control_hub, "is_configured", lambda: True)
    monkeypatch.setattr(
        control_hub, "register_tenant",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    me = client.get("/api/v1/users/me", headers=auth_headers).json()["data"]

    response = client.put(
        "/api/v1/users/me",
        json={"name": "Real Full Name", "email": "real.email@example.com"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    assert len(calls) == 1
    assert calls[0]["external_user_id"] == me["id"]
    assert calls[0]["name"] == "Real Full Name"
    assert calls[0]["email"] == "real.email@example.com"


def test_update_me_without_name_or_email_does_not_sync(client, auth_headers, monkeypatch):
    """Unrelated profile updates (e.g. monthly_income, onboarding_done) must
    not trigger a redundant Control Hub call."""
    from app.services import control_hub

    calls = []
    monkeypatch.setattr(control_hub, "is_configured", lambda: True)
    monkeypatch.setattr(
        control_hub, "register_tenant",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    response = client.put(
        "/api/v1/users/me",
        json={"monthly_income": 50000, "onboarding_done": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert calls == []
