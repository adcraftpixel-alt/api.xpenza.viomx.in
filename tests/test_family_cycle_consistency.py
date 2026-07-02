"""
Consistency check: the family expense screen (/expenses?shared=true&cycle_month)
and the family dashboard (/family/expenses?year&month) must return the SAME
family expenses for the same cycle — both honoring the family group's
month_start_day. Also verifies personal scope excludes family expenses.

Uses a fixed past month (March 2025) so the cycle window is deterministic
regardless of the real system clock (resolve_anchor only snaps for the
current calendar month).
"""


def _auth(client, email):
    client.post("/api/v1/auth/register", json={
        "name": "Cycle User", "email": email,
        "phone": "+919000000001", "password": "TestPass123!",
    })
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _mk_expense(client, headers, amount, dt, *, family_group_id=None):
    payload = {
        "amount": amount, "expense_date": dt, "description": f"exp-{amount}",
        "payment_method": "upi", "currency": "INR",
    }
    if family_group_id:
        payload["family_group_id"] = family_group_id
    r = client.post("/api/v1/expenses", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def test_family_endpoints_agree_on_cycle_window(client):
    headers = _auth(client, "cycle@example.com")

    # Personal salary cycle = 8th → the family group inherits this on creation.
    r = client.put("/api/v1/users/preferences",
                   json={"month_start_day": 8}, headers=headers)
    assert r.status_code == 200, r.text

    g = client.post("/api/v1/family/groups",
                    json={"name": "Test Family"}, headers=headers)
    assert g.status_code == 200, g.text
    group = g.json()["data"]
    gid = group["id"]
    # Group inherited the creator's cycle
    assert group["month_start_day"] == 8, group

    # Cycle window for (2025-03) with start day 8 = 2025-03-08 .. 2025-04-07
    inside = [
        _mk_expense(client, headers, 100, "2025-03-10", family_group_id=gid),
        _mk_expense(client, headers, 200, "2025-03-25", family_group_id=gid),
        _mk_expense(client, headers, 300, "2025-04-07", family_group_id=gid),  # last day
    ]
    outside = [
        _mk_expense(client, headers, 400, "2025-03-05", family_group_id=gid),  # before start
        _mk_expense(client, headers, 500, "2025-04-08", family_group_id=gid),  # next cycle
    ]
    # Personal (no family_group_id) — must never appear in family results
    personal = [
        _mk_expense(client, headers, 999, "2025-03-10"),
    ]

    # 1) Family dashboard endpoint
    fam = client.get("/api/v1/family/expenses?year=2025&month=3", headers=headers)
    assert fam.status_code == 200, fam.text
    fam_data = fam.json()["data"]
    fam_ids = {e["id"] for e in fam_data["expenses"]}

    # 2) Family expense-screen endpoint
    shared = client.get(
        "/api/v1/expenses?limit=200&cycle_month=2025-03&shared=true",
        headers=headers)
    assert shared.status_code == 200, shared.text
    shared_ids = {e["id"] for e in shared.json()["data"]["items"]}

    # Both must return exactly the in-window family expenses — and agree.
    assert fam_ids == set(inside), f"dashboard={fam_ids} expected={set(inside)}"
    assert shared_ids == set(inside), f"screen={shared_ids} expected={set(inside)}"
    assert fam_ids == shared_ids, "family screen and dashboard disagree!"

    # Out-of-window and personal expenses excluded from family views
    for oid in outside + personal:
        assert oid not in fam_ids
        assert oid not in shared_ids

    # 3) Personal scope uses the same cycle window but only personal expenses
    pers = client.get("/api/v1/expenses?limit=200&cycle_month=2025-03",
                      headers=headers)
    assert pers.status_code == 200, pers.text
    pers_ids = {e["id"] for e in pers.json()["data"]["items"]}
    assert pers_ids == set(personal), f"personal={pers_ids}"
    # Family expenses must NOT leak into personal
    for fid in inside + outside:
        assert fid not in pers_ids

    # 4) Auto-follow: changing the OWNER's personal cycle changes the family
    #    cycle too — without any group-level setting call. Prove the family
    #    window shifts to day 15 (2025-03-15 .. 2025-04-14): the 03-10 expense
    #    drops out and the 04-08 expense (previously outside) comes in.
    r = client.put("/api/v1/users/preferences",
                   json={"month_start_day": 15}, headers=headers)
    assert r.status_code == 200, r.text

    me = client.get("/api/v1/family/groups/me", headers=headers)
    assert me.json()["data"]["month_start_day"] == 15, "family didn't follow owner"

    fam2 = client.get("/api/v1/family/expenses?year=2025&month=3", headers=headers)
    fam2_data = fam2.json()["data"]
    assert fam2_data["month_start_day"] == 15
    assert fam2_data["period_start"] == "2025-03-15"
    assert fam2_data["period_end"] == "2025-04-14"
    fam2_ids = {e["id"] for e in fam2_data["expenses"]}
    assert inside[0] not in fam2_ids       # 2025-03-10 now before the window
    assert outside[1] in fam2_ids          # 2025-04-08 now inside the window
