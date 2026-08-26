"""
New users must have a real category tree from the moment they register —
not only after completing onboarding. Covers the gap where expenses logged
before onboarding finished had nowhere real to attach a category to.
"""


def test_categories_seeded_immediately_on_register(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "Newbie", "email": "newbie1@example.com",
        "phone": "+919000000050", "password": "TestPass123!",
    })
    assert r.status_code == 200, r.text
    login = client.post("/api/v1/auth/login",
                        json={"email": "newbie1@example.com", "password": "TestPass123!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    tree = client.get("/api/v1/categories/tree", headers=headers).json()["data"]
    assert tree, "brand-new user has no categories before onboarding"
    names = {c["name"] for c in tree}
    assert "Groceries" in names
    assert "General" in names


def test_categories_seeded_immediately_on_phone_register(client, db):
    from app.models.category import Category

    r = client.post("/api/v1/auth/register-phone",
                    json={"name": "PhoneUser", "phone": "+919000000051"})
    assert r.status_code == 200, r.text
    user_id = r.json()["data"]["id"]

    roots = db.query(Category).filter(
        Category.user_id == user_id, Category.parent_id.is_(None)
    ).all()
    assert roots, "phone-registered user has no seeded categories"
    assert any(c.name == "General" for c in roots)


def test_categories_seeded_immediately_on_send_otp_autocreate(client, db):
    """POST /auth/send-otp auto-creates a user if the phone isn't registered
    (router.py's own creation path, separate from AuthService)."""
    from app.models.user import User
    from app.models.category import Category

    r = client.post("/api/v1/auth/send-otp", json={"phone": "+919000000053"})
    assert r.status_code == 200, r.text

    user = db.query(User).filter(User.phone == "+919000000053").first()
    assert user is not None
    roots = db.query(Category).filter(
        Category.user_id == str(user.id), Category.parent_id.is_(None)
    ).all()
    assert roots, "send-otp auto-created user has no seeded categories"


def test_general_fallback_category_exists_and_resolves(client):
    """A description that matches nothing (no keyword, no LLM key in tests)
    must still resolve to a real 'General' category, not category_id=None."""
    owner = client.post("/api/v1/auth/register", json={
        "name": "Gen", "email": "gen1@example.com",
        "phone": "+919000000052", "password": "TestPass123!",
    })
    assert owner.status_code == 200, owner.text
    login = client.post("/api/v1/auth/login",
                        json={"email": "gen1@example.com", "password": "TestPass123!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = client.post("/api/v1/expenses/suggest-category",
                    json={"description": "zzz_totally_unmatchable_gibberish_zzz"},
                    headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["category_name"] == "General"
    assert data["category_id"] is not None, \
        "General fallback matched by name but no real category_id returned"
