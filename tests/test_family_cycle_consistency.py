"""
Consistency check: the family expense screen (/expenses?shared=true&cycle_month)
and the family dashboard (/family/expenses?year&month) must return the SAME
family expenses for the same cycle — both honoring the family group's
month_start_day. Also verifies personal scope excludes family expenses.

Uses a fixed past month (March 2025) so the cycle window is deterministic
regardless of the real system clock (resolve_anchor only snaps for the
current calendar month).
"""


def _register_login(client, name, email, phone):
    client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "phone": phone, "password": "TestPass123!",
    })
    r = client.post("/api/v1/auth/login",
                    json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _me_id(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()["data"]["id"]


def test_family_spend_attribution(client):
    """Owner can log a spend on behalf of another member; member_totals
    attributes it to that member, not the logger."""
    from datetime import date as _date
    owner = _register_login(client, "Owner", "owner@example.com", "+919000000010")
    neetika = _register_login(client, "Neetika", "neetika@example.com",
                              "+919000000011")
    neetika_id = _me_id(client, neetika)

    gid = client.post("/api/v1/family/groups", json={"name": "Fam"},
                      headers=owner).json()["data"]["id"]

    # Invite Neetika (auto-links since she has an account) and accept.
    assert client.post("/api/v1/family/invite",
                       json={"phone": "+919000000011"},
                       headers=owner).status_code == 200
    invites = client.get("/api/v1/family/invites/pending",
                         headers=neetika).json()["data"]
    assert invites, "Neetika has no pending invite"
    assert client.post("/api/v1/family/invites/accept",
                       json={"group_id": invites[0]["group_id"]},
                       headers=neetika).status_code == 200

    today = _date.today().isoformat()
    # Owner's own family spend
    client.post("/api/v1/expenses", json={
        "amount": 300, "expense_date": today, "description": "owner spend",
        "family_group_id": gid,
    }, headers=owner)
    # Owner logs a spend ON BEHALF OF Neetika
    client.post("/api/v1/expenses", json={
        "amount": 700, "expense_date": today, "description": "neetika spend",
        "family_group_id": gid, "spent_by_user_id": neetika_id,
    }, headers=owner)

    now = _date.today()
    fam = client.get(
        f"/api/v1/family/expenses?year={now.year}&month={now.month}",
        headers=owner)
    assert fam.status_code == 200, fam.text
    totals = fam.json()["data"]["member_totals"]
    owner_key = next(k for k in totals if "(Me)" in k)
    neetika_key = next(k for k in totals if "Neetika" in k)
    assert totals[owner_key] == 300, totals      # NOT 1000
    assert totals[neetika_key] == 700, totals     # attributed to the member


def test_family_budget_uses_family_cycle_and_all_members(client):
    """A shared family budget's spend counts ALL members' group expenses in the
    FAMILY cycle window (not just the owner's, not the owner's personal cycle)."""
    from datetime import date as _date
    owner = _register_login(client, "Owner", "owner@example.com", "+919000000020")
    member = _register_login(client, "Mem", "mem@example.com", "+919000000021")
    member_id = _me_id(client, member)

    # Owner uses an 8th-of-month cycle → the family group inherits it.
    client.put("/api/v1/users/preferences",
               json={"month_start_day": 8}, headers=owner)

    gid = client.post("/api/v1/family/groups", json={"name": "Fam"},
                      headers=owner).json()["data"]["id"]
    client.post("/api/v1/family/invite", json={"phone": "+919000000021"},
                headers=owner)
    invites = client.get("/api/v1/family/invites/pending",
                         headers=member).json()["data"]
    client.post("/api/v1/family/invites/accept",
                json={"group_id": invites[0]["group_id"]}, headers=member)

    # Pick a root category from the shared family tree.
    tree = client.get(f"/api/v1/categories/tree?family_group_id={gid}",
                      headers=owner).json()["data"]
    assert tree, "family tree empty"
    cat_id = tree[0]["id"]

    today = _date.today().isoformat()
    # Owner's family expense + owner-logged spend on behalf of the member,
    # both in that category and dated today (inside the current cycle).
    client.post("/api/v1/expenses", json={
        "amount": 300, "expense_date": today, "description": "owner",
        "family_group_id": gid, "category_id": cat_id,
    }, headers=owner)
    client.post("/api/v1/expenses", json={
        "amount": 700, "expense_date": today, "description": "member",
        "family_group_id": gid, "category_id": cat_id,
        "spent_by_user_id": member_id,
    }, headers=owner)

    # Shared budget on that category.
    client.post("/api/v1/budgets", json={
        "name": "Household", "amount": 5000, "category_id": cat_id,
        "start_date": today, "is_shared": True,
    }, headers=owner)

    now = _date.today()
    budgets = client.get(
        f"/api/v1/budgets?shared=true&month={now.month}&year={now.year}",
        headers=owner).json()["data"]
    assert budgets, "no shared budget returned"
    b = budgets[0]
    # Spend = BOTH members' family expenses in the family cycle window = 1000.
    assert float(b["spent"]) == 1000.0, b


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
