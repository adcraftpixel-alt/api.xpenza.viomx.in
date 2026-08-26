"""
Family invite → notification flow.

Covers two bugs fixed together:
1. Phone-format mismatch: users.phone is stored in inconsistent shapes
   (bare 10-digit vs +91 E.164, see auth/service.py:normalize_phone). The
   invite/accept code used to match phones with exact `==`, so an invite
   sent to a differently-formatted (but same) number silently failed to
   link the invitee, notify them, or let them see/accept the invite.
2. The inviter was never notified when their invite got accepted.
"""


def _register_login(client, name, email, phone):
    client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "phone": phone, "password": "TestPass123!",
    })
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_invite_matches_despite_phone_format_mismatch(client):
    """Invitee registered with a bare 10-digit phone; inviter invites using
    the full +91 E.164 form. The invite must still auto-link to the invitee,
    notify them, and show up in their pending invites."""
    owner = _register_login(client, "Owner", "owner2@example.com", "+919000000030")
    # Bob registers with a BARE national number (no +91) — this is what the
    # register screen historically sent (see normalize_phone's docstring).
    bob = _register_login(client, "Bob", "bob2@example.com", "9000000031")

    client.post("/api/v1/family/groups", json={"name": "Fam"}, headers=owner)

    # Owner invites Bob using the FULL E.164 form — different shape than
    # what's stored on Bob's user row.
    r = client.post("/api/v1/family/invite",
                    json={"phone": "+919000000031"}, headers=owner)
    assert r.status_code == 200, r.text
    # Auto-linked immediately since Bob is already a user.
    assert r.json()["data"]["user_id"], "invite did not auto-link to existing user"

    # Bob sees the pending invite despite the format mismatch.
    invites = client.get("/api/v1/family/invites/pending", headers=bob).json()["data"]
    assert invites, "Bob has no pending invite despite phone format mismatch"

    # Bob got an in-app notification about the invite.
    notifs = client.get("/api/v1/notifications", headers=bob).json()["data"]
    items = notifs.get("items", notifs) if isinstance(notifs, dict) else notifs
    assert any(n.get("type") == "family_invite" for n in items), \
        f"Bob never received a family_invite notification: {items}"

    # Bob accepts.
    gid = invites[0]["group_id"]
    acc = client.post("/api/v1/family/invites/accept",
                      json={"group_id": gid}, headers=bob)
    assert acc.status_code == 200, acc.text
    assert acc.json()["data"]["status"] == "accepted"


def test_inviter_notified_when_invite_accepted(client):
    """When B accepts A's invite, A gets an in-app notification (previously
    nothing happened — A had to manually refresh to discover it)."""
    owner = _register_login(client, "Owner3", "owner3@example.com", "+919000000040")
    mem = _register_login(client, "Mem3", "mem3@example.com", "+919000000041")

    client.post("/api/v1/family/groups", json={"name": "Fam3"}, headers=owner)
    client.post("/api/v1/family/invite", json={"phone": "+919000000041"}, headers=owner)

    invites = client.get("/api/v1/family/invites/pending", headers=mem).json()["data"]
    gid = invites[0]["group_id"]
    client.post("/api/v1/family/invites/accept", json={"group_id": gid}, headers=mem)

    notifs = client.get("/api/v1/notifications", headers=owner).json()["data"]
    items = notifs.get("items", notifs) if isinstance(notifs, dict) else notifs
    assert any(n.get("type") == "family_join" for n in items), \
        f"Owner never received a family_join notification: {items}"
